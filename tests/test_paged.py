"""PDF/CBZ regression checks using disposable originals, never real library data."""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import library, paged
from backend.parsers import BookParseError


def pdf_bytes(pages=3, size=(300, 500)):
    """Tiny genuine PDF with distinct colored rectangles and Unicode metadata."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    page_ids = []
    for index in range(pages):
        page_id = len(objects) + 1
        page_ids.append(page_id)
        objects.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {size[0]} {size[1]}] "
                        f"/Resources << >> /Contents {page_id + 1} 0 R >>").encode())
        colors = ("1 0 0", "0 1 0", "0 0 1")
        content = f"{colors[index % 3]} rg 20 20 100 50 re f".encode()
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    kids = " ".join(f"{item} 0 R" for item in page_ids)
    objects[1] = f"<< /Type /Pages /Count {pages} /Kids [{kids}] >>".encode()
    title = (b"\xfe\xff" + "Тестовый PDF".encode("utf-16-be")).hex()
    author = (b"\xfe\xff" + "Тестовый автор".encode("utf-16-be")).hex()
    objects.append(f"<< /Title <{title}> /Author <{author}> /Subject (PDF fixture) >>".encode())
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend((f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {len(objects)} 0 R >>\n"
                 f"startxref\n{start}\n%%EOF\n").encode())
    return bytes(data)


def png(color, size=(20, 30)):
    with Image.new("RGBA", size, color) as image:
        output = io.BytesIO()
        image.save(output, "PNG")
        return output.getvalue()


class PagedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pereplet-pages-test-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def pdf(self, pages=3, size=(300, 500)):
        source = self.root / "original.pdf"
        source.write_bytes(pdf_bytes(pages, size))
        return source

    def cbz(self, entries):
        source = self.root / "original.cbz"
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries:
                # Bypass ZipInfo's Windows slash normalization to exercise
                # the actual untrusted member names seen by the parser.
                info = zipfile.ZipInfo()
                info.filename = name
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
        return source

    def prepare(self, source):
        return paged.prepare_paged(source, "Книга" + source.suffix, self.root, "a" * 32)

    def test_pdf_metadata_cover_and_lazy_render_keep_original_intact(self):
        source = self.pdf()
        digest = hashlib.sha256(source.read_bytes()).digest()
        with patch.object(paged, "_pdf_image", wraps=paged._pdf_image) as render:
            meta = self.prepare(source)
            self.assertEqual(render.call_count, 1)
            self.assertEqual(render.call_args.args[1], 0)
        self.assertEqual(meta["title"], "Тестовый PDF")
        self.assertEqual(meta["authors"], ["Тестовый автор"])
        self.assertEqual(meta["reader_type"], "pages")
        self.assertEqual(meta["page_count"], 3)
        self.assertEqual([item["index"] for item in meta["chapters"]], [0, 1, 2])
        self.assertTrue((self.root / "resources" / meta["cover_resource"]).is_file())
        self.assertFalse((self.root / "pages").exists())
        rendered = paged.render_page(self.root, meta, 1, 800)
        with Image.open(rendered) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.width, 800)
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
            self.assertEqual(image.getpixel((100, image.height - 100)), (0, 255, 0))
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), digest)
        self.assertEqual(len(list((self.root / "pages").glob("*.png"))), 1)

    def test_cache_reuses_normalized_width_and_bounds_files(self):
        meta = self.prepare(self.pdf())
        first = paged.render_page(self.root, meta, 0, 1000)
        with patch.object(paged, "_pdf_image", side_effect=AssertionError("cache should be used")):
            self.assertEqual(paged.render_page(self.root, meta, 0, 1200), first)
        with patch.object(paged, "MAX_CACHE_FILES", 2):
            second = paged.render_page(self.root, meta, 1, 800)
            paged.render_page(self.root, meta, 0, 1000)  # keep page zero recent
            third = paged.render_page(self.root, meta, 2, 800)
            self.assertTrue(first.exists())
            self.assertFalse(second.exists())
            self.assertTrue(third.exists())
            self.assertEqual(len(list((self.root / "pages").glob("*.png"))), 2)

    def test_cache_bounds_bytes_and_has_no_partial_files(self):
        meta = self.prepare(self.pdf())
        first = paged.render_page(self.root, meta, 0, 480)
        with patch.object(paged, "MAX_CACHE_BYTES", first.stat().st_size + 10):
            second = paged.render_page(self.root, meta, 1, 480)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertFalse(list((self.root / "pages").glob("*.tmp")))

    def test_cbz_natural_order_metadata_and_white_transparency(self):
        source = self.cbz([
            ("10.png", png("blue")), ("2.png", png("red")),
            ("1.png", png((0, 0, 0, 0))), ("__MACOSX/._1.png", b"ignored"),
            ("ComicInfo.xml", "<ComicInfo><Title>Комикс</Title><Writer>Автор один, Автор два</Writer>"
             "<Series>Цикл</Series><Number>3</Number><LanguageISO>ru</LanguageISO></ComicInfo>"),
        ])
        meta = self.prepare(source)
        self.assertEqual(meta["page_count"], 3)
        self.assertEqual(meta["title"], "Комикс")
        self.assertEqual(meta["authors"], ["Автор один", "Автор два"])
        self.assertEqual((meta["series"], meta["series_index"]), ("Цикл", "3"))
        manifest = json.loads((self.root / paged.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(manifest["entries"], ["1.png", "2.png", "10.png"])
        for index, expected in [(0, (255, 255, 255)), (1, (255, 0, 0)), (2, (0, 0, 255))]:
            with Image.open(paged.render_page(self.root, meta, index)) as image:
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.getpixel((0, 0)), expected)
                self.assertEqual(image.size, (20, 30))  # no invented resolution
        self.assertFalse((self.root / "1.png").exists())

    def test_cbz_import_does_not_decode_other_pages(self):
        meta = self.prepare(self.cbz([("1.png", png("red")), ("2.png", b"not an image")]))
        self.assertEqual(meta["page_count"], 2)
        with self.assertRaisesRegex(BookParseError, "прочитать страницу"):
            paged.render_page(self.root, meta, 1)

    def test_unsafe_zip_paths_and_duplicate_names_are_rejected(self):
        for name in ("../escape.png", "/absolute.png", "C:/absolute.png", "folder\\escape.png"):
            with self.subTest(name=name):
                with self.assertRaises(BookParseError):
                    self.prepare(self.cbz([(name, png("red"))]))
        with self.assertRaisesRegex(BookParseError, "повторяющиеся"):
            self.prepare(self.cbz([("page.png", png("red")), ("PAGE.png", png("blue"))]))

    def test_no_image_or_oversized_cbz_rejected(self):
        with self.assertRaises(BookParseError):
            self.prepare(self.cbz([("readme.txt", "text")]))
        with patch.object(paged, "MAX_IMAGE_BYTES", 10):
            with self.assertRaisesRegex(BookParseError, "128 МБ"):
                self.prepare(self.cbz([("1.png", png("red"))]))
        with patch.object(paged, "MAX_IMAGE_PIXELS", 100):
            with self.assertRaisesRegex(BookParseError, "мегапикселей"):
                self.prepare(self.cbz([("1.png", png("red"))]))

    def test_page_index_manifest_and_original_paths_are_checked(self):
        meta = self.prepare(self.pdf())
        for index in (-1, 3, True, "1"):
            with self.subTest(index=index), self.assertRaises(KeyError):
                paged.render_page(self.root, meta, index)
        for name in ("../original.pdf", "sub/original.pdf", "C:\\test.pdf", ".."):
            with self.subTest(name=name), self.assertRaises(BookParseError):
                paged.render_page(self.root, {**meta, "original_file": name}, 0)
        (self.root / paged.MANIFEST).write_text('{"version":1,"format":"PDF","count":999}', encoding="utf-8")
        with self.assertRaisesRegex(BookParseError, "список страниц"):
            paged.render_page(self.root, meta, 0)

    def test_invalid_pdf_and_empty_page_tree_report_friendly_errors(self):
        source = self.root / "original.pdf"
        source.write_bytes(b"This is not a PDF")
        with self.assertRaisesRegex(BookParseError, "PDF"):
            self.prepare(source)
        with self.assertRaises(BookParseError):
            self.prepare(self.pdf(pages=0))

    def test_render_dimensions_and_width_buckets_are_bounded(self):
        meta = self.prepare(self.pdf(size=(100, 10000)))
        output = paged.render_page(self.root, meta, 0, 999999)
        self.assertIn("w2400", output.name)
        with Image.open(output) as image:
            self.assertLessEqual(max(image.size), paged.MAX_RENDER_SIDE)
            self.assertLessEqual(image.width * image.height, paged.MAX_RENDER_PIXELS)
        self.assertIn("w480", paged.render_page(self.root, meta, 0, -100).name)

    def test_parallel_requests_share_one_render(self):
        meta = self.prepare(self.cbz([("1.png", png("red"))]))
        with patch.object(paged, "_comic_image", wraps=paged._comic_image) as render:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: paged.render_page(self.root, meta, 0, 800), range(4)))
            self.assertEqual(render.call_count, 1)
            self.assertEqual(len(set(results)), 1)

    def test_library_pdf_cbz_import_duplicate_page_and_saved_position(self):
        pdf = self.pdf()
        cbz = self.cbz([("1.png", png("red")), ("2.png", png("blue"))])
        with patch.object(library, "DATA_DIR", self.root / "isolated-data"):
            for source, expected_format in [(pdf, "PDF"), (cbz, "CBZ")]:
                with self.subTest(format=expected_format):
                    imported = library.import_path(source)
                    book = imported["book"]
                    self.assertFalse(imported["duplicate"])
                    self.assertEqual(book["format"], expected_format)
                    self.assertEqual(book["reader_type"], "pages")
                    self.assertEqual(book["chapter_count"], book["page_count"])
                    self.assertTrue(book["cover_url"].endswith("cover.jpg"))
                    page = library.get_page(book["id"], 1, 800)
                    self.assertTrue(page.is_file())
                    with Image.open(page) as image:
                        self.assertEqual(image.mode, "RGB")
                    library.update_book(book["id"], {"chapter": 1, "progress": 50, "locator": {"page": 1}})
                    repeat = library.import_path(source)
                    self.assertTrue(repeat["duplicate"])
                    self.assertEqual(repeat["book"]["chapter"], 1)
                    original = library.DATA_DIR / "books" / book["id"] / ("original" + source.suffix)
                    self.assertEqual(source.read_bytes(), original.read_bytes())

    def test_failed_pdf_library_import_cleans_derived_directory(self):
        source = self.root / "invalid.pdf"
        source.write_bytes(b"broken pdf")
        with patch.object(library, "DATA_DIR", self.root / "isolated-data"):
            with self.assertRaises(BookParseError):
                library.import_path(source)
            self.assertEqual(list((library.DATA_DIR / "books").iterdir()), [])
            self.assertTrue(source.is_file())


if __name__ == "__main__":
    unittest.main()
