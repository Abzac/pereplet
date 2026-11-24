"""First-run shelf must never replace or refill an existing personal library."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import library, starter_library as starter


class StarterLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = library.DATA_DIR
        library.DATA_DIR = Path(self.temp.name) / 'data'

    def tearDown(self):
        library.DATA_DIR = self.previous
        self.temp.cleanup()

    def test_fresh_restart_and_deleted_book(self):
        self.assertEqual(starter.seed_starter_library(), 13)
        books = library.list_books()
        expected = json.loads((starter.BUNDLE / 'manifest.json').read_text(encoding='utf-8'))['books']
        self.assertEqual({b['title'] for b in books}, {b['title'] for b in expected})
        for book in books:
            self.assertTrue(book['cover_url'])
            self.assertEqual(book['series'], next(entry['series'] for entry in expected if entry['title'] == book['title']))
            self.assertGreater(book['chapter_count'], 0)
            self.assertEqual(book['progress'], 0)
        self.assertEqual(starter.seed_starter_library(), 0)
        library.delete_book(books[0]['id'])
        self.assertEqual(starter.seed_starter_library(), 0)
        self.assertEqual(len(library.list_books()), 12)

    def test_existing_even_empty_library_is_untouched(self):
        library.init()
        self.assertEqual(starter.seed_starter_library(), 0)
        self.assertEqual(library.list_books(), [])

    def test_interruption_after_committed_import_resumes_without_duplicate(self):
        original = library.import_path
        def interrupted(*args):
            original(*args)
            raise RuntimeError('simulated interruption after import')
        with patch.object(library, 'import_path', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                starter.seed_starter_library()
        self.assertEqual(starter.seed_starter_library(), 12)
        self.assertEqual(len(library.list_books()), 13)

    def test_missing_bundle_does_not_create_database_or_poison_retry(self):
        with patch.object(starter, 'BUNDLE', Path(self.temp.name) / 'missing'):
            with self.assertRaises(RuntimeError):
                starter.seed_starter_library()
        self.assertFalse((library.DATA_DIR / 'library.sqlite').exists())


if __name__ == '__main__':
    unittest.main()
