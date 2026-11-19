import asyncio
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

from app import main


class ReadingApiTests(unittest.TestCase):
    def test_template_required_before_task_creation(self):
        with patch.object(main, 'require_db'), \
             patch.object(main.db, 'get_report_template', return_value=None):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(main.create_reading_task(BackgroundTasks(), reference='10.1234/example'))
        self.assertEqual(context.exception.status_code, 409)
        self.assertIn('上传文献阅读报告模板', context.exception.detail)

    def test_search_result_creates_single_reading_task(self):
        paper = {'id': 'GS-1', 'title': 'Example Paper', 'authors': 'A. Author',
                 'source': 'Google Scholar', 'is_mock': False,
                 'doi': '10.1234/example', 'pdf_url': None}
        template = {'report_template_body': b'data', 'report_template_text': 'template',
                    'report_template_format': 'pdf'}
        with patch.object(main, 'require_db'), \
             patch.object(main, 'resolve_search_papers', return_value=[paper]), \
             patch.object(main.db, 'get_report_template', return_value=template), \
             patch.object(main.db, 'create_reading_task', return_value='task-1') as create:
            background = BackgroundTasks()
            result = asyncio.run(main.create_reading_from_search(background, main.ReadSearchRequest(id='GS-1')))
        self.assertEqual(result, {'id': 'task-1', 'status': 'queued'})
        self.assertEqual(create.call_args.args[0:5], ('doi', '10.1234/example', None, 'Example Paper', 'Google Scholar'))
        self.assertEqual(create.call_args.args[-1], 'A. Author')
        self.assertEqual(len(background.tasks), 1)

    def test_mock_search_result_cannot_start_reading(self):
        with patch.object(main, 'require_db'), \
             patch.object(main, 'resolve_search_papers', return_value=[{'is_mock': True}]):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(main.create_reading_from_search(BackgroundTasks(), main.ReadSearchRequest(id='MOCK-1')))
        self.assertEqual(context.exception.status_code, 422)


if __name__ == '__main__':
    unittest.main()
