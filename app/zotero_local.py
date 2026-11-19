"""Zotero 10 local API integration. All requests stay on loopback."""

import hashlib
import re
import time
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from . import db
from .file_names import original_pdf_name, chinese_pdf_name, report_name

BASE = 'http://127.0.0.1:23119/api'


class ZoteroError(ValueError):
    pass


class ZoteroClient:
    def __init__(self):
        self.http = httpx.Client(base_url=BASE, timeout=15, trust_env=False)
        self.server_id = None
        self.key = None

    def close(self):
        self.http.close()

    def _response(self, response, action):
        if response.status_code in {401, 403}:
            raise ZoteroError(f'Zotero 拒绝{action}；请在设置中重新连接并选择“始终允许”')
        if response.status_code == 412:
            raise ZoteroError('Zotero 数据库已切换；请在设置中重新连接')
        if response.status_code >= 400:
            raise ZoteroError(f'Zotero {action}失败（HTTP {response.status_code}）')
        return response

    def probe(self):
        try:
            response = self.http.get('/')
        except httpx.HTTPError as exc:
            raise ZoteroError('Zotero 桌面端未运行或本地 API 不可用') from exc
        self._response(response, '连接')
        self.server_id = response.headers.get('Zotero-Server-ID')
        if not self.server_id:
            raise ZoteroError('当前 Zotero 版本不支持所需的本地写入 API')
        return self.server_id

    def authorize(self):
        self.probe()
        try:
            response = self.http.post('/local/authorize',
                json={'appName':'个人论文助手'},
                headers={'Zotero-Server-ID':self.server_id}, timeout=120)
        except httpx.HTTPError as exc:
            raise ZoteroError('Zotero 授权未完成，请重试') from exc
        self._response(response, '授权')
        result = response.json()
        if not result.get('remember'):
            raise ZoteroError('请再次连接，并在 Zotero 授权窗口选择“始终允许”，以支持批量导入和 PDF 附件')
        key = result.get('key')
        if not key or len(key) != 32:
            raise ZoteroError('Zotero 未返回有效的本地写入授权')
        self.key = key
        return self.server_id, key

    def use_saved_connection(self):
        saved = db.get_app_settings(include_secret=True)
        server_id = self.probe()
        if not saved['zotero_connected'] or not saved.get('zotero_api_key'):
            raise ZoteroError('请先在设置中连接 Zotero')
        if saved['zotero_server_id'] != server_id:
            raise ZoteroError('Zotero 数据库已切换；请在设置中重新连接')
        self.key = saved['zotero_api_key']
        return saved

    def get(self, path):
        try:
            return self._response(self.http.get(path), '读取').json()
        except httpx.HTTPError as exc:
            raise ZoteroError('无法读取 Zotero 本地文献库') from exc

    def write(self, path, payload, action, token=True):
        headers = {'Zotero-Server-ID':self.server_id,'Zotero-API-Key':self.key}
        if token:
            headers['Zotero-Write-Token'] = uuid4().hex
        try:
            response = self.http.post(path,json=payload,headers=headers,timeout=30)
        except httpx.HTTPError as exc:
            raise ZoteroError(f'Zotero {action}请求失败') from exc
        return self._response(response, action).json()

    @staticmethod
    def created_key(result, action):
        if result.get('failed'):
            raise ZoteroError(f'Zotero {action}失败：{result["failed"]}')
        key = result.get('success', {}).get('0')
        if not key:
            raise ZoteroError(f'Zotero 未返回{action}结果')
        return key

    def ensure_collection(self, name):
        collections = self.get('/users/0/collections')
        found = next((row['key'] for row in collections
            if row['data'].get('name') == name and not row['data'].get('parentCollection')), None)
        if found:
            return found
        result = self.write('/users/0/collections',
            [{'name':name,'parentCollection':False}], '创建文献目录')
        return self.created_key(result, '创建文献目录')

    def existing_item(self, kind, source_id):
        key = db.get_zotero_export(self.server_id,kind,source_id)
        if not key:
            return None
        try:
            response = self.http.get(f'/users/0/items/{key}')
        except httpx.HTTPError as exc:
            raise ZoteroError('无法核对 Zotero 中的既有条目') from exc
        if response.status_code == 404:
            return None
        self._response(response, '核对条目')
        return key

    def create_item(self, kind, source_id, data):
        existing = self.existing_item(kind, source_id)
        if existing:
            return existing, False
        key = self.created_key(self.write('/users/0/items',[data], '保存文献'), '保存文献')
        db.save_zotero_export(self.server_id,kind,source_id,key)
        return key, True

    def child_attachments(self, parent_key):
        return self.get(f'/users/0/items/{parent_key}/children')

    def attach_pdf(self, parent_key, title, filename, body):
        children = self.child_attachments(parent_key)
        existing = next((row for row in children if row['data'].get('title') == title
            and row['data'].get('itemType') == 'attachment'), None)
        if existing and existing['data'].get('md5'):
            return existing['key'], False
        if existing:
            item_key = existing['key']
        else:
            payload = {'itemType':'attachment','parentItem':parent_key,
                'linkMode':'imported_file','title':title,'contentType':'application/pdf',
                'filename':filename,'tags':[]}
            item_key = self.created_key(self.write('/users/0/items',[payload], '创建 PDF 附件'), '创建 PDF 附件')
        self.upload_pdf(item_key,filename,body)
        return item_key, True

    def upload_pdf(self, item_key, filename, body):
        if not body.startswith(b'%PDF-'):
            raise ZoteroError('附件内容不是 PDF')
        path = f'/users/0/items/{item_key}/file'
        headers = {'Zotero-Server-ID':self.server_id,'Zotero-API-Key':self.key,'If-None-Match':'*'}
        data = {'md5':hashlib.md5(body).hexdigest(),'filename':filename,
            'filesize':str(len(body)),'mtime':str(int(time.time()*1000))}
        try:
            authorization = self.http.post(path,data=data,headers=headers,timeout=30)
            self._response(authorization, '准备 PDF 上传')
            details = authorization.json()
            if details.get('exists'):
                return
            upload_url = details.get('url','')
            target = urlparse(upload_url)
            if target.scheme != 'http' or target.hostname not in {'127.0.0.1','localhost'} or target.port != 23119 or not target.path.startswith('/api/local/uploads/'):
                raise ZoteroError('Zotero 返回了无效的本地上传地址')
            content = details.get('prefix','').encode() + body + details.get('suffix','').encode()
            uploaded = self.http.post(upload_url,content=content,
                headers={'Content-Type':details.get('contentType','application/pdf')},timeout=60)
            self._response(uploaded, '上传 PDF')
            registered = self.http.post(path,data={'upload':details['uploadKey']},headers=headers,timeout=30)
            self._response(registered, '登记 PDF 附件')
        except httpx.HTTPError as exc:
            raise ZoteroError('Zotero PDF 上传中断，请重试') from exc


