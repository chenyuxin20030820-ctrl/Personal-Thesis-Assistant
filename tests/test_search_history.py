import asyncio
import unittest
from unittest.mock import patch

from app import main


class SearchHistoryTests(unittest.TestCase):
    def test_latest_returns_saved_result(self):
        snapshot = {'items': [{'id': 'OA-W1'}], 'returned': 1, 'total': 1}
        row = {'id': '8e9cf048-504a-4c71-9bad-c4313fa53260',
               'sources': ['zh'], 'result': snapshot}
        with patch.object(main, 'require_db'), \
             patch.object(main.db, 'get_latest_search_task_id', return_value=row['id']), \
             patch.object(main.db, 'get_search_task', return_value=row):
            result = asyncio.run(main.latest_search_history())
        self.assertEqual(result['result'], snapshot)

    def test_latest_without_records_returns_null(self):
        with patch.object(main, 'require_db'), \
             patch.object(main.db, 'get_latest_search_task_id', return_value=None):
            self.assertIsNone(asyncio.run(main.latest_search_history()))


if __name__ == '__main__':
    unittest.main()
