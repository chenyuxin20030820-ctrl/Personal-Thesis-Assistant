"""Normalize Google Scholar records returned by SerpApi without inventing full-text analysis."""

import hashlib
import re
from urllib.parse import parse_qs, urlparse

import httpx

from .config import settings

ENDPOINT = 'https://serpapi.com/search.json'


class ScholarSearchError(RuntimeError):
    pass


def public_url(value):
    if not isinstance(value,str):
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
        return None
    if parsed.hostname.casefold().endswith('serpapi.com') or 'api_key' in parse_qs(parsed.query):
        return None
    return value[:2000]


def normalize_result(row):
    title = str(row.get('title') or '').strip()[:500]
    if not title:
        return None
    info = row.get('publication_info') or {}
    summary = str(info.get('summary') or '')
    raw_authors = info.get('authors') or []
    names = [str(author.get('name') or '').strip() for author in raw_authors if isinstance(author,dict)]
    authors = '; '.join(name for name in names if name)[:500]
    years = re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)',summary)
    year = int(years[-1]) if years else 0
    parts = summary.split(' - ')
    venue = (parts[1] if len(parts)>1 else summary).strip()[:300]
    snippet = str(row.get('snippet') or '').strip()[:5000]
    link = public_url(row.get('link'))
    resources = row.get('resources') or []
    pdf_url = next((public_url(resource.get('link')) for resource in resources
        if isinstance(resource,dict) and str(resource.get('file_format') or '').upper() == 'PDF'
        and public_url(resource.get('link'))),None)
    if not pdf_url and link and urlparse(link).path.lower().endswith('.pdf'):
        pdf_url = link
    doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+',link or '',re.I)
    doi = doi_match.group(0)[:255] if doi_match else None
    identity = str(row.get('result_id') or link or title)
    record_id = 'GS-SERP-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
    unavailable = '检索片段不足以可靠判断；请查看原文。'
    return {
        'id':record_id,'source':'Google Scholar','is_mock':False,'title':title,
        'year':year,'authors':authors,'venue':venue,'document_type':'学术文献',
        'doi':doi,'url':link,'pdf_url':pdf_url,'abstract':snippet,
        'analysis':{'summary':snippet or '检索结果未提供摘要片段。',
            'purpose':unavailable,'method':unavailable,'empirical_process':unavailable,
            'basis':'SerpApi Google Scholar 检索片段；未获取或阅读论文全文'},
    }


def search_google_scholar(query,year_from,year_to,limit,sort='relevance',language='all',client=None):
    if not settings.serpapi_key:
        raise ScholarSearchError('SerpApi 密钥尚未配置，请填写 .env 中的 SERPAPI_API_KEY')
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(35,connect=8),trust_env=False)
    results = []
    seen = set()
    total = 0
    try:
        for start in range(0,limit,20):
            params = {'engine':'google_scholar','q':query,'as_ylo':year_from,'as_yhi':year_to,
                'start':start,'num':min(20,limit-start),'api_key':settings.serpapi_key,'output':'json'}
            if language in {'zh','en'}:
                params['lr'] = 'lang_'+language
            try:
                response = client.get(ENDPOINT,params=params)
            except httpx.HTTPError as exc:
                raise ScholarSearchError('SerpApi 请求失败，请检查网络后重试') from exc
            if response.status_code in {401,403}:
                raise ScholarSearchError('SerpApi 授权失败，请检查 API Key')
            if response.status_code == 429:
                raise ScholarSearchError('SerpApi 请求额度或速率受限，请稍后重试')
            if response.status_code >= 400:
                raise ScholarSearchError(f'SerpApi 检索失败（HTTP {response.status_code}）')
            try:
                payload = response.json()
            except ValueError as exc:
                raise ScholarSearchError('SerpApi 返回了无效数据') from exc
            rows = payload.get('organic_results') or []
            if payload.get('error') and not rows:
                if (payload.get('search_information') or {}).get('total_results') == 0:
                    break
                raise ScholarSearchError('SerpApi 未能完成检索，请调整关键词后重试')
            if payload.get('search_metadata',{}).get('status') not in {None,'Success'}:
                raise ScholarSearchError('SerpApi 检索尚未完成，请稍后重试')
            total = max(total,int((payload.get('search_information') or {}).get('total_results') or 0))
            if not rows:
                break
            for row in rows:
                paper = normalize_result(row)
                if paper and paper['id'] not in seen:
                    seen.add(paper['id'])
                    results.append(paper)
            if len(rows)<params['num'] or len(results)>=limit:
                break
    finally:
        if own_client:
            client.close()
    results = results[:limit]
    if sort == 'year_asc':
        results.sort(key=lambda paper:(paper['year'] or 9999,paper['title']))
    elif sort == 'year_desc':
        results.sort(key=lambda paper:(-paper['year'],paper['title']))
    return {'total':total or len(results),'returned':len(results),'items':results,'mock':False,
        'provider':'SerpApi Google Scholar'}
