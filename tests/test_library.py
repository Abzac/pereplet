"""Isolated parser/storage regression tests; never touch the user's real library."""
from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import library
from backend.parsers import BookParseError, anchor

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==")


def fb2(body="<p>Первый <emphasis>абзац</emphasis>. Привет, мир!</p>", encoding="utf-8"):
    return (f'''<?xml version="1.0" encoding="{encoding}"?>
    <FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
    <description><title-info><genre>sf</genre><author><first-name>Антон</first-name><last-name>Чехов</last-name></author>
    <book-title>Тестовая книга</book-title><annotation><p>Описание книги.</p></annotation><lang>ru</lang>
    <sequence name="Собрание" number="2"/><coverpage><image l:href="#cover"/></coverpage></title-info></description>
    <body><section id="start"><title><p>Глава первая</p></title>{body}</section></body>
    <binary id="cover" content-type="image/png">{base64.b64encode(PNG).decode()}</binary></FictionBook>''').encode(encoding)


def epub(path, body=None):
    body = body or '<h1 id="first">Начало</h1><p>Текст <em>книги</em>. <a href="two.xhtml#note">Сноска</a></p><img src="cover.png"/><script>alert(1)</script><p onclick="alert(2)"><a href="javascript:evil()">Безопасно</a></p>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
        z.writestr("OPS/book.opf", '''<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>EPUB пример</dc:title><dc:creator>Мария Автор</dc:creator><dc:language>ru</dc:language><meta name="cover" content="cover"/></metadata><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/><item id="two" href="two.xhtml" media-type="application/xhtml+xml"/><item id="cover" href="cover.png" media-type="image/png"/></manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>''')
        z.writestr("OPS/one.xhtml", f'<html><head><style>body{{color:red}}</style></head><body>{body}</body></html>')
        z.writestr("OPS/two.xhtml", '<html><body><p id="note">Текст примечания.</p></body></html>')
        z.writestr("OPS/cover.png", PNG)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pereplet-test-")
        self.root = Path(self.temp.name)
        self.previous = library.DATA_DIR
        library.DATA_DIR = self.root / "data"

    def tearDown(self):
        library.DATA_DIR = self.previous
        self.temp.cleanup()

    def write(self, name, data):
        p = self.root / name
        p.write_bytes(data)
        return p

    def test_fb2_zip_metadata_duplicate_and_saved_reading(self):
        source = self.root / "book.fb2.zip"
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("books/book.fb2", fb2())
        imported = library.import_path(source)
        book = imported["book"]
        self.assertFalse(imported["duplicate"])
        self.assertEqual(book["title"], "Тестовая книга")
        self.assertEqual(book["authors"], ["Антон Чехов"])
        self.assertEqual(book["format"], "FB2.zip")
        self.assertEqual(book["series"], "Собрание")
        self.assertEqual(book["series_index"], "2")
        self.assertTrue(book["cover_url"])
        chapter = library.get_chapter(book["id"], 0)
        self.assertIn("<em>абзац</em>", chapter["html"])
        self.assertIn("Первый абзац.", " ".join(p["text"] for p in chapter["paragraphs"]))
        self.assertEqual(book["anchors"][anchor("start")], 0)
        library.update_book(book["id"], {"progress": 42.5, "status": "reading", "locator": {"paragraph": "p-0000002"}, "reading_settings": {"font": "Georgia"}})
        repeated = library.import_path(source)
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(repeated["book"]["progress"], 42.5)
        self.assertEqual(len(library.list_books()), 1)
        self.assertEqual(source.read_bytes(), (library.DATA_DIR / "books" / book["id"] / "original.fb2.zip").read_bytes())

    def test_windows1251_fb2(self):
        p = self.write("1251.fb2", fb2(encoding="windows-1251"))
        book = library.import_path(p)["book"]
        self.assertEqual(book["title"], "Тестовая книга")
        self.assertIn("Привет, мир!", library.get_chapter(book["id"], 0)["html"])

    def test_epub_sanitized_links_images_and_anchors(self):
        p = self.root / "book.epub"
        epub(p)
        book = library.import_path(p)["book"]
        self.assertEqual(book["title"], "EPUB пример")
        self.assertEqual(book["authors"], ["Мария Автор"])
        self.assertEqual(book["chapter_count"], 2)
        text = library.get_chapter(book["id"], 0)["html"]
        for forbidden in ("<script", "alert(", "onclick", "javascript:", "<style", "color:red"):
            self.assertNotIn(forbidden, text)
        self.assertIn("/resources/images/", text)
        self.assertIn("#" + anchor("OPS/two.xhtml#note"), text)
        self.assertEqual(book["anchors"][anchor("OPS/two.xhtml#note")], 1)
        resource = book["cover_url"].split("/resources/", 1)[1]
        path, kind = library.resource_path(book["id"], resource)
        self.assertTrue(path.is_file())
        self.assertTrue(kind.startswith("image/"))
        with self.assertRaises(KeyError):
            library.resource_path(book["id"], "../original.epub")

    def test_unsafe_archives_entities_and_cleanup(self):
        p = self.root / "bad.fb2.zip"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("../book.fb2", fb2())
        with self.assertRaises(BookParseError):
            library.import_path(p)
        evil = self.write("entity.fb2", b'<!DOCTYPE FictionBook [<!ENTITY x "unsafe">]><FictionBook><body><p>&x;</p></body></FictionBook>')
        with self.assertRaises(BookParseError):
            library.import_path(evil)
        self.assertEqual(library.list_books(), [])
        self.assertEqual(list((library.DATA_DIR / "books").iterdir()), [])

    def test_large_chapters_keep_text_and_are_bounded(self):
        paragraphs = "".join(f"<p>Строка {n}: " + ("Текст с подробностями. " * 20) + "</p>" for n in range(2000))
        p = self.write("large.fb2", fb2(paragraphs))
        book = library.import_path(p)["book"]
        self.assertGreater(book["chapter_count"], 10)
        chapters = [library.get_chapter(book["id"], n) for n in range(book["chapter_count"])]
        text = " ".join(p["text"] for c in chapters for p in c["paragraphs"])
        for n in range(2000):
            self.assertEqual(text.count(f"Строка {n}:"), 1)
        self.assertLess(max(len(c["html"]) for c in chapters), 110_000)
        ids = [p["id"] for c in chapters for p in c["paragraphs"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_giant_single_paragraph_is_split_without_loss(self):
        body = "АБВГД " * 100_000
        p = self.write("giant.fb2", fb2("<p>" + body + "</p>"))
        book = library.import_path(p)["book"]
        chapters = [library.get_chapter(book["id"], n) for n in range(book["chapter_count"])]
        collected = "".join(p["text"] for c in chapters for p in c["paragraphs"])
        self.assertEqual(collected.replace(" ", "").count("АБВГД"), 100_000)
        self.assertLess(max(len(c["html"]) for c in chapters), 110_000)

    def test_settings_catalogs_and_delete_preserve_source(self):
        source = self.write("book.fb2", fb2())
        book = library.import_path(source)["book"]
        library.save_settings({"theme": "navy"})
        library.save_settings({"fontSize": 22})
        self.assertEqual(library.get_settings(), {"theme": "navy", "fontSize": 22})
        c = library.add_catalog({"name": "Каталог", "url": "https://example.org/opds"})
        self.assertEqual(len(library.list_catalogs()), 1)
        library.delete_catalog(c["id"])
        self.assertEqual(library.list_catalogs(), [])
        library.delete_book(book["id"])
        self.assertTrue(source.is_file())
        self.assertEqual(library.list_books(), [])

    def test_api_import_state_and_resource_contract(self):
        from fastapi.testclient import TestClient
        from backend.server import app, PORT
        with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as client:
            token = client.get("/api/session").json()["token"]
            headers = {"X-Pereplet": "1", "X-Pereplet-Token": token}
            result = client.post("/api/import", files=[("files", ("example.fb2", fb2(), "application/xml"))], headers=headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["errors"], [])
            book = result.json()["imported"][0]
            self.assertEqual(len(client.get("/api/books").json()), 1)
            detail = client.get(f'/api/books/{book["id"]}').json()
            self.assertTrue(detail["chapters"])
            ch = client.get(f'/api/books/{book["id"]}/chapters/0')
            self.assertTrue(ch.json()["paragraphs"])
            cover = client.get(book["cover_url"])
            self.assertEqual(cover.status_code, 200)
            self.assertIn("image/", cover.headers["content-type"])
            self.assertIn("sandbox", cover.headers["content-security-policy"])
            state = client.patch(f'/api/books/{book["id"]}', json={"progress": 18, "chapter": 0, "status": "reading"}, headers=headers)
            self.assertEqual(state.json()["progress"], 18)

    def test_api_rejects_foreign_origin_host_and_missing_token(self):
        from fastapi.testclient import TestClient
        from backend.server import app, PORT
        with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as client:
            self.assertEqual(client.get("/api/health").status_code, 200)
            self.assertEqual(client.put("/api/settings", json={"theme": "navy"}, headers={"X-Pereplet": "1"}).status_code, 403)
            self.assertEqual(client.get("/api/session", headers={"Origin": "https://evil.example"}).status_code, 403)
            self.assertEqual(client.get("/api/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
            self.assertEqual(client.get("/api/books", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
            self.assertEqual(client.get("/api/books", headers={"Host": "evil.example:8765"}).status_code, 403)
            self.assertEqual(client.get("/api/books", headers={"Host": "localhost:9999"}).status_code, 403)
            self.assertEqual(library.get_settings(), {})

    def test_seed_once_and_deleted_demos_stay_deleted(self):
        from seed_demo import seed
        from backend.catalog_defaults import load_manifest, canonical_catalog_url
        from PIL import Image
        seeded = seed()
        self.assertTrue(seeded["seeded"])
        books = library.list_books()
        self.assertEqual(len(books), 3)
        self.assertEqual({b["format"] for b in books}, {"FB2", "FB2.zip", "EPUB"})
        self.assertTrue(all("Демо" in b["author"] or "Руководство" in b["author"] for b in books))
        self.assertTrue(all(b.get("cover_kind") == "template" for b in books))
        self.assertTrue(all(b["chapter_count"] >= 3 for b in books))
        catalogs = library.list_catalogs()
        default_catalogs = load_manifest()["catalogs"]
        self.assertEqual(len(catalogs), 4)
        self.assertEqual({canonical_catalog_url(c["url"]) for c in catalogs},
                         {canonical_catalog_url(c["url"]) for c in default_catalogs})
        self.assertFalse(any("wolnelektury.pl" in c["url"] for c in catalogs))
        epub_book = next(b for b in books if b["format"] == "EPUB")
        resource_dir = library.DATA_DIR / "books" / epub_book["id"] / "resources" / "images"
        found_transparency = False
        for path in resource_dir.iterdir():
            with Image.open(path) as image:
                if image.mode == "RGBA" and image.size == (720, 320):
                    self.assertEqual(image.getpixel((0, 0))[3], 0)
                    self.assertGreater(image.getpixel((300, 150))[3], 0)
                    found_transparency = True
        self.assertTrue(found_transparency)
        for book in books:
            library.delete_book(book["id"])
        for catalog in catalogs:
            library.delete_catalog(catalog["id"])
        self.assertFalse(seed()["seeded"])
        self.assertEqual(library.list_books(), [])
        self.assertEqual(library.list_catalogs(), [])

    def test_demo_cover_migration_preserves_state_and_other_books(self):
        from seed_demo import seed, mark_demo_covers
        seed()
        book = library.list_books()[0]
        other = library.import_path(self.write("personal.fb2", fb2()))["book"]
        expected = library.update_book(book["id"], {"progress": 34, "chapter": 1, "status": "reading", "locator": {"id": "p-0000001"}, "reading_settings": {"font": "Georgia"}, "bookmarks": [{"title": "Test"}]})
        marker = library.DATA_DIR / "demo-seeded-v1.json"
        state = json.loads(marker.read_text(encoding="utf-8"))
        state.pop("cover_template_version")
        marker.write_text(json.dumps(state), encoding="utf-8")
        with library.connect() as db:
            row = db.execute("SELECT metadata FROM books WHERE id=?", (book["id"],)).fetchone()
            meta = json.loads(row["metadata"])
            meta.pop("cover_kind")
            db.execute("UPDATE books SET metadata=? WHERE id=?", (json.dumps(meta), book["id"]))
        self.assertEqual(mark_demo_covers()["updated"], 1)
        self.assertEqual(library.get_book(book["id"]), expected)
        self.assertNotIn("cover_kind", library.get_book(other["id"]))
        self.assertEqual(mark_demo_covers()["updated"], 0)

    def test_static_javascript_and_fonts_have_explicit_mime(self):
        from fastapi.testclient import TestClient
        from backend import server
        previous = server.FRONTEND
        server.FRONTEND = self.root / "dist"
        server.FRONTEND.mkdir()
        (server.FRONTEND / "app.js").write_text("export const ok = true;", encoding="utf-8")
        (server.FRONTEND / "index.html").write_text("<!doctype html><title>Test</title>", encoding="utf-8")
        (server.FRONTEND / "font.ttf").write_bytes(b"fixture")
        try:
            with TestClient(server.app, base_url=f"http://127.0.0.1:{server.PORT}") as client:
                self.assertIn("application/javascript", client.get("/app.js").headers["content-type"])
                self.assertIn("font/ttf", client.get("/font.ttf").headers["content-type"])
                self.assertIn("text/html", client.get("/").headers["content-type"])
        finally:
            server.FRONTEND = previous


if __name__ == "__main__":
    unittest.main()