def creators_from_authors(authors):
    names = [part.strip() for part in re.split(r'[;；、，,]+', authors or '') if part.strip()]
    return [{'creatorType':'author','name':name} for name in names[:12]]


def export_search_papers(papers):
    client = ZoteroClient()
    try:
        settings = client.use_saved_connection()
        collection = client.ensure_collection(settings['search_collection'])
        imported = skipped = 0
        for paper in papers:
            mock = paper.get('is_mock',False)
            item_type = 'journalArticle' if paper['document_type'] in {'期刊论文', 'article'} else 'document'
            data = {'itemType':item_type,
                'title':('[模拟文献] ' if mock else '') + paper['title'],
                'creators':creators_from_authors(paper['authors']),
                'date':str(paper['year']) if paper['year'] else '',
                'abstractNote':paper['abstract'],
                'collections':[collection],
                'tags':[{'tag':'个人论文助手'}] + ([{'tag':'模拟数据-不可引用'}] if mock else []),
                'extra':('本地模拟记录，非真实出版文献；不可用于正式引用。\n' if mock else f'来自 {paper["source"]} 检索，元数据需核对原文。\n') + f'个人论文助手记录 ID: {paper["id"]}'}
            if paper.get('url'):
                data['url'] = paper['url']
            if paper.get('doi'):
                data['DOI'] = paper['doi']
            if item_type == 'journalArticle':
                data['publicationTitle'] = paper['venue']
            elif paper['venue']:
                data['extra'] += f'\n检索来源刊物: {paper["venue"]}'
            _, created = client.create_item('search',paper['id'],data)
            imported += int(created)
            skipped += int(not created)
        return {'imported':imported,'already_exists':skipped,'collection':settings['search_collection']}
    finally:
        client.close()


def export_reading_task(task, translation_pdf, report_pdf):
    client = ZoteroClient()
    try:
        settings = client.use_saved_connection()
        collection = client.ensure_collection(settings['reading_collection'])
        data = {'itemType':'journalArticle','title':task['title'],
            'creators':creators_from_authors(task.get('authors')),
            'collections':[collection], 'tags':[{'tag':'个人论文助手精读'}],
            'extra':f'个人论文助手精读任务 ID: {task["id"]}\n来源: {task["source_label"]}'}
        if task['input_type'] == 'doi':
            data['DOI'] = task['source_value']
        elif task['input_type'] == 'url':
            data['url'] = task['source_value']
        parent, created = client.create_item('reading',task['id'],data)
        attachments = [
            ('原文 PDF',original_pdf_name(task['title']),task['pdf_body']),
        ]
        if translation_pdf:
            attachments.append(('中文翻译 PDF',chinese_pdf_name(task.get('translated_title') or task['title']),translation_pdf))
        attachments.append(('阅读报告 PDF',report_name(task['title'],'pdf'),report_pdf))
        uploaded = 0
        for title, filename, body in attachments:
            _, added = client.attach_pdf(parent,title,filename,body)
            uploaded += int(added)
        return {'item_key':parent,'created':created,'uploaded':uploaded,
            'collection':settings['reading_collection']}
    finally:
        client.close()
