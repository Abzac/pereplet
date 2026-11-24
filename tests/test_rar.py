"""Real UnRAR callback/CBR checks against tiny synthetic archives only."""
from __future__ import annotations

import ctypes
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import library, paged, rar
from backend.parsers import BookParseError

FIXTURES = Path(__file__).parent / "fixtures" / "cbr"


def png(color="red"):
    with Image.new("RGBA", (40, 60), color) as image:
        stream = io.BytesIO()
        image.save(stream, "PNG")
        return stream.getvalue()


def stored_rar4(entries, *, declared_size=None, main_flags=0, file_flags=0):
    def block(body):
        return struct.pack("<H", zlib.crc32(body) & 0xffff) + body
    data = b"Rar!\x1a\x07\x00" + block(struct.pack("<BHHHI", 0x73, main_flags, 13, 0, 0))
    for name, raw in entries:
        name = name.encode("ascii")
        data += block(struct.pack("<BHHIIBIIBBHI", 0x74, 0x8000 | file_flags, 32 + len(name),
                                  len(raw), len(raw) if declared_size is None else declared_size,
                                  2, zlib.crc32(raw), 0, 20, 0x30, len(name), 0x20) + name) + raw
    return data + block(struct.pack("<BHH", 0x7b, 0, 7))


@unittest.skipUnless(os.name == "nt" and ctypes.sizeof(ctypes.c_void_p) == 8, "bundled DLL requires Windows x64")
class RarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pereplet-cbr-test-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def original(self, data):
        source = self.root / "original.cbr"
        source.write_bytes(data)
        return source

    def test_official_packed_abi_and_dll_api(self):
        self.assertEqual(ctypes.sizeof(rar._OpenData), 176)
        self.assertEqual(ctypes.sizeof(rar._Header), 10244)
        self.assertEqual(rar._library().RARGetDllVersion(), 9)

    def test_rar4_unicode_archive_path_and_nested_member_use_test_only(self):
        source = self.root / "Комикс.cbr"
        expected = png()
        source.write_bytes(stored_rar4([("pages\\1.png", expected)]))
        native, operations = rar._library(), []
        class ObservedDll:
            def __getattr__(self, key):
                return getattr(native, key)
            def RARProcessFileW(self, handle, operation, path, name):
                operations.append(operation)
                self_outer.assertIsNone(path)
                self_outer.assertIsNone(name)
                return native.RARProcessFileW(handle, operation, path, name)
        self_outer = self
        with patch.object(rar, "_dll", ObservedDll()):
            self.assertEqual(rar.members(source)[0]["name"], "pages/1.png")
            self.assertEqual(rar.read_member(source, "pages/1.png", 1024), expected)
        self.assertEqual(operations, [rar.RAR_SKIP, rar.RAR_TEST])
        self.assertFalse((self.root / "pages").exists())

    def test_real_solid_rar5_metadata_sorted_pages_transparency_and_cache(self):
        source = self.original((FIXTURES / "solid-rar5.cbr").read_bytes())
        original = source.read_bytes()
        with patch.object(paged, "_rar_image", wraps=paged._rar_image) as renderer:
            meta = paged.prepare_paged(source, "Test.cbr", self.root, "a" * 32)
            self.assertEqual(renderer.call_count, 1)
        self.assertEqual(meta["format"], "CBR")
        self.assertEqual(meta["reader_type"], "pages")
        self.assertEqual(meta["page_count"], 3)
        self.assertEqual(meta["title"], "CBR regression")
        self.assertEqual(meta["authors"], ["Test author"])
        manifest = json.loads((self.root / paged.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(manifest["entries"], ["1.png", "2.png", "10.png"])
        self.assertFalse((self.root / "pages").exists())
        for index, color in [(0, (255, 255, 255)), (1, (255, 0, 0)), (2, (0, 0, 255))]:
            with Image.open(paged.render_page(self.root, meta, index, 800)) as image:
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.getpixel((0, 0)), color)
        with patch.object(paged, "_rar_image", side_effect=AssertionError("must use PNG cache")):
            self.assertTrue(paged.render_page(self.root, meta, 2, 800).is_file())
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse((self.root / "1.png").exists())

    def test_password_headers_and_files_fail_without_prompt_and_release_handle(self):
        for name in ["encrypted-headers.cbr", "encrypted-file.cbr"]:
            with self.subTest(name=name):
                source = self.original((FIXTURES / name).read_bytes())
                started = time.monotonic()
                with self.assertRaisesRegex(BookParseError, "паролем"):
                    rar.members(source)
                self.assertLess(time.monotonic() - started, 2)
                source.unlink()  # Windows would fail if native handles leaked.

    def test_paths_duplicates_and_multivolume_are_rejected(self):
        for name in ["../bad.png", "..\\bad.png", "/bad.png"]:
            with self.subTest(name=name), self.assertRaises(BookParseError):
                rar.members(self.original(stored_rar4([(name, png())])))
        # UnRAR itself normalizes these Windows-invalid characters. They remain
        # relative member identifiers; RAR_TEST cannot write a drive path or ADS.
        for name in ["C:/bad.png", "folder/file:stream.png"]:
            source = self.original(stored_rar4([(name, png())]))
            member = rar.members(source)[0]["name"]
            self.assertNotIn(":", member)
            self.assertEqual(rar.read_member(source, member, 1024), png())
        with self.assertRaisesRegex(BookParseError, "повторяющиеся"):
            rar.members(self.original(stored_rar4([("Page.png", png()), ("page.png", png())])))
        with self.assertRaisesRegex(BookParseError, "Многотомные"):
            rar.members(self.original(stored_rar4([("1.png", png())], main_flags=1)))

    def test_size_dictionary_and_file_count_limits(self):
        source = self.original(stored_rar4([("1.png", png())], declared_size=1024**3 + 1))
        with self.assertRaisesRegex(BookParseError, "лимит распаковки"):
            rar.members(source)
        source = self.original((FIXTURES / "solid-rar5.cbr").read_bytes())
        with patch.object(rar, "MAX_DICTIONARY_KIB", 0), self.assertRaisesRegex(BookParseError, "Словарь"):
            rar.members(source)
        with patch.object(rar, "MAX_FILES", 1), self.assertRaisesRegex(BookParseError, "много файлов"):
            rar.members(source)
        with self.assertRaisesRegex(BookParseError, "большая страница"):
            rar.read_member(source, "1.png", 10)

    def test_corrupt_payload_and_missing_member_report_errors(self):
        source = self.original(stored_rar4([("1.png", png())]))
        with self.assertRaisesRegex(BookParseError, "отсутствует"):
            rar.read_member(source, "absent.png", 1024)
        raw = bytearray(source.read_bytes())
        payload = raw.index(b"\x89PNG")
        raw[payload + 20] ^= 0xff
        source.write_bytes(raw)
        with self.assertRaisesRegex(BookParseError, "повреждённый"):
            rar.read_member(source, "1.png", 1024)

    def test_invalid_native_component_is_not_loaded(self):
        wrong = self.root / "UnRAR64.dll"
        wrong.write_bytes(b"not a DLL")
        with patch.object(rar, "DLL_PATH", wrong), patch.object(rar, "_dll", None):
            with self.assertRaisesRegex(BookParseError, "отсутствует или повреждена"):
                rar._library()

    def test_library_cbr_import_page_and_duplicate_are_isolated(self):
        source = self.original((FIXTURES / "solid-rar5.cbr").read_bytes())
        with patch.object(library, "DATA_DIR", self.root / "isolated-data"):
            first = library.import_path(source)
            self.assertEqual(first["book"]["format"], "CBR")
            self.assertEqual(first["book"]["page_count"], 3)
            self.assertTrue(library.get_page(first["book"]["id"], 2, 800).is_file())
            self.assertTrue(library.import_path(source)["duplicate"])


class CallbackTests(unittest.TestCase):
    def test_callback_checks_size_before_copying_or_allocating(self):
        state = rar._State(2)
        state.collecting = True
        buffer = ctypes.create_string_buffer(b"abcd")
        self.assertEqual(state.callback(1, 0, ctypes.addressof(buffer), 4), -1)
        self.assertEqual(len(state.buffer), 0)
        self.assertIn("размер", state.error)

    def test_callbacks_refuse_password_volumes_large_dictionary_and_timeout(self):
        for message, pointer in [(0, 0), (3, 0), (2, 0), (4, 0), (5, rar.MAX_DICTIONARY_KIB + 1)]:
            state = rar._State()
            self.assertEqual(state.callback(message, 0, pointer, 0), -1)
            self.assertTrue(state.error)
        state = rar._State()
        state.deadline = time.monotonic() - 1
        self.assertEqual(state.callback(1, 0, 0, 0), -1)
        self.assertIn("времени", state.error)


if __name__ == "__main__":
    unittest.main()
