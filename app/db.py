from contextlib import contextmanager
from datetime import datetime
import json
import re
from uuid import uuid4

import pymysql
from pymysql.cursors import DictCursor

from .config import settings
from .file_names import original_pdf_name, chinese_pdf_name


def _connect(database=True):
    kwargs = dict(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=3,
    )
    if database:
        kwargs["database"] = settings.mysql_database
    return pymysql.connect(**kwargs)


@contextmanager
def connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    # The database name cannot be bound as a SQL value. Reject unsafe names first.
    name = settings.mysql_database
    if not name or not all(ch.isalnum() or ch == "_" for ch in name):
        raise ValueError("MYSQL_DATABASE 只能包含字母、数字和下划线")
    conn = _connect(database=False)
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.commit()
    finally:
        conn.close()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS conversations (
                id CHAR(36) PRIMARY KEY,
                title VARCHAR(180) NOT NULL DEFAULT '新对话',
                created_at DATETIME(6) NOT NULL,
                updated_at DATETIME(6) NOT NULL,
                INDEX idx_updated (updated_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS messages (
                id CHAR(36) PRIMARY KEY,
                conversation_id CHAR(36) NOT NULL,
                role ENUM('user','assistant') NOT NULL,
                content LONGTEXT NOT NULL,
                thinking_mode VARCHAR(20) NOT NULL DEFAULT 'normal',
                created_at DATETIME(6) NOT NULL,
                INDEX idx_conversation_time (conversation_id, created_at),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS attachments (
                id CHAR(36) PRIMARY KEY,
                message_id CHAR(36) NULL,
                conversation_id CHAR(36) NOT NULL,
                filename VARCHAR(255) NOT NULL,
                mime_type VARCHAR(120) NOT NULL,
                body LONGBLOB NOT NULL,
                extracted_text LONGTEXT NULL,
                created_at DATETIME(6) NOT NULL,
                INDEX idx_conversation_attachment (conversation_id),
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS reading_tasks (
                id CHAR(36) PRIMARY KEY,
                input_type ENUM('doi','url','upload') NOT NULL,
                source_value TEXT NULL,
                filename VARCHAR(255) NULL,
                title VARCHAR(500) NOT NULL,
                authors VARCHAR(500) NULL,
                source_label VARCHAR(80) NOT NULL,
                status ENUM('queued','processing','completed','failed') NOT NULL DEFAULT 'queued',
                error_message TEXT NULL,
                pdf_body LONGBLOB NULL,
                extracted_text LONGTEXT NULL,
                translation LONGTEXT NULL,
                report LONGTEXT NULL,
                output_format VARCHAR(12) NOT NULL DEFAULT 'markdown',
                report_language VARCHAR(2) NOT NULL DEFAULT 'zh',
                report_template_text LONGTEXT NULL,
                report_template_body MEDIUMBLOB NULL,
                document_language VARCHAR(2) NULL,
                translated_title VARCHAR(500) NULL,
                translation_pdf LONGBLOB NULL,
                report_body LONGBLOB NULL,
                stage VARCHAR(32) NOT NULL DEFAULT 'queued',
                total_segments INT NOT NULL DEFAULT 0,
                completed_segments INT NOT NULL DEFAULT 0,
                created_at DATETIME(6) NOT NULL,
                updated_at DATETIME(6) NOT NULL,
                INDEX idx_reading_updated (updated_at),
                INDEX idx_reading_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("SHOW COLUMNS FROM reading_tasks")
            reading_columns = {row['Field'] for row in cur.fetchall()}
            for column, definition in {
                'output_format': "VARCHAR(12) NOT NULL DEFAULT 'markdown'",
                'report_language': "VARCHAR(2) NOT NULL DEFAULT 'zh'",
                'report_template_text': 'LONGTEXT NULL',
                'report_template_body': 'MEDIUMBLOB NULL',
                'document_language': 'VARCHAR(2) NULL',
                'translated_title': 'VARCHAR(500) NULL',
                'translation_pdf': 'LONGBLOB NULL',
                'report_body': 'LONGBLOB NULL',
                'stage': "VARCHAR(32) NOT NULL DEFAULT 'queued'",
                'total_segments': 'INT NOT NULL DEFAULT 0',
                'completed_segments': 'INT NOT NULL DEFAULT 0',
            }.items():
                if column not in reading_columns:
                    cur.execute(f'ALTER TABLE reading_tasks ADD COLUMN {column} {definition}')
            cur.execute("""CREATE TABLE IF NOT EXISTS reading_segments (
                task_id CHAR(36) NOT NULL,
                segment_index INT NOT NULL,
                source_text LONGTEXT NOT NULL,
                translated_text LONGTEXT NULL,
                PRIMARY KEY (task_id, segment_index),
                FOREIGN KEY (task_id) REFERENCES reading_tasks(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS library_papers (
                id CHAR(36) PRIMARY KEY,
                source_record_id VARCHAR(64) NOT NULL UNIQUE,
                source_name VARCHAR(80) NOT NULL,
                is_mock BOOLEAN NOT NULL DEFAULT TRUE,
                title VARCHAR(500) NOT NULL,
                authors VARCHAR(500) NOT NULL,
                venue VARCHAR(300) NOT NULL,
                publication_year SMALLINT NOT NULL,
                document_type VARCHAR(80) NOT NULL,
                abstract_text TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                added_at DATETIME(6) NOT NULL,
                INDEX idx_library_added (added_at),
                INDEX idx_library_source (source_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS library_topics (
                id CHAR(36) PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                created_at DATETIME(6) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS library_files (
                paper_id CHAR(36) NOT NULL,
                file_kind ENUM('original','chinese') NOT NULL,
                filename VARCHAR(255) NOT NULL,
                mime_type VARCHAR(80) NOT NULL DEFAULT 'application/pdf',
                body LONGBLOB NOT NULL,
                PRIMARY KEY (paper_id,file_kind),
                FOREIGN KEY (paper_id) REFERENCES library_papers(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("SHOW COLUMNS FROM library_papers")
            existing_columns = {row['Field'] for row in cur.fetchall()}
            additions = {
                'category': "VARCHAR(16) NOT NULL DEFAULT 'theme'",
                'topic_id': 'CHAR(36) NULL',
                'reading_task_id': 'CHAR(36) NULL UNIQUE',
                'doi': 'VARCHAR(255) NULL',
                'source_url': 'VARCHAR(2000) NULL',
                'translation_text': 'LONGTEXT NULL',
                'report_text': 'LONGTEXT NULL',
            }
            for column, definition in additions.items():
                if column not in existing_columns:
                    cur.execute(f'ALTER TABLE library_papers ADD COLUMN {column} {definition}')
            cur.execute("INSERT IGNORE INTO library_topics (id,name,created_at) VALUES (%s,'未分类',%s)",
                (str(uuid4()),datetime.now()))
            cur.execute("SELECT id FROM library_topics WHERE name='未分类'")
            unfiled_id = cur.fetchone()['id']
            cur.execute("UPDATE library_papers SET topic_id=%s WHERE category='theme' AND topic_id IS NULL",(unfiled_id,))
            cur.execute("""CREATE TABLE IF NOT EXISTS search_tasks (
                id CHAR(36) PRIMARY KEY,
                query_text VARCHAR(200) NOT NULL,
                sources_json VARCHAR(100) NOT NULL,
                year_from SMALLINT NOT NULL,
                year_to SMALLINT NOT NULL,
                requested_count SMALLINT NOT NULL,
                sort_order VARCHAR(20) NOT NULL,
                returned_count SMALLINT NOT NULL,
                created_at DATETIME(6) NOT NULL,
                INDEX idx_search_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("SHOW COLUMNS FROM search_tasks LIKE 'result_json'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE search_tasks ADD COLUMN result_json LONGTEXT NULL")
            cur.execute("""CREATE TABLE IF NOT EXISTS search_result_cache (
                id VARCHAR(64) PRIMARY KEY,
                data_json LONGTEXT NOT NULL,
                updated_at DATETIME(6) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS app_settings (
                id TINYINT PRIMARY KEY,
                data_json LONGTEXT NOT NULL,
                avatar_body MEDIUMBLOB NULL,
                avatar_mime VARCHAR(50) NULL,
                zotero_server_id VARCHAR(64) NULL,
                zotero_api_key VARCHAR(128) NULL,
                zotero_remember BOOLEAN NOT NULL DEFAULT FALSE,
                report_template_body MEDIUMBLOB NULL,
                report_template_filename VARCHAR(255) NULL,
                report_template_format VARCHAR(12) NULL,
                report_template_text LONGTEXT NULL,
                updated_at DATETIME(6) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute('SHOW COLUMNS FROM app_settings')
            settings_columns = {row['Field'] for row in cur.fetchall()}
            for column, definition in {
                'report_template_body': 'MEDIUMBLOB NULL',
                'report_template_filename': 'VARCHAR(255) NULL',
                'report_template_format': 'VARCHAR(12) NULL',
                'report_template_text': 'LONGTEXT NULL',
            }.items():
                if column not in settings_columns:
                    cur.execute(f'ALTER TABLE app_settings ADD COLUMN {column} {definition}')
            cur.execute("""CREATE TABLE IF NOT EXISTS zotero_exports (
                server_id VARCHAR(64) NOT NULL,
                source_kind ENUM('search','reading') NOT NULL,
                source_id VARCHAR(64) NOT NULL,
                item_key VARCHAR(16) NOT NULL,
                created_at DATETIME(6) NOT NULL,
                PRIMARY KEY (server_id,source_kind,source_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("INSERT IGNORE INTO app_settings (id,data_json,updated_at) VALUES (1,%s,%s)",
                (json.dumps(DEFAULT_APP_SETTINGS,ensure_ascii=False),datetime.now()))


DEFAULT_APP_SETTINGS = {
    'user_name': 'Chelsea',
    'email': 'chelsea@example.com',
    'literature_language': 'zh',
    'search_count': 20,
    'report_language': 'zh',
    'search_collection': '文献目录',
    'reading_collection': '每周精读文献',
}


def get_app_settings(include_secret=False):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT data_json,avatar_mime,zotero_server_id,zotero_api_key,zotero_remember,
                report_template_filename,report_template_format FROM app_settings WHERE id=1""")
            row = cur.fetchone()
    values = {**DEFAULT_APP_SETTINGS, **(json.loads(row['data_json']) if row else {})}
    for retired in ('report_format', 'literature_dir', 'report_dir'):
        values.pop(retired, None)
    values['report_template_filename'] = row['report_template_filename'] if row else None
    values['report_template_format'] = row['report_template_format'] if row else None
    values['has_avatar'] = bool(row and row['avatar_mime'])
    values['zotero_server_id'] = row['zotero_server_id'] if row else None
    values['zotero_connected'] = bool(row and row['zotero_api_key'] and row['zotero_remember'])
    if include_secret:
        values['zotero_api_key'] = row['zotero_api_key'] if row else None
    return values


def update_app_settings(values):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE app_settings SET data_json=%s,updated_at=%s WHERE id=1",
                (json.dumps(values,ensure_ascii=False),datetime.now()))


def get_report_template(include_body=False):
    columns = 'report_template_filename,report_template_format,report_template_text'
    if include_body:
        columns += ',report_template_body'
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT {columns} FROM app_settings WHERE id=1')
            return cur.fetchone()


def save_report_template(filename, format_name, text, body):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE app_settings SET report_template_filename=%s,report_template_format=%s,
                report_template_text=%s,report_template_body=%s,updated_at=%s WHERE id=1""",
                (filename,format_name,text,body,datetime.now()))


def delete_report_template():
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE app_settings SET report_template_filename=NULL,report_template_format=NULL,
                report_template_text=NULL,report_template_body=NULL,updated_at=%s WHERE id=1""", (datetime.now(),))


def save_avatar(body,mime):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE app_settings SET avatar_body=%s,avatar_mime=%s,updated_at=%s WHERE id=1",
                (body,mime,datetime.now()))


def get_avatar():
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT avatar_body,avatar_mime FROM app_settings WHERE id=1")
            return cur.fetchone()


def save_zotero_connection(server_id,key,remember):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE app_settings SET zotero_server_id=%s,zotero_api_key=%s,
                zotero_remember=%s,updated_at=%s WHERE id=1""",
                (server_id,key,remember,datetime.now()))


def clear_zotero_connection():
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE app_settings SET zotero_server_id=NULL,zotero_api_key=NULL,
                zotero_remember=FALSE,updated_at=%s WHERE id=1""",(datetime.now(),))


def get_zotero_export(server_id,kind,source_id):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT item_key FROM zotero_exports WHERE server_id=%s AND source_kind=%s AND source_id=%s",
                (server_id,kind,source_id))
            row = cur.fetchone()
            return row['item_key'] if row else None


def save_zotero_export(server_id,kind,source_id,item_key):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO zotero_exports (server_id,source_kind,source_id,item_key,created_at)
                VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE item_key=VALUES(item_key)""",
                (server_id,kind,source_id,item_key,datetime.now()))


def create_search_task(query, sources, year_from, year_to, count, sort, returned, result=None):
    task_id = str(uuid4())
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO search_tasks
                (id,query_text,sources_json,year_from,year_to,requested_count,sort_order,returned_count,result_json,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (task_id,query,json.dumps(sources,ensure_ascii=False),year_from,year_to,count,sort,returned,
                 json.dumps(result,ensure_ascii=False) if result is not None else None,datetime.now()))
    return task_id


def get_search_task(task_id):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id,query_text,sources_json,year_from,year_to,requested_count,sort_order,returned_count,result_json,created_at
                FROM search_tasks WHERE id=%s""",(task_id,))
            row = cur.fetchone()
    if row:
        row['sources'] = json.loads(row.pop('sources_json'))
        result_json = row.pop('result_json')
        row['result'] = json.loads(result_json) if result_json else None
    return row


def get_latest_search_task_id():
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM search_tasks ORDER BY created_at DESC, id DESC LIMIT 1')
            row = cur.fetchone()
    return row['id'] if row else None


def save_search_result(task_id,result):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE search_tasks SET result_json=%s,returned_count=%s WHERE id=%s",
                (json.dumps(result,ensure_ascii=False),result['returned'],task_id))
            return cur.rowcount == 1


def list_home_recent(limit=3):
    per_kind = min(max(limit, 1), 100)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id,query_text AS title,created_at AS happened_at FROM search_tasks ORDER BY created_at DESC LIMIT {per_kind}")
            searches = [{**row,'kind':'search','status':'completed'} for row in cur.fetchall()]
            cur.execute(f"""SELECT id,title,created_at AS happened_at,status FROM reading_tasks
                ORDER BY created_at DESC LIMIT {per_kind}""")
            readings = [{**row,'kind':'reading'} for row in cur.fetchall()]
            cur.execute(f"""SELECT id,title,updated_at AS happened_at FROM conversations
                WHERE title <> '新对话' ORDER BY updated_at DESC LIMIT {per_kind}""")
            conversations = [{**row,'kind':'chat','status':'completed'} for row in cur.fetchall()]
    return sorted(searches + readings + conversations,key=lambda row:row['happened_at'],reverse=True)[:limit]


def list_library_topics():
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT t.id,t.name,COUNT(p.id) AS paper_count FROM library_topics t
                LEFT JOIN library_papers p ON p.topic_id=t.id AND p.category='theme'
                GROUP BY t.id,t.name ORDER BY (t.name='未分类') DESC,t.created_at""")
            return cur.fetchall()


def create_library_topic(name):
    topic_id = str(uuid4())
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO library_topics (id,name,created_at) VALUES (%s,%s,%s)',
                (topic_id,name,datetime.now()))
    return {'id':topic_id,'name':name,'paper_count':0}


def library_topic_exists(topic_id):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM library_topics WHERE id=%s',(topic_id,))
            return bool(cur.fetchone())


def cache_search_papers(papers):
    with connection() as conn:
        with conn.cursor() as cur:
            for paper in papers:
                cur.execute("""INSERT INTO search_result_cache (id,data_json,updated_at) VALUES (%s,%s,%s)
                    ON DUPLICATE KEY UPDATE data_json=VALUES(data_json),updated_at=VALUES(updated_at)""",
                    (paper['id'],json.dumps(paper,ensure_ascii=False),datetime.now()))


def cached_search_papers(ids):
    if not ids:
        return []
    placeholders = ','.join(['%s']*len(ids))
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT id,data_json FROM search_result_cache WHERE id IN ({placeholders})',ids)
            found = {row['id']:json.loads(row['data_json']) for row in cur.fetchall()}
    return [found[item_id] for item_id in ids if item_id in found]


def import_search_papers(papers, topic_id):
    imported = 0
    now = datetime.now()
    with connection() as conn:
        with conn.cursor() as cur:
            for paper in papers:
                cur.execute("""INSERT IGNORE INTO library_papers
                    (id,source_record_id,source_name,is_mock,title,authors,venue,publication_year,
                     document_type,abstract_text,analysis_json,added_at,category,topic_id,doi,source_url)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'theme',%s,%s,%s)""",
                    (str(uuid4()),paper['id'],paper['source'],paper.get('is_mock',False),paper['title'],paper['authors'],
                     paper['venue'],paper['year'],paper['document_type'],paper['abstract'],
                     json.dumps(paper['analysis'],ensure_ascii=False),now,topic_id,paper.get('doi'),paper.get('url')))
                imported += cur.rowcount
                if cur.rowcount == 0:
                    cur.execute("UPDATE library_papers SET topic_id=%s WHERE source_record_id=%s AND category='theme'",
                        (topic_id,paper['id']))
    return imported


def list_library_papers(query='', source='all', category='all', topic_id=None):
    sql = """SELECT p.id,p.source_record_id,p.source_name,p.is_mock,p.title,p.authors,p.venue,
             p.publication_year,p.document_type,p.abstract_text,p.analysis_json,p.added_at,
             p.category,p.topic_id,p.reading_task_id,p.doi,p.source_url,p.translation_text,p.report_text,
             t.name AS topic_name,
             EXISTS(SELECT 1 FROM library_files f WHERE f.paper_id=p.id AND f.file_kind='original') AS has_original_pdf,
             (p.translation_text IS NOT NULL OR EXISTS(SELECT 1 FROM library_files f WHERE f.paper_id=p.id AND f.file_kind='chinese')) AS has_chinese_pdf
             FROM library_papers p LEFT JOIN library_topics t ON t.id=p.topic_id WHERE 1=1"""
    params = []
    if query:
        sql += " AND (p.title LIKE %s OR p.authors LIKE %s OR p.abstract_text LIKE %s)"
        params.extend([f'%{query}%'] * 3)
    if source != 'all':
        sql += ' AND p.source_name=%s'
        params.append(source)
    if category != 'all':
        sql += ' AND p.category=%s'
        params.append(category)
    if topic_id:
        sql += ' AND p.topic_id=%s'
        params.append(topic_id)
    sql += ' ORDER BY p.added_at DESC,p.title'
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql,params)
            rows = cur.fetchall()
    for row in rows:
        row['analysis'] = json.loads(row.pop('analysis_json'))
    return rows


def get_library_paper(paper_id):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id,title,category,translation_text FROM library_papers WHERE id=%s',(paper_id,))
            return cur.fetchone()


def get_library_file(paper_id,kind):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT filename,mime_type,body FROM library_files WHERE paper_id=%s AND file_kind=%s',
                (paper_id,kind))
            return cur.fetchone()


def add_library_upload(title,authors,abstract,doi,source_url,category,topic_id,original,original_name,chinese=None,chinese_name=None):
    paper_id = str(uuid4())
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO library_papers (id,source_record_id,source_name,is_mock,title,authors,venue,
                publication_year,document_type,abstract_text,analysis_json,added_at,category,topic_id,doi,source_url)
                VALUES (%s,%s,'本地上传',FALSE,%s,%s,'',0,'PDF 文献',%s,'{}',%s,%s,%s,%s,%s)""",
                (paper_id,'UPLOAD-'+paper_id,title,authors,abstract,datetime.now(),category,topic_id,doi,source_url))
            cur.execute("INSERT INTO library_files (paper_id,file_kind,filename,body) VALUES (%s,'original',%s,%s)",
                (paper_id,original_name,original))
            if chinese:
                cur.execute("INSERT INTO library_files (paper_id,file_kind,filename,body) VALUES (%s,'chinese',%s,%s)",
                    (paper_id,chinese_name,chinese))
    return paper_id


def record_reading_document(task_id,title,authors,source_label,pdf_body,extracted_text):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE reading_tasks SET title=%s,authors=%s,source_label=%s,pdf_body=%s,
                extracted_text=%s,updated_at=%s WHERE id=%s AND status='processing'""",
                (title[:500],(authors or '')[:500],source_label[:80],pdf_body,extracted_text,datetime.now(),task_id))
    return archive_completed_reading(task_id)


def reading_abstract(text):
    value = text or ''
    match = re.search(r'(?im)^\s*(?:abstract|摘要)\s*[:：]?\s*$',value)
    if match:
        remainder = value[match.end():]
        end = re.search(r'(?im)^\s*(?:keywords?|关键词|1\.?\s*introduction|引言|绪论)\s*[:：]?',remainder)
        abstract = remainder[:end.start() if end else 1800].strip()
        if abstract:
            return abstract[:5000]
    return '原文摘录（未识别到独立摘要）：' + value[:1200].strip() if value else ''


def archive_completed_reading(task_id):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id,input_type,source_value,filename,title,authors,source_label,pdf_body,
                extracted_text,translation,translation_pdf,translated_title,report,status FROM reading_tasks WHERE id=%s""",(task_id,))
            task = cur.fetchone()
            if not task or task['status'] not in {'processing','completed','failed'} or not task['pdf_body']:
                return None
            abstract = reading_abstract(task['extracted_text'])
            cur.execute('SELECT id FROM library_papers WHERE reading_task_id=%s',(task_id,))
            existing = cur.fetchone()
            if existing:
                cur.execute("""UPDATE library_papers SET title=%s,authors=%s,source_name=%s,
                    abstract_text=%s,translation_text=%s,report_text=%s WHERE id=%s""",
                    (task['title'],task['authors'] or '',task['source_label'],
                     abstract,task['translation'],task['report'],existing['id']))
                cur.execute("""UPDATE library_files SET filename=%s,body=%s WHERE paper_id=%s AND file_kind='original'""",
                    (original_pdf_name(task['title']),task['pdf_body'],existing['id']))
                if task['translation_pdf']:
                    cur.execute("""INSERT INTO library_files (paper_id,file_kind,filename,body)
                        VALUES (%s,'chinese',%s,%s) ON DUPLICATE KEY UPDATE filename=VALUES(filename),body=VALUES(body)""",
                        (existing['id'],chinese_pdf_name(task['translated_title'] or task['title']),task['translation_pdf']))
                else:
                    cur.execute("DELETE FROM library_files WHERE paper_id=%s AND file_kind='chinese'", (existing['id'],))
                return existing['id']
            paper_id = str(uuid4())
            doi = task['source_value'] if task['input_type']=='doi' else None
            source_url = task['source_value'] if task['input_type']=='url' else (f'https://doi.org/{doi}' if doi else None)
            cur.execute("""INSERT INTO library_papers (id,source_record_id,source_name,is_mock,title,authors,venue,
                publication_year,document_type,abstract_text,analysis_json,added_at,category,reading_task_id,
                doi,source_url,translation_text,report_text)
                VALUES (%s,%s,%s,FALSE,%s,%s,'',0,'精读论文',%s,'{}',%s,'reading',%s,%s,%s,%s,%s)""",
                (paper_id,'READING-'+task_id,task['source_label'],task['title'],task['authors'] or '',
                 abstract,datetime.now(),task_id,doi,source_url,task['translation'],task['report']))
            cur.execute("INSERT INTO library_files (paper_id,file_kind,filename,body) VALUES (%s,'original',%s,%s)",
                (paper_id,original_pdf_name(task['title']),task['pdf_body']))
            if task['translation_pdf']:
                cur.execute("INSERT INTO library_files (paper_id,file_kind,filename,body) VALUES (%s,'chinese',%s,%s)",
                    (paper_id,chinese_pdf_name(task['translated_title'] or task['title']),task['translation_pdf']))
            return paper_id


def backfill_reading_library():
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT r.id FROM reading_tasks r LEFT JOIN library_papers p ON p.reading_task_id=r.id
                WHERE r.status IN ('completed','failed') AND r.pdf_body IS NOT NULL
                AND (p.id IS NULL OR (r.status='completed' AND (p.translation_text IS NULL OR p.report_text IS NULL)))""")
            ids = [row['id'] for row in cur.fetchall()]
    for task_id in ids:
        archive_completed_reading(task_id)
    return len(ids)


def delete_library_paper(paper_id):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM library_papers WHERE id=%s',(paper_id,))
            return cur.rowcount == 1


def list_conversations(query=""):
    with connection() as conn:
        with conn.cursor() as cur:
            if query:
                cur.execute("""SELECT DISTINCT c.id, c.title, c.created_at, c.updated_at
                    FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id
                    WHERE c.title LIKE %s OR m.content LIKE %s
                    ORDER BY c.updated_at DESC LIMIT 100""", (f"%{query}%", f"%{query}%"))
            else:
                cur.execute("SELECT id,title,created_at,updated_at FROM conversations ORDER BY updated_at DESC LIMIT 100")
            return cur.fetchall()


def create_conversation():
    cid = str(uuid4())
    now = datetime.now()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO conversations (id,created_at,updated_at) VALUES (%s,%s,%s)", (cid, now, now))
    return cid


def get_conversation(cid):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,title,created_at,updated_at FROM conversations WHERE id=%s", (cid,))
            conversation = cur.fetchone()
            if not conversation:
                return None
            cur.execute("SELECT id,role,content,thinking_mode,created_at FROM messages WHERE conversation_id=%s ORDER BY created_at,id", (cid,))
            conversation["messages"] = cur.fetchall()
            for message in conversation["messages"]:
                cur.execute("SELECT id,filename,mime_type FROM attachments WHERE message_id=%s", (message["id"],))
                message["attachments"] = cur.fetchall()
            return conversation


def add_message(cid, role, content, thinking_mode="normal"):
    mid = str(uuid4())
    now = datetime.now()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO messages (id,conversation_id,role,content,thinking_mode,created_at) VALUES (%s,%s,%s,%s,%s,%s)", (mid,cid,role,content,thinking_mode,now))
            cur.execute("UPDATE conversations SET updated_at=%s WHERE id=%s", (now,cid))
            if role == "user":
                cur.execute("SELECT COUNT(*) AS n FROM messages WHERE conversation_id=%s AND role='user'", (cid,))
                if cur.fetchone()["n"] == 1:
                    cur.execute("UPDATE conversations SET title=%s WHERE id=%s", ((content.strip() or "附件对话")[:80],cid))
    return mid


def save_attachment(cid, filename, mime_type, body, extracted_text):
    aid = str(uuid4())
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO attachments (id,conversation_id,filename,mime_type,body,extracted_text,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)", (aid,cid,filename,mime_type,body,extracted_text,datetime.now()))
    return aid


def get_attachment(aid):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM attachments WHERE id=%s", (aid,))
            return cur.fetchone()


def bind_attachments(cid, mid, ids):
    if not ids:
        return []
    with connection() as conn:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(f"SELECT id,filename,mime_type,body,extracted_text FROM attachments WHERE conversation_id=%s AND message_id IS NULL AND id IN ({placeholders})", [cid,*ids])
            rows = cur.fetchall()
            if len(rows) != len(set(ids)):
                raise ValueError("附件不存在或已发送")
            cur.execute(f"UPDATE attachments SET message_id=%s WHERE conversation_id=%s AND id IN ({placeholders})", [mid,cid,*ids])
            return rows


def add_user_message_with_attachments(cid, content, thinking_mode, ids):
    mid = str(uuid4())
    now = datetime.now()
    with connection() as conn:
        with conn.cursor() as cur:
            if ids:
                placeholders = ",".join(["%s"] * len(ids))
                cur.execute(f"SELECT id FROM attachments WHERE conversation_id=%s AND message_id IS NULL AND id IN ({placeholders}) FOR UPDATE", [cid,*ids])
                if len(cur.fetchall()) != len(ids):
                    raise ValueError("附件不存在或已发送")
            cur.execute("INSERT INTO messages (id,conversation_id,role,content,thinking_mode,created_at) VALUES (%s,%s,'user',%s,%s,%s)", (mid,cid,content,thinking_mode,now))
            cur.execute("SELECT COUNT(*) AS n FROM messages WHERE conversation_id=%s AND role='user'", (cid,))
            if cur.fetchone()["n"] == 1:
                cur.execute("UPDATE conversations SET title=%s WHERE id=%s", ((content or "附件对话")[:80],cid))
            cur.execute("UPDATE conversations SET updated_at=%s WHERE id=%s", (now,cid))
            if ids:
                cur.execute(f"UPDATE attachments SET message_id=%s WHERE conversation_id=%s AND id IN ({placeholders})", [mid,cid,*ids])
    return mid


def get_conversation_attachments(cid):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,message_id,filename,mime_type,body,extracted_text FROM attachments WHERE conversation_id=%s AND message_id IS NOT NULL ORDER BY created_at", (cid,))
            return cur.fetchall()


def rename_conversation(cid, title):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE conversations SET title=%s,updated_at=%s WHERE id=%s", (title[:180],datetime.now(),cid))
            return cur.rowcount > 0


def delete_conversation(cid):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM conversations WHERE id=%s", (cid,))
            return cur.rowcount > 0


READING_COLUMNS = "id,input_type,source_value,filename,title,authors,source_label,status,error_message,output_format,report_language,document_language,translated_title,stage,total_segments,completed_segments,(pdf_body IS NOT NULL) AS has_original_pdf,(translation_pdf IS NOT NULL) AS has_translation_pdf,(report_body IS NOT NULL) AS has_report_body,created_at,updated_at"


def create_reading_task(input_type, source_value, filename, title, source_label, pdf_body=None, output_format='markdown', report_language='zh', report_template_text=None, report_template_body=None, authors=''):
    task_id = str(uuid4())
    now = datetime.now()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO reading_tasks
                (id,input_type,source_value,filename,title,authors,source_label,status,pdf_body,output_format,report_language,report_template_text,report_template_body,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s,%s,%s,%s,%s)""",
                (task_id,input_type,source_value,filename,title,(authors or '')[:500],source_label,pdf_body,output_format,report_language,report_template_text,report_template_body,now,now))
    return task_id


def list_reading_tasks(query="", status="all"):
    sql = f"SELECT {READING_COLUMNS} FROM reading_tasks WHERE 1=1"
    params = []
    if query:
        sql += " AND (title LIKE %s OR source_label LIKE %s OR authors LIKE %s)"
        params.extend([f"%{query}%"] * 3)
    if status != "all":
        sql += " AND status=%s"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def get_reading_task(task_id, include_pdf=False, include_template=False):
    cols = READING_COLUMNS + ",extracted_text,translation,report"
    if include_pdf:
        cols += ",pdf_body,translation_pdf,report_body,report_template_text,report_template_body"
    elif include_template:
        cols += ",report_body,report_template_body"
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {cols} FROM reading_tasks WHERE id=%s", (task_id,))
            return cur.fetchone()


def get_reading_pdf(task_id):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pdf_body,title FROM reading_tasks WHERE id=%s", (task_id,))
            row = cur.fetchone()
            return row if row and row['pdf_body'] else None


def set_reading_language(task_id, language):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reading_tasks SET document_language=%s,updated_at=%s WHERE id=%s",
                (language,datetime.now(),task_id))


def save_reading_translation(task_id, translation, translated_title, translation_pdf):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE reading_tasks SET translation=%s,translated_title=%s,translation_pdf=%s,
                updated_at=%s WHERE id=%s AND status='processing'""",
                (translation,translated_title[:500],translation_pdf,datetime.now(),task_id))
    archive_completed_reading(task_id)


