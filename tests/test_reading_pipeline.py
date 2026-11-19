import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app import reading
from app.file_names import original_pdf_name, chinese_pdf_name, report_name


class FakeAgent:
    def __init__(self, kind):
        self.kind = kind
        self.calls = []

    def invoke(self, payload):
        prompt = payload['messages'][0]['content']
        self.calls.append(prompt)
        if self.kind == 'translator':
            answer = f'译文 {len(self.calls)}'
        elif '模式：最终报告' in prompt:
            answer = '# 阅读报告\n完整'
        elif '模式：压缩记忆' in prompt:
            answer = '压缩事实'
        else:
            answer = '事实' * 1600
        return {'messages': [type('Message', (), {'content': answer})()]}


class ReadingPipelineTests(unittest.TestCase):
    def test_paragraph_order_and_two_agents(self):
        translator, reporter = FakeAgent('translator'), FakeAgent('reporter')
        with patch.object(reading, '_agent', side_effect=[translator, reporter]):
            translation, translated_title = reading.translate_paper('First paragraph.\n\nSecond paragraph.', 'Paper')
            report = reading.generate_report('First paragraph.\n\nSecond paragraph.', 'Paper',
                '## 研究目的', 'markdown', '## 研究目的'.encode())
        self.assertEqual(translation, '译文 2\n\n译文 3')
        self.assertEqual(translated_title, '译文 1')
        self.assertIn('阅读报告', report)
        self.assertEqual(len(translator.calls), 3)
        self.assertIn('First paragraph.', reporter.calls[0])
        self.assertIn('Second paragraph.', reporter.calls[0])

    def test_progressive_compression_reads_all_batches(self):
        reporter = FakeAgent('reporter')
        paragraphs = [f'段落 {i} ' + 'evidence ' * 250 for i in range(12)]
        with patch.object(reading, 'settings', SimpleNamespace(reading_context_tokens=8000)):
            report = reading.build_reading_report(reporter, paragraphs, 'Paper')
        self.assertIn('阅读报告', report)
        self.assertTrue(any('模式：压缩记忆' in call for call in reporter.calls))
        self.assertTrue(any('段落 11' in call for call in reporter.calls))

    def test_large_paragraph_stays_within_batch_budget(self):
        batches = reading._report_batches(['研究' * 5000], 2000)
        self.assertGreater(len(batches), 1)
        self.assertTrue(all(reading._tokens(batch) <= 2000 for batch in batches))

    def test_report_uses_uploaded_template_sections(self):
        reporter = FakeAgent('reporter')
        reading.build_reading_report(reporter, ['Paper evidence.'], 'Paper',
            template_text='研究背景 | 实证方法 | 结论')
        self.assertIn('研究背景 | 实证方法 | 结论', reporter.calls[-1])

    def test_document_language(self):
        self.assertEqual(reading.detect_document_language('这是中文论文的研究方法和结论。' * 8), 'zh')
        self.assertEqual(reading.detect_document_language('The empirical study uses panel data. ' * 20), 'en')

    def test_artifact_names(self):
        self.assertEqual(original_pdf_name('A/B: Paper'), 'A B Paper.pdf')
        self.assertEqual(chinese_pdf_name('数字金融研究'), '数字金融研究.pdf')
        self.assertEqual(report_name('A Paper', 'xlsx'), 'A Paper阅读报告.xlsx')

    def test_chinese_paper_skips_translation(self):
        task = {'input_type': 'upload', 'title': '原题', 'authors': '', 'source_label': '本地上传',
            'pdf_body': b'%PDF-probe', 'output_format': 'markdown',
            'report_template_text': '## 研究目的', 'report_template_body': '## 研究目的'.encode()}
        with patch.object(reading.db, 'claim_reading_task', return_value=True), \
             patch.object(reading.db, 'get_reading_task', return_value=task), \
             patch.object(reading, 'acquire_pdf', return_value=(b'%PDF-probe', '原题', '', '本地上传')), \
             patch.object(reading, 'extract_pdf_text', return_value=('中文论文内容' * 30, '中文题目', '作者')), \
             patch.object(reading, 'detect_document_language', return_value='zh'), \
             patch.object(reading, 'translate_paper') as translate, \
             patch.object(reading, 'generate_report', return_value='## 研究目的\n报告'), \
             patch.object(reading, 'render_filled_report', return_value=b'filled'), \
             patch.object(reading.db, 'record_reading_document'), \
             patch.object(reading.db, 'set_reading_stage'), \
             patch.object(reading.db, 'set_reading_language'), \
             patch.object(reading.db, 'finish_reading_task', return_value=True) as finish, \
             patch.object(reading.db, 'archive_completed_reading'), \
             patch.object(reading.db, 'fail_reading_task') as fail:
            reading.process_reading_task('task-id')
        translate.assert_not_called()
        self.assertIsNone(finish.call_args.args[6])
        fail.assert_not_called()


class DoiAcquisitionTests(unittest.TestCase):
    doi = '10.1234/example.2024'

    def response(self, status, data):
        return httpx.Response(status, json=data, request=httpx.Request('GET', 'https://example.com'))

    def test_openalex_pdf_takes_priority(self):
        work = {'display_name': 'Target Paper', 'best_oa_location':
            {'is_oa': True, 'pdf_url': 'https://publisher.example/paper.pdf'}}
        with patch.object(reading.httpx, 'get', return_value=self.response(200, work)) as get, \
             patch.object(reading, 'download_pdf', return_value=b'%PDF-openalex'):
            body, title, _, source = reading.acquire_pdf({'input_type': 'doi', 'source_value': self.doi})
        self.assertEqual((body, title, source), (b'%PDF-openalex', 'Target Paper', 'OpenAlex 开放获取'))
        self.assertEqual(get.call_count, 1)

    def test_serpapi_fallback_when_openalex_has_no_pdf(self):
        work = {'display_name': 'Target Paper', 'locations': []}
        scholar = {'organic_results': [{'title': 'Target Paper', 'resources': [
            {'file_format': 'PDF', 'link': 'https://archive.example/target.pdf'}]}]}
        with patch.object(reading, 'settings', SimpleNamespace(serpapi_key='test')), \
             patch.object(reading.httpx, 'get', side_effect=[self.response(200, work), self.response(200, scholar)]) as get, \
             patch.object(reading, 'download_pdf', return_value=b'%PDF-scholar') as download:
            body, _, _, source = reading.acquire_pdf({'input_type': 'doi', 'source_value': self.doi})
        self.assertEqual((body, source), (b'%PDF-scholar', 'SerpApi Google Scholar'))
        self.assertEqual(get.call_count, 2)
        download.assert_called_once_with('https://archive.example/target.pdf')

    def test_serpapi_rejects_unverified_result(self):
        scholar = {'organic_results': [{'title': 'Different Paper', 'resources': [
            {'file_format': 'PDF', 'link': 'https://archive.example/other.pdf'}]}]}
        with patch.object(reading, 'settings', SimpleNamespace(serpapi_key='test')), \
             patch.object(reading.httpx, 'get', side_effect=[self.response(404, {}), self.response(200, scholar)]), \
             patch.object(reading, 'download_pdf', return_value=b'%PDF-other'), \
             patch.object(reading, '_pdf_mentions_doi', return_value=False):
            with self.assertRaisesRegex(ValueError, '均未找到可验证'):
                reading.acquire_pdf({'input_type': 'doi', 'source_value': self.doi})


if __name__ == '__main__':
    unittest.main()
