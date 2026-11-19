import io
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import UUID

import pymysql
from docx import Document
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pypdf import PdfReader
from starlette.concurrency import run_in_threadpool

from . import db
from .agent import answer
from .config import settings
from .mock_search import PAPERS, search_mock_papers
from .reading import DOI_RE, classify_reference, process_reading_task
from .pdf_export import render_text_pdf
from .zotero_local import ZoteroClient, ZoteroError, export_search_papers, export_reading_task
from .scholar_serpapi import ScholarSearchError, search_google_scholar
from .openalex_search import OpenAlexSearchError, search_openalex
from .markdown_render import render_assistant_markdown
from .report_template import CONTENT_TYPES, EXTENSIONS, MAX_TEMPLATE_BYTES, extract_template, render_office_document
from .file_names import original_pdf_name, chinese_pdf_name, report_name

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await run_in_threadpool(db.init_db)
        await run_in_threadpool(db.backfill_reading_library)
        app.state.db_error = None
        pending = await run_in_threadpool(db.recover_reading_tasks)
        for task_id in pending:
            asyncio.create_task(run_in_threadpool(process_reading_task, task_id))
    except Exception as exc:
        app.state.db_error = str(exc)
        log.warning("MySQL 尚未连接：%s", exc)
    yield


app = FastAPI(title="个人论文助手", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


def require_db():
    if app.state.db_error:
        raise HTTPException(503, "MySQL 未连接；请检查 .env 中的 MYSQL_PASSWORD 并重启服务")


def valid_id(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError):
        raise HTTPException(400, "无效的 ID")


def serialize(value):
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(request, "home.html")


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/search", response_class=HTMLResponse)
async def literature_search_page(request: Request):
    version = max((ROOT / 'static' / name).stat().st_mtime_ns for name in ('search.js', 'search.css'))
    return templates.TemplateResponse(request, "search.html", {'static_version': version})


@app.get("/library", response_class=HTMLResponse)
async def library_page(request: Request):
    return templates.TemplateResponse(request, "library.html")


@app.get("/reading", response_class=HTMLResponse)
async def reading_page(request: Request):
    return templates.TemplateResponse(request, "reading.html")


@app.get("/tasks", response_class=HTMLResponse)
async def task_records_page(request: Request):
    return templates.TemplateResponse(request, "tasks.html")


@app.get('/settings', response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request, 'settings.html')


class SettingsRequest(BaseModel):
    user_name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=160)
    literature_language: str
    search_count: int = Field(ge=10, le=100)
    search_collection: str = Field(min_length=1, max_length=100)
    reading_collection: str = Field(min_length=1, max_length=100)


class SearchIdsRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)


class ReadSearchRequest(BaseModel):
    id: str = Field(min_length=1, max_length=100)


class ImportLibraryRequest(SearchIdsRequest):
    topic_id: str


@app.get('/api/settings')
async def get_settings():
    require_db()
    return await run_in_threadpool(db.get_app_settings)


@app.put('/api/settings')
async def put_settings(payload: SettingsRequest):
    require_db()
    data = payload.model_dump()
    data['user_name'] = data['user_name'].strip()
    data['email'] = data['email'].strip()
    data['search_collection'] = data['search_collection'].strip()
    data['reading_collection'] = data['reading_collection'].strip()
    if not data['user_name'] or not data['search_collection'] or not data['reading_collection']:
        raise HTTPException(400, '姓名和 Zotero 目录名称不能为空')
    if '@' not in data['email'] or data['email'].startswith('@') or data['email'].endswith('@'):
        raise HTTPException(400, '邮箱格式不正确')
    if data['literature_language'] not in {'zh','en','all'}:
        raise HTTPException(400, '使用偏好不正确')
    await run_in_threadpool(db.update_app_settings, data)
    return await run_in_threadpool(db.get_app_settings)