def claim_reading_task(task_id):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reading_tasks SET status='processing',stage='acquiring',error_message=NULL,updated_at=%s WHERE id=%s AND status='queued'", (datetime.now(),task_id))
            return cur.rowcount == 1


def set_reading_stage(task_id, stage):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reading_tasks SET stage=%s,updated_at=%s WHERE id=%s AND status='processing'", (stage,datetime.now(),task_id))


def prepare_reading_segments(task_id, segments):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM reading_segments WHERE task_id=%s", (task_id,))
            existing = cur.fetchone()['n']
            if existing != len(segments):
                cur.execute("DELETE FROM reading_segments WHERE task_id=%s", (task_id,))
                cur.executemany("INSERT INTO reading_segments (task_id,segment_index,source_text) VALUES (%s,%s,%s)",
                    [(task_id,i,text) for i,text in enumerate(segments)])
            cur.execute("SELECT segment_index,source_text,translated_text FROM reading_segments WHERE task_id=%s ORDER BY segment_index", (task_id,))
            rows = cur.fetchall()
            cur.execute("UPDATE reading_tasks SET total_segments=%s,completed_segments=%s,stage='translating',updated_at=%s WHERE id=%s",
                (len(rows),sum(bool(row['translated_text']) for row in rows),datetime.now(),task_id))
            return rows


