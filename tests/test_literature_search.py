import unittest
from unittest.mock import patch

from app import main
from app.openalex_search import OpenAlexSearchError, normalize_work, search_openalex


class FakeResponse:
    status_code = 200

    def json(self):
        return {'meta': {'count': 1}, 'results': [{
            'id': 'https://openalex.org/W123', 'display_name': '数字金融研究',
            'publication_year': 2024, 'language': 'zh',
            'authorships': [{'author': {'display_name': '张三'}}],
            'abstract_inverted_index': {'研究': [0], '结果': [1]},
            'best_oa_location': {'pdf_url': 'https://example.org/paper.pdf'},
            'primary_location': {'source': {'display_name': '经济研究'}}}]}


class FakeClient:
    def __init__(self):
        self.params = None

    def get(self, url, params):
        self.params = params
        return FakeResponse()


class LiteratureSearchTests(unittest.TestCase):
    def test_openalex_query_and_normalization(self):
        client = FakeClient()
        result = search_openalex('数字金融', 2020, 2024, 10, 'year_desc', 'zh', client)
        self.assertIn('language:zh', client.params['filter'])
        self.assertIn('to_publication_date:2024-12-31', client.params['filter'])
        self.assertEqual(client.params['sort'], 'publication_date:desc')
        self.assertEqual(result['items'][0]['id'], 'OA-W123')
        self.assertEqual(result['items'][0]['abstract'], '研究 结果')
        self.assertEqual(result['items'][0]['pdf_url'], 'https://example.org/paper.pdf')

    def test_full_openalex_results_skip_serpapi(self):
        papers = [{'id': 'OA-W1', 'title': 'Study', 'doi': None}]
        with patch.object(main, 'search_openalex', return_value={'total': 25, 'returned': 1,
                'items': papers, 'mock': False, 'provider': 'OpenAlex'}), \
             patch.object(main, 'search_google_scholar') as scholar:
            result = main.search_literature_sources('topic', 2020, 2024, 1, 'relevance', 'en')
        scholar.assert_not_called()
        self.assertEqual(result['provider'], 'OpenAlex')

    def test_openalex_failure_uses_serpapi(self):
        paper = {'id': 'GS-1', 'title': 'Research Paper', 'doi': None}
        with patch.object(main, 'search_openalex', side_effect=OpenAlexSearchError('HTTP 429')), \
             patch.object(main, 'search_google_scholar', return_value={'total': 20, 'items': [paper]}):
            result = main.search_literature_sources('topic', 2020, 2024, 10, 'relevance', 'en')
        self.assertEqual(result['provider'], 'SerpApi Google Scholar')
        self.assertEqual(result['items'], [paper])
        self.assertIn('OpenAlex 检索失败', result['warning'])

    def test_missing_abstract_does_not_invent_analysis(self):
        paper = normalize_work({'id': 'https://openalex.org/W123', 'display_name': 'Study'})
        self.assertIn('不足', paper['analysis']['method'])


if __name__ == '__main__':
    unittest.main()