@app.post('/api/settings/report-template')
async def upload_report_template(file: UploadFile = File(...)):
    require_db()
    filename = Path(file.filename or '').name[:255]
    body = await file.read(MAX_TEMPLATE_BYTES + 1)
    try:
        format_name, template_text = await run_in_threadpool(extract_template, filename, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await run_in_threadpool(db.save_report_template, filename, format_name, template_text, body)
    return {'filename': filename, 'format': format_name}


@app.get('/api/settings/report-template')
async def download_report_template():
    require_db()
    template = await run_in_threadpool(db.get_report_template, True)
    if not template or not template['report_template_body']:
        raise HTTPException(404, '尚未上传阅读报告模板')
    format_name = template['report_template_format']
    return Response(template['report_template_body'], media_type=CONTENT_TYPES[format_name],
        headers={'Content-Disposition':f'attachment; filename=report-template.{EXTENSIONS[format_name]}',
            'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@app.delete('/api/settings/report-template')
async def remove_report_template():
    require_db()
    await run_in_threadpool(db.delete_report_template)
    return {'ok': True}


@app.post('/api/settings/avatar')
async def upload_avatar(file: UploadFile = File(...)):
    require_db()
    if file.content_type not in {'image/png','image/jpeg','image/webp'}:
        raise HTTPException(400, '头像仅支持 PNG、JPG 或 WEBP')
    body = await file.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise HTTPException(413, '头像不能超过 2 MB')
    if not body or not (body.startswith(b'\x89PNG\r\n\x1a\n') or body.startswith(b'\xff\xd8\xff') or body.startswith(b'RIFF') and body[8:12] == b'WEBP'):
        raise HTTPException(400, '图片内容无效')
    await run_in_threadpool(db.save_avatar, body, file.content_type)
    return {'ok': True}


@app.get('/api/settings/avatar')
async def avatar():
    require_db()
    row = await run_in_threadpool(db.get_avatar)
    if not row or not row['avatar_body']:
        raise HTTPException(404, '尚未设置头像')
    return Response(row['avatar_body'], media_type=row['avatar_mime'], headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


def zotero_status():
    saved = db.get_app_settings()
    client = ZoteroClient()
    try:
        server_id = client.probe()
        connected = saved['zotero_connected'] and saved['zotero_server_id'] == server_id
        return {'running':True,'connected':connected,
            'server_matches':saved['zotero_server_id'] == server_id,
            'message':'本地 API 可用，已保存写入授权；实际写入将在导入时验证' if connected else 'Zotero 已运行，尚未授权写入'}
    except ZoteroError as exc:
        return {'running':False,'connected':False,'server_matches':False,'message':str(exc)}
    finally:
        client.close()


@app.get('/api/zotero/status')
async def get_zotero_status():
    require_db()
    return await run_in_threadpool(zotero_status)


def connect_zotero():
    client = ZoteroClient()
    try:
        server_id, key = client.authorize()
        db.save_zotero_connection(server_id, key, True)
        return {'connected':True,'message':'已连接 Zotero'}
    finally:
        client.close()


@app.post('/api/zotero/connect')
async def post_zotero_connect():
    require_db()
    try:
        return await run_in_threadpool(connect_zotero)
    except ZoteroError as exc:
        raise HTTPException(502, str(exc))


@app.post('/api/zotero/disconnect')
async def post_zotero_disconnect():
    require_db()
    await run_in_threadpool(db.clear_zotero_connection)
    return {'connected':False}


def resolve_search_papers(ids):
    index = {paper['id']:paper for paper in PAPERS}
    cached = {paper['id']:paper for paper in db.cached_search_papers([item for item in ids if item not in index])}
    combined = {**index,**cached}
    if any(item not in combined for item in ids):
        raise ValueError('包含无效或未检索到的文献 ID')
    return [combined[item] for item in ids]


@app.post('/api/zotero/search/import')
async def import_search_to_zotero(payload: SearchIdsRequest):
    require_db()
    if len(payload.ids) != len(set(payload.ids)):
        raise HTTPException(400, '选中文献不能重复')
    try:
        papers = await run_in_threadpool(resolve_search_papers,payload.ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    try:
        return await run_in_threadpool(export_search_papers, papers)
    except ZoteroError as exc:
        raise HTTPException(502, str(exc))


def make_reading_pdfs(task):
    return (task.get('translation_pdf') or (render_text_pdf(f'{task["title"]} — 中文翻译', task['translation']) if task.get('translation') else None),
        render_text_pdf(f'{task["title"]} — 阅读报告', task['report']))


@app.post('/api/zotero/reading/{task_id}/import')
async def import_reading_to_zotero(task_id: str):
    require_db()
    task = await run_in_threadpool(db.get_reading_task, valid_id(task_id), True)
    if not task:
        raise HTTPException(404, '精读任务不存在')
    if task['status'] != 'completed' or not task.get('pdf_body') or not task.get('report') or (task.get('document_language') != 'zh' and not task.get('translation')):
        raise HTTPException(409, '精读任务尚未生成完整的原文和报告')
    try:
        translation_pdf, report_pdf = await run_in_threadpool(make_reading_pdfs, task)
        return await run_in_threadpool(export_reading_task, task, translation_pdf, report_pdf)
    except (ZoteroError, RuntimeError) as exc:
        raise HTTPException(502, str(exc))


class MockSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    sources: list[str] = Field(min_length=1, max_length=2)
    year_from: int = Field(ge=1900, le=2100)
    year_to: int = Field(ge=1900, le=2100)
    count: int = Field(ge=1, le=100)
    sort: str = "relevance"
    record: bool = False


class LiteratureSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    language: str
    year_from: int = Field(ge=1900, le=2100)
    year_to: int = Field(ge=1900, le=2100)
    count: int = Field(ge=1, le=100)
    sort: str = 'relevance'
    record: bool = False


@app.post("/api/search/mock")
async def mock_literature_search(payload: MockSearchRequest):
    if len(payload.query.strip()) < 2:
        raise HTTPException(400, "请至少输入 2 个字符")
    if payload.year_from > payload.year_to:
        raise HTTPException(400, "起始年份不能晚于结束年份")
    if len(set(payload.sources)) != len(payload.sources) or not set(payload.sources) <= {"CNKI", "Google Scholar"}:
        raise HTTPException(400, "无效的检索来源")
    if payload.sort not in {"relevance", "year_asc", "year_desc"}:
        raise HTTPException(400, "无效的排序方式")
    result = search_mock_papers(payload.query.strip(), payload.sources, payload.year_from, payload.year_to, payload.count, payload.sort)
    if payload.record and not app.state.db_error:
        try:
            result['search_task_id'] = await run_in_threadpool(db.create_search_task,
                payload.query.strip(), payload.sources, payload.year_from, payload.year_to,
                payload.count, payload.sort, result['returned'],result)
        except pymysql.MySQLError:
            log.exception('检索记录保存失败')
    return result


def search_literature_sources(query, year_from, year_to, count, sort, language):
    openalex_error = None
    try:
        result = search_openalex(query, year_from, year_to, count, sort, language)
    except OpenAlexSearchError as exc:
        openalex_error = str(exc)
        result = {'total': 0, 'returned': 0, 'items': [], 'mock': False, 'provider': 'OpenAlex'}
    if len(result['items']) < count:
        try:
            scholar = search_google_scholar(query, year_from, year_to,
                count - len(result['items']), sort, language)
            known = {str(item.get('doi') or '').casefold() or item['title'].casefold()
                     for item in result['items']}
            for paper in scholar['items']:
                title = paper['title']
                # Scholar's language parameter is a preference; verify the returned title too.
                has_han = any('\u4e00' <= char <= '\u9fff' for char in title)
                if (language == 'zh') != has_han:
                    continue
                identity = str(paper.get('doi') or '').casefold() or title.casefold()
                if identity not in known:
                    known.add(identity)
                    result['items'].append(paper)
            if scholar['items']:
                result['provider'] = ('OpenAlex + SerpApi Google Scholar'
                                      if result['total'] and not openalex_error else 'SerpApi Google Scholar')
            if openalex_error:
                result['total'] = scholar['total']
        except ScholarSearchError as exc:
            if not result['items']:
                raise ValueError(f'{openalex_error or "OpenAlex 未检索到文献"}；SerpApi 兜底失败：{exc}') from exc
            result['warning'] = f'SerpApi 补充检索失败：{exc}'
    result['items'] = result['items'][:count]
    result['returned'] = len(result['items'])
    result['language'] = language
    if openalex_error and result['items']:
        result['warning'] = f'OpenAlex 检索失败，已改用 SerpApi：{openalex_error}'
    return result


@app.post('/api/search')
async def literature_search(payload: LiteratureSearchRequest):
    require_db()
    if len(payload.query.strip()) < 2 or payload.year_from > payload.year_to or payload.sort not in {'relevance','year_asc','year_desc'} or payload.language not in {'zh', 'en'}:
        raise HTTPException(400, '检索条件不正确')
    try:
        result = await run_in_threadpool(search_literature_sources, payload.query.strip(), payload.year_from,
            payload.year_to, payload.count, payload.sort, payload.language)
    except ValueError as exc:
        raise HTTPException(502,str(exc))
    await run_in_threadpool(db.cache_search_papers,result['items'])
    if payload.record:
        result['search_task_id'] = await run_in_threadpool(db.create_search_task,
            payload.query.strip(),[payload.language],payload.year_from,payload.year_to,
            payload.count,payload.sort,result['returned'],result)
    return result


@app.get('/api/search-history/latest')
async def latest_search_history():
    require_db()
    task_id = await run_in_threadpool(db.get_latest_search_task_id)
    return await search_history(task_id) if task_id else None


@app.get('/api/search-history/{task_id}')
async def search_history(task_id: str):
    require_db()
    row = await run_in_threadpool(db.get_search_task, valid_id(task_id))
    if not row:
        raise HTTPException(404, '检索任务不存在')
    if row['result'] is None and set(row['sources']) <= {'CNKI', 'Google Scholar'} and row['sources'] != ['Google Scholar']:
        snapshot = search_mock_papers(row['query_text'],row['sources'],row['year_from'],row['year_to'],
            row['requested_count'],row['sort_order'])
        await run_in_threadpool(db.save_search_result,row['id'],snapshot)
        row['result'] = snapshot
    return serialize(row)


@app.get('/api/home/recent')
async def home_recent(limit: int = 3):
    require_db()
    if not 1 <= limit <= 100:
        raise HTTPException(400, '最近任务数量必须为 1 到 100')
    return serialize(await run_in_threadpool(db.list_home_recent, limit))


@app.post('/api/library/import', status_code=201)
async def import_library(payload: ImportLibraryRequest):
    require_db()
    topic_id = valid_id(payload.topic_id)
    if not await run_in_threadpool(db.library_topic_exists, topic_id):
        raise HTTPException(404, '文献主题不存在')
    if len(payload.ids) != len(set(payload.ids)):
        raise HTTPException(400, '选中文献不能重复')
    try:
        papers = await run_in_threadpool(resolve_search_papers,payload.ids)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    imported = await run_in_threadpool(db.import_search_papers, papers, topic_id)
    return {'imported': imported, 'already_exists': len(payload.ids) - imported, 'total': len(payload.ids), 'topic_id':topic_id}


@app.get('/api/library/topics')
async def library_topics():
    require_db()
    return serialize(await run_in_threadpool(db.list_library_topics))


class TopicRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@app.post('/api/library/topics', status_code=201)
async def create_library_topic(payload: TopicRequest):
    require_db()
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, '主题名称不能为空')
    try:
        return await run_in_threadpool(db.create_library_topic, name)
    except pymysql.err.IntegrityError:
        raise HTTPException(409, '该主题已经存在')


@app.get('/api/library')
async def library_papers(q: str = '', source: str = 'all', category: str = 'all', topic_id: str | None = None):
    require_db()
    if source not in {'all', 'CNKI', 'Google Scholar', 'OpenAlex', '本地上传', 'DOI', 'arXiv'}:
        raise HTTPException(400, '无效的文献来源')
    if category not in {'all','theme','reading'}:
        raise HTTPException(400, '无效的文献库分类')
    if topic_id:
        topic_id = valid_id(topic_id)
    return serialize(await run_in_threadpool(db.list_library_papers, q.strip()[:100], source, category, topic_id))


@app.post('/api/library/upload', status_code=201)
async def upload_library_paper(title: str = Form(...), authors: str = Form(default=''), abstract: str = Form(default=''),
    doi: str = Form(default=''), source_url: str = Form(default=''), category: str = Form(...),
    topic_id: str = Form(default=''), original: UploadFile = File(...), chinese: UploadFile | None = File(default=None)):
    require_db()
    title, authors, abstract, doi, source_url = (value.strip() for value in (title,authors,abstract,doi,source_url))
    if not title or len(title)>500 or len(authors)>500 or len(abstract)>5000 or len(source_url)>2000:
        raise HTTPException(400, '标题、作者、摘要或链接长度不正确')
    if doi and not DOI_RE.fullmatch(doi):
        raise HTTPException(400, 'DOI 格式不正确')
    if source_url and not source_url.startswith('https://'):
        raise HTTPException(400, '来源链接需使用 HTTPS')
    if category not in {'theme','reading'}:
        raise HTTPException(400, '请选择主题文献库或精读文献库')
    if category == 'theme':
        topic_id = valid_id(topic_id)
        if not await run_in_threadpool(db.library_topic_exists, topic_id):
            raise HTTPException(404, '文献主题不存在')
    else:
        topic_id = None
    async def pdf_body(file):
        if not file:
            return None, None
        filename = Path(file.filename or '').name[:255]
        if Path(filename).suffix.lower() != '.pdf':
            raise HTTPException(400, '仅支持 PDF 文件')
        body = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        if len(body)>settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f'单个 PDF 不能超过 {settings.max_upload_mb} MB')
        if not body.startswith(b'%PDF-'):
            raise HTTPException(400, '文件不是有效 PDF')
        try:
            PdfReader(io.BytesIO(body))
        except Exception:
            raise HTTPException(400, 'PDF 文件无法读取')
        return body,filename
    original_body, original_name = await pdf_body(original)
    chinese_body, chinese_name = await pdf_body(chinese)
    paper_id = await run_in_threadpool(db.add_library_upload,title,authors,abstract,doi or None,
        source_url or None,category,topic_id,original_body,original_name,chinese_body,chinese_name)
    return {'id':paper_id,'category':category}


@app.get('/api/library/{paper_id}/files/{kind}')
async def library_pdf(paper_id: str, kind: str):
    require_db()
    if kind not in {'original','chinese'}:
        raise HTTPException(404, '文件不存在')
    paper_id = valid_id(paper_id)
    paper = await run_in_threadpool(db.get_library_paper,paper_id)
    if not paper:
        raise HTTPException(404, '文献不存在')
    file = await run_in_threadpool(db.get_library_file,paper_id,kind)
    if file:
        return Response(file['body'],media_type='application/pdf',headers={'Content-Disposition':f'inline; filename={kind}.pdf','X-Content-Type-Options':'nosniff'})
    if kind == 'chinese' and paper['translation_text']:
        try:
            body = await run_in_threadpool(render_text_pdf,f'{paper["title"]} — 中文翻译',paper['translation_text'])
        except RuntimeError as exc:
            raise HTTPException(503,str(exc))
        return Response(body,media_type='application/pdf',headers={'Content-Disposition':'inline; filename=chinese.pdf','X-Content-Type-Options':'nosniff'})
    raise HTTPException(404, '该文献尚无此 PDF')


@app.delete('/api/library/{paper_id}')
async def delete_library_paper(paper_id: str):
    require_db()
    if not await run_in_threadpool(db.delete_library_paper, valid_id(paper_id)):
        raise HTTPException(404, '文献不存在')
    return {'ok': True}


@app.get("/api/reading-tasks")
async def reading_tasks(q: str = "", status: str = "all"):
    require_db()
    if status not in {"all", "queued", "processing", "completed", "failed"}:
        raise HTTPException(400, "无效的任务状态")
    return serialize(await run_in_threadpool(db.list_reading_tasks, q.strip()[:100], status))


@app.post('/api/reading/from-search', status_code=201)
async def create_reading_from_search(background: BackgroundTasks, payload: ReadSearchRequest):
    require_db()
    try:
        paper = (await run_in_threadpool(resolve_search_papers, [payload.id]))[0]
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if paper.get('is_mock'):
        raise HTTPException(422, '模拟文献没有真实原文，请在文献精读页上传 PDF')
    doi = str(paper.get('doi') or '').strip()
    pdf_url = str(paper.get('pdf_url') or '').strip()
    if doi and DOI_RE.fullmatch(doi):
        input_type, source_value = 'doi', doi
    elif pdf_url and urlparse(pdf_url).scheme == 'https' and urlparse(pdf_url).hostname:
        input_type, source_value = 'url', pdf_url
    else:
        raise HTTPException(422, '这篇文献没有可获取的 DOI 或 PDF 链接，请上传原文 PDF')
    template = await run_in_threadpool(db.get_report_template, True)
    if not template or not template.get('report_template_body') or not template.get('report_template_text'):
        raise HTTPException(409, '请先在“设置 > 文献工具”上传文献阅读报告模板')
    task_id = await run_in_threadpool(
        db.create_reading_task, input_type, source_value, None,
        paper['title'], paper.get('source') or '文献检索', None,
        template['report_template_format'], 'zh',
        template['report_template_text'], template['report_template_body'],
        paper.get('authors') or '',
    )
    background.add_task(process_reading_task, task_id)
    return {'id': task_id, 'status': 'queued'}


@app.post("/api/reading-tasks", status_code=201)
async def create_reading_task(background: BackgroundTasks, reference: str = Form(default=""), file: UploadFile | None = File(default=None)):
    require_db()
    template = await run_in_threadpool(db.get_report_template, True)
    if not template or not template.get('report_template_body') or not template.get('report_template_text'):
        raise HTTPException(409, '请先在“设置 > 文献工具”上传文献阅读报告模板')
    output_format = template['report_template_format']
    template_text = template['report_template_text']
    template_body = template['report_template_body']
    if bool(reference.strip()) == bool(file):
        raise HTTPException(400, "请选择 DOI / 链接或上传一个 PDF")
    if file:
        filename = Path(file.filename or "paper.pdf").name[:255]
        if Path(filename).suffix.casefold() != ".pdf":
            raise HTTPException(400, "仅支持 PDF 文件")
        body = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        if len(body) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"PDF 不能超过 {settings.max_upload_mb} MB")
        if not body.lstrip().startswith(b"%PDF-"):
            raise HTTPException(400, "文件不是有效 PDF")
        task_id = await run_in_threadpool(db.create_reading_task, "upload", None, filename, Path(filename).stem, "本地上传", body, output_format, 'zh', template_text, template_body)
    else:
        try:
            input_type, value, source_label = classify_reference(reference)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        task_id = await run_in_threadpool(db.create_reading_task, input_type, value, None, value[:500], source_label, None, output_format, 'zh', template_text, template_body)
    background.add_task(process_reading_task, task_id)
    return {"id": task_id, "status": "queued"}


@app.get("/api/reading-tasks/{task_id}")
async def reading_task_detail(task_id: str):
    require_db()
    task = await run_in_threadpool(db.get_reading_task, valid_id(task_id))
    if not task:
        raise HTTPException(404, "任务不存在")
    task.pop("extracted_text", None)
    if task['status'] == 'completed':
        task['translation_html'] = render_assistant_markdown(task.get('translation') or '')
        task['report_html'] = render_assistant_markdown(task.get('report') or '')
    return serialize(task)


@app.get("/api/reading-tasks/{task_id}/pdf")
async def reading_task_pdf(task_id: str, download: bool = False):
    require_db()
    row = await run_in_threadpool(db.get_reading_pdf, valid_id(task_id))
    if not row:
        raise HTTPException(404, "原文 PDF 尚不可用")
    filename = original_pdf_name(row['title'])
    disposition = 'attachment' if download else 'inline'
    return Response(row['pdf_body'], media_type='application/pdf', headers={
        'Content-Disposition':f"{disposition}; filename=paper.pdf; filename*=UTF-8''{quote(filename)}",
        'X-Content-Type-Options':'nosniff'})


@app.get('/api/reading-tasks/{task_id}/{kind}.pdf')
async def reading_generated_pdf(task_id: str, kind: str, download: bool = False):
    require_db()
    if kind not in {'translation','report'}:
        raise HTTPException(404, '文件不存在')
    task = await run_in_threadpool(db.get_reading_task, valid_id(task_id), True)
    if not task or not task[kind] or (kind == 'report' and task['status'] != 'completed'):
        raise HTTPException(404, 'PDF 尚不可用')
    title = task['translated_title'] or task['title'] if kind == 'translation' else f'{task["title"]} — 阅读报告'
    try:
        body = (task.get('translation_pdf') if kind == 'translation' else
            (task.get('report_body') if task['output_format'] == 'pdf' else None))
        body = body or await run_in_threadpool(render_text_pdf, title, task[kind])
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    filename = chinese_pdf_name(task['translated_title'] or task['title']) if kind == 'translation' else report_name(task['title'], 'pdf')
    disposition = 'attachment' if download else 'inline'
    return Response(body, media_type='application/pdf', headers={
        'Content-Disposition':f"{disposition}; filename={kind}.pdf; filename*=UTF-8''{quote(filename)}",
        'X-Content-Type-Options':'nosniff'})


@app.get('/api/reading-tasks/{task_id}/{kind}.md')
async def reading_generated_markdown(task_id: str, kind: str):
    require_db()
    if kind not in {'translation', 'report'}:
        raise HTTPException(404, '文件不存在')
    task = await run_in_threadpool(db.get_reading_task, valid_id(task_id), False, True)
    if not task or task['status'] != 'completed' or not task[kind]:
        raise HTTPException(404, 'Markdown 尚不可用')
    filename = report_name(task['title'], 'md') if kind == 'report' else chinese_pdf_name(task['translated_title'] or task['title']).removesuffix('.pdf') + '.md'
    body = task.get('report_body') if kind == 'report' and task['output_format'] == 'markdown' else task[kind]
    return Response(body, media_type='text/markdown; charset=utf-8',
        headers={'Content-Disposition':f"attachment; filename={kind}.md; filename*=UTF-8''{quote(filename)}",'X-Content-Type-Options':'nosniff'})


@app.get('/api/reading-tasks/{task_id}/{kind}.{extension}')
async def reading_generated_office(task_id: str, kind: str, extension: str):
    require_db()
    if kind not in {'translation', 'report'} or extension not in {'docx', 'xlsx'}:
        raise HTTPException(404, '文件不存在')
    task = await run_in_threadpool(db.get_reading_task, valid_id(task_id), False, True)
    if not task or task['status'] != 'completed' or not task[kind] or task['output_format'] != extension:
        raise HTTPException(404, '文件尚不可用')
    title = f'{task["title"]} — {"中文翻译" if kind == "translation" else "阅读报告"}'
    body = task.get('report_body') if kind == 'report' else None
    body = body or await run_in_threadpool(render_office_document, title, task[kind], extension)
    filename = report_name(task['title'], extension) if kind == 'report' else f'{chinese_pdf_name(task["translated_title"] or task["title"]).removesuffix(".pdf")}.{extension}'
    return Response(body, media_type=CONTENT_TYPES[extension],
        headers={'Content-Disposition':f"attachment; filename={kind}.{extension}; filename*=UTF-8''{quote(filename)}",
            'X-Content-Type-Options':'nosniff'})


@app.post("/api/reading-tasks/{task_id}/retry")
async def retry_reading_task(task_id: str, background: BackgroundTasks):
    require_db()
    task_id = valid_id(task_id)
    if not await run_in_threadpool(db.retry_reading_task, task_id):
        raise HTTPException(409, "任务不存在或正在执行")
    background.add_task(process_reading_task, task_id)
    return {"id": task_id, "status": "queued"}


@app.delete("/api/reading-tasks/{task_id}")
async def delete_reading_task(task_id: str):
    require_db()
    if not await run_in_threadpool(db.delete_reading_task, valid_id(task_id)):
        raise HTTPException(404, "任务不存在")
    return {"ok": True}


@app.get("/api/health")
async def health():
    return {"database": "ready" if not app.state.db_error else "unavailable", "model": "ready" if settings.chat_api_key else "unconfigured", "chat_model": settings.chat_model,
        "reading_model": "ready" if settings.chat_api_key else "unconfigured", "database_error": app.state.db_error}


@app.get("/api/conversations")
async def conversations(q: str = ""):
    require_db()
    return serialize(await run_in_threadpool(db.list_conversations, q.strip()[:100]))


@app.post("/api/conversations", status_code=201)
async def create_conversation():
    require_db()
    cid = await run_in_threadpool(db.create_conversation)
    return {"id": cid}


@app.get("/api/conversations/{cid}")
async def get_conversation(cid: str):
    require_db()
    result = await run_in_threadpool(db.get_conversation, valid_id(cid))
    if not result:
        raise HTTPException(404, "会话不存在")
    result = serialize(result)
    for message in result['messages']:
        if message['role'] == 'assistant':
            message['html'] = render_assistant_markdown(message['content'])
    return result


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=180)


@app.patch("/api/conversations/{cid}")
async def rename_conversation(cid: str, payload: RenameRequest):
    require_db()
    if not await run_in_threadpool(db.rename_conversation, valid_id(cid), payload.title.strip()):
        raise HTTPException(404, "会话不存在")
    return {"ok": True}


@app.delete("/api/conversations/{cid}")
async def delete_conversation(cid: str):
    require_db()
    if not await run_in_threadpool(db.delete_conversation, valid_id(cid)):
        raise HTTPException(404, "会话不存在")
    return {"ok": True}


def extract_text(body: bytes, suffix: str):
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(body))
        return "\n".join(page.extract_text() or "" for page in reader.pages)[:100000]
    if suffix == ".docx":
        doc = Document(io.BytesIO(body))
        return "\n".join(p.text for p in doc.paragraphs)[:100000]
    if suffix == ".txt":
        return body.decode("utf-8-sig", errors="replace")[:100000]
    return None


