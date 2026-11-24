"""Text import and misleading-extension regressions in a disposable library."""
from __future__ import annotations

import codecs
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend import library
from backend.parsers import BookParseError, CHUNK_HARD


class TextImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pereplet-text-test-")
        self.root = Path(self.temp.name)
        self.previous = library.DATA_DIR
        library.DATA_DIR = self.root / "data"

    def tearDown(self):
        library.DATA_DIR = self.previous
        self.temp.cleanup()

    def write(self, name, data):
        source = self.root / name
        source.write_bytes(data)
        return source

    def paragraphs(self, book):
        return [paragraph["text"] for index in range(book["chapter_count"])
                for paragraph in library.get_chapter(book["id"], index)["paragraphs"]]

    def assert_empty_library(self):
        self.assertEqual(library.list_books(), [])
        self.assertEqual(list((library.DATA_DIR / "books").iterdir()), [])

    def test_rtf_disguised_as_fb2_or_zipped_fb2_is_explained_and_cleaned_up(self):
        raw = br"{\rtf1\ansi\ansicpg1251{\fonttbl{\f0 Times New Roman;}}\f0 Test\par}"
        source = self.write("not-an-xml-book.fb2", raw)
        with self.assertRaisesRegex(BookParseError, "RTF, а не FB2"):
            library.import_path(source)
        self.assertEqual(source.read_bytes(), raw)
        self.assert_empty_library()
        archive = self.root / "not-an-xml-book.fb2.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("book.fb2", raw)
        with self.assertRaisesRegex(BookParseError, "RTF, а не FB2"):
            library.import_path(archive)
        self.assert_empty_library()

    def test_unicode_txt_paragraphs_title_and_safe_html(self):
        original = "Первый абзац: ёж и € 😺.\r\nПеренос строки.\r\n\r\n<script>alert(1)</script> & текст."
        for name, data, expected_encoding in (
            ("Тихий вечер.txt", original.encode("utf-8"), "UTF-8"),
            ("С BOM.txt", codecs.BOM_UTF8 + original.encode("utf-8"), "UTF-8 (BOM)"),
            ("LE.txt", codecs.BOM_UTF16_LE + original.encode("utf-16-le"), "UTF-16 LE"),
            ("BE.txt", codecs.BOM_UTF16_BE + original.encode("utf-16-be"), "UTF-16 BE"),
        ):
            with self.subTest(encoding=expected_encoding):
                source = self.write(name, data)
                book = library.import_path(source)["book"]
                self.assertEqual(book["title"], Path(name).stem)
                self.assertEqual(book["format"], "TXT")
                self.assertEqual(book["text_encoding"], expected_encoding)
                self.assertEqual(book["import_warnings"], [])
                self.assertEqual(self.paragraphs(book), ["Первый абзац: ёж и € 😺. Перенос строки.", "<script>alert(1)</script> & текст."])
                chapter = library.get_chapter(book["id"], 0)
                self.assertNotIn("<script>", chapter["html"])
                self.assertIn("&lt;script&gt;", chapter["html"])
                self.assertEqual(source.read_bytes(), data)
                managed = library.DATA_DIR / "books" / book["id"] / "original.txt"
                self.assertEqual(managed.read_bytes(), data)
                self.assertTrue(library.import_path(source)["duplicate"])

    def test_windows1251_after_long_ascii_prefix_has_explicit_warning(self):
        prefix = "English preface. " * 5000
        original = prefix + "\n\nСъешь ещё этих мягких французских булок. Ёжик."
        source = self.write("Старая книга.txt", original.encode("cp1251"))
        book = library.import_path(source)["book"]
        self.assertEqual(book["text_encoding"], "Windows-1251")
        self.assertTrue(book["import_warnings"])
        self.assertIn("Windows-1251", book["import_warnings"][0])
        self.assertEqual(self.paragraphs(book)[-1], "Съешь ещё этих мягких французских булок. Ёжик.")
        self.assertNotIn("\ufffd", "".join(self.paragraphs(book)))

    def test_invalid_declared_unicode_or_binary_is_not_silently_redecoded(self):
        for name, raw in (
            ("broken-utf8.txt", codecs.BOM_UTF8 + b"Valid start then \xff"),
            ("broken-utf16.txt", codecs.BOM_UTF16_LE + b"A\x00x"),
            ("undefined-cp1251.txt", b"Text \x98"),
            ("binary.txt", b"Text \x00\x01\x02"),
            ("utf32.txt", "Text".encode("utf-32")),
            ("renamed-rtf.txt", br"{\rtf1\ansi Test}"),
        ):
            with self.subTest(file=name):
                source = self.write(name, raw)
                with self.assertRaises(BookParseError):
                    library.import_path(source)
                self.assertEqual(source.read_bytes(), raw)
                self.assert_empty_library()

    def test_large_single_paragraph_stays_bounded_without_losing_text(self):
        text = "Я" * (CHUNK_HARD * 3 + 777)
        source = self.write("Большой абзац.txt", text.encode("utf-8"))
        book = library.import_path(source)["book"]
        self.assertGreater(book["chapter_count"], 1)
        self.assertEqual("".join(self.paragraphs(book)), text)
        for index in range(book["chapter_count"]):
            self.assertLess(len(library.get_chapter(book["id"], index)["html"]), CHUNK_HARD + 10000)

    def test_blank_text_does_not_create_empty_book(self):
        source = self.write("Пусто.txt", b"\n \t\r\n")
        with self.assertRaisesRegex(BookParseError, "не найдено"):
            library.import_path(source)
        self.assert_empty_library()


if __name__ == "__main__":
    unittest.main()
