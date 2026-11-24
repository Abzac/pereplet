"""Guide discovery must preserve an existing library and reading position."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend import library, starter_library

class GuideTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch.object(library,'DATA_DIR',Path(self.temp.name)/'data');self.patch.start()
    def tearDown(self):
        self.patch.stop();self.temp.cleanup()
    def test_help_imports_only_guide_and_reuses_it_with_progress(self):
        library.init()
        guide=starter_library.reader_guide()
        self.assertTrue(guide['is_reader_guide'])
        self.assertEqual(len(library.list_books()),1)
        library.update_book(guide['id'],{'progress':12,'chapter':1})
        reopened=starter_library.reader_guide()
        self.assertEqual(reopened['id'],guide['id'])
        self.assertEqual(reopened['progress'],12)
        self.assertEqual(len(library.list_books()),1)
        library.save_settings({'readerGuideHidden':True})
        self.assertTrue(library.get_settings()['readerGuideHidden'])
        self.assertEqual(starter_library.reader_guide()['id'],guide['id'])
    def test_missing_guide_is_recoverable_without_importing_classics(self):
        first=starter_library.reader_guide()
        library.delete_book(first['id'])
        second=starter_library.reader_guide()
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(len(library.list_books()),1)
    def test_missing_bundle_gives_clear_error(self):
        with patch.object(starter_library,'BUNDLE',Path(self.temp.name)/'missing'):
            with self.assertRaisesRegex(ValueError,'Руководство не найдено'):
                starter_library.reader_guide()