@app.post("/api/conversations/{cid}/attachments", status_code=201)
async def upload_attachment(cid: str, file: UploadFile = File(...)):
    require_db()
    cid = valid_id(cid)
    if not await run_in_threadpool(db.get_conversation, cid):
        raise HTTPException(404, "会话不存在")
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    mime = file.content_type or ""
    if mime not in ALLOWED_MIME or suffix != ALLOWED_MIME[mime] and not (mime == "image/jpeg" and suffix == ".jpeg"):
        raise HTTPException(400, "支持 PDF、DOCX、TXT、PNG、JPG 和 WEBP 文件")
    body = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(body) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"文件不能超过 {settings.max_upload_mb} MB")
    if not body:
        raise HTTPException(400, "文件为空")
    try:
        text = await run_in_threadpool(extract_text, body, suffix)
    except Exception:
        raise HTTPException(400, "文件无法读取或格式不正确")
    aid = await run_in_threadpool(db.save_attachment, cid, filename, mime, body, text)
    return {"id": aid, "filename": filename, "mime_type": mime}


@app.get("/api/attachments/{aid}")
async def download_attachment(aid: str):
    require_db()
    row = await run_in_threadpool(db.get_attachment, valid_id(aid))
    if not row or not row["message_id"]:
        raise HTTPException(404, "附件不存在")
    return Response(row["body"], media_type=row["mime_type"], headers={"Content-Disposition": "attachment"})


