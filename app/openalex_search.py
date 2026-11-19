"""Search OpenAlex works and preserve only evidence present in its metadata."""

import re

import httpx

from .config import settings
from .scholar_serpapi import public_url

ENDPOINT = 'https://api.openalex.org/works'


class OpenAlexSearchError(RuntimeError):
    pass


def restore_abstract(index):
    if not isinstance(index, dict):
        return ''
    positions = [(position, word) for word, offsets in index.items()
                 if isinstance(offsets, list) for position in offsets
                 if isinstance(position, int) and 0 <= position < 2000]
    positions.sort()
    return ' '.join(word for _, word in positions)[:5000]


def normalize_work(work):
    title = str(work.get('display_name') or work.get('title') or '').strip()[:500]
    work_id = str(work.get('id') or '').rsplit('/', 1)[-1]
    if not title or not re.fullmatch(r'W\d+', work_id):
        return None
    primary = work.get('primary_location') or {}
    best = work.get('best_oa_location') or {}
    locations = work.get('locations') or []
    pdf_url = public_url(best.get('pdf_url')) or next(
        (public_url(place.get('pdf_url')) for place in locations
         if isinstance(place, dict) and place.get('is_oa') and public_url(place.get('pdf_url'))), None)
    source = primary.get('source') or {}
    doi = str(work.get('doi') or '').removeprefix('https://doi.org/').strip() or None
    abstract = restore_abstract(work.get('abstract_inverted_index'))
    unavailable = 'OpenAlex 元数据不足以可靠判断；请查看原文。'
    return {
        'id': f'OA-{work_id}', 'source': 'OpenAlex', 'is_mock': False,
        'title': title, 'year': work.get('publication_year') or 0,
        'authors': '; '.join(str((part.get('author') or {}).get('display_name') or '')
                             for part in work.get('authorships') or [] if isinstance(part, dict))[:500],
        'venue': str(source.get('display_name') or '')[:300],
        'document_type': str(work.get('type') or '学术文献')[:80],
        'doi': doi, 'url': public_url(primary.get('landing_page_url')) or public_url(work.get('doi'))
               or public_url(work.get('id')), 'pdf_url': pdf_url,
        'abstract': abstract,
        'analysis': {'summary': abstract or 'OpenAlex 未提供摘要。',
                     'purpose': unavailable, 'method': unavailable,
                     'empirical_process': unavailable,
                     'basis': 'OpenAlex 论文元数据与摘要；未获取或阅读论文全文'},
    }


def search_openalex(query, year_from, year_to, limit, sort='relevance', language='zh', client=None):
    params = {
        'search': query,
        'filter': f'language:{language},from_publication_date:{year_from}-01-01,to_publication_date:{year_to}-12-31',
        'per_page': min(limit, 100),
        'page': 1,
    }
    if sort == 'year_asc':
        params['sort'] = 'publication_date:asc'
    elif sort == 'year_desc':
        params['sort'] = 'publication_date:desc'
    if settings.openalex_api_key:
        params['api_key'] = settings.openalex_api_key
    own_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(25, connect=8), trust_env=False)
    try:
        try:
            response = client.get(ENDPOINT, params=params)
        except httpx.HTTPError as exc:
            raise OpenAlexSearchError('OpenAlex 请求失败') from exc
        if response.status_code != 200:
            raise OpenAlexSearchError(f'OpenAlex 检索失败（HTTP {response.status_code}）')
        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenAlexSearchError('OpenAlex 返回了无效数据') from exc
    finally:
        if own_client:
            client.close()
    items = [item for work in payload.get('results') or [] if (item := normalize_work(work))]
    return {'total': int((payload.get('meta') or {}).get('count') or len(items)),
            'returned': len(items), 'items': items, 'mock': False, 'provider': 'OpenAlex'}