def save_reading_segment(task_id, index, translation):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reading_segments SET translated_text=%s WHERE task_id=%s AND segment_index=%s", (translation,task_id,index))
            cur.execute("UPDATE reading_tasks SET completed_segments=(SELECT COUNT(*) FROM reading_segments WHERE task_id=%s AND translated_text IS NOT NULL),updated_at=%s WHERE id=%s",
                (task_id,datetime.now(),task_id))


def finish_reading_task(task_id, title, authors, source_label, pdf_body, extracted_text, translation, report, report_body=None):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE reading_tasks SET title=%s,authors=%s,source_label=%s,pdf_body=%s,
                extracted_text=%s,translation=%s,report=%s,report_body=%s,status='completed',stage='completed',error_message=NULL,updated_at=%s
                WHERE id=%s AND status='processing'""",
                (title[:500],authors[:500],source_label[:80],pdf_body,extracted_text,translation,report,report_body,datetime.now(),task_id))
            return cur.rowcount == 1


def fail_reading_task(task_id, message):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reading_tasks SET status='failed',stage='failed',error_message=%s,updated_at=%s WHERE id=%s AND status='processing'", (message[:1000],datetime.now(),task_id))


def retry_reading_task(task_id):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE reading_tasks SET status='queued',stage='queued',error_message=NULL,translation=NULL,
                translated_title=NULL,translation_pdf=NULL,report=NULL,report_body=NULL,
                updated_at=%s WHERE id=%s AND status IN ('failed','completed')""", (datetime.now(),task_id))
            return cur.rowcount == 1


def delete_reading_task(task_id):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM reading_tasks WHERE id=%s", (task_id,))
            return cur.rowcount == 1


def recover_reading_tasks():
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE reading_tasks SET status='queued' WHERE status='processing'")
            cur.execute("SELECT id FROM reading_tasks WHERE status='queued'")
            return [row["id"] for row in cur.fetchall()]