class MessageRequest(BaseModel):
    content: str = Field(default="", max_length=12000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=8)
    thinking_mode: str = "normal"


@app.post("/api/conversations/{cid}/messages", status_code=201)
async def send_message(cid: str, payload: MessageRequest):
    require_db()
    cid = valid_id(cid)
    conversation = await run_in_threadpool(db.get_conversation, cid)
    if not conversation:
        raise HTTPException(404, "会话不存在")
    content = payload.content.strip()
    if not content and not payload.attachment_ids:
        raise HTTPException(400, "请输入问题或添加附件")
    if payload.thinking_mode != "normal":
        raise HTTPException(400, "AI 对话当前只支持非思考模式")
    ids = [valid_id(aid) for aid in payload.attachment_ids]
    if len(ids) != len(set(ids)):
        raise HTTPException(400, "附件不能重复")
    if not settings.chat_api_key:
        raise HTTPException(503, "DeepSeek 尚未配置，请填写 .env 中的 DEEPSEEK_API_KEY")
    try:
        mid = await run_in_threadpool(db.add_user_message_with_attachments, cid, content, payload.thinking_mode, ids)
        conversation = await run_in_threadpool(db.get_conversation, cid)
        attachments = await run_in_threadpool(db.get_conversation_attachments, cid)
        reply = await run_in_threadpool(answer, conversation, attachments)
        reply_id = await run_in_threadpool(db.add_message, cid, "assistant", reply)
        return {"user_message_id": mid, "assistant_message": {"id": reply_id, "role": "assistant",
            "content": reply, "html": render_assistant_markdown(reply)}}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except pymysql.MySQLError:
        log.exception("数据库操作失败")
        raise HTTPException(503, "数据库操作失败，请稍后重试")
    except Exception:
        log.exception("模型调用失败")
        raise HTTPException(502, "AI 回复失败；你的提问已保存，请稍后重试")
