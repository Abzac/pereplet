"""User-assigned series update catalogue metadata only, never the imported source."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from backend import library, server


@pytest.fixture
def stored_book(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path / "library")
    source = tmp_path / "book.fb2"
    source.write_text('<FictionBook><description><title-info><book-title>Series test</book-title><sequence name="Old series" number="2.5"/></title-info></description><body><section><p>Text.</p></section></body></FictionBook>', encoding="utf-8")
    book = library.import_path(source)["book"]
    book = library.update_book(book["id"], {"progress": 27, "status": "reading", "locator": {"id": "p1"}, "last_opened": True})
    return book, source


def test_assign_series_preserves_book_and_source(stored_book):
    book, source = stored_book
    original = library.DATA_DIR / "books" / book["id"] / "original.fb2"
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    with library.connect() as db:
        metadata = json.loads(db.execute("SELECT metadata FROM books WHERE id=?", (book["id"],)).fetchone()[0])
    changed = library.update_book(book["id"], {"series": "  New series  ", "media_type": "comic"})
    assert changed["series"] == "New series" and changed["series_index"] is None
    assert changed["media_type"] == "comic"
    for field in ("title", "progress", "status", "locator", "last_opened", "chapters", "anchors"):
        assert changed[field] == book[field]
    with library.connect() as db:
        after = json.loads(db.execute("SELECT metadata FROM books WHERE id=?", (book["id"],)).fetchone()[0])
    for field, value in metadata.items():
        if field not in {"series", "series_index", "media_type"}:
            assert after[field] == value
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    assert original.read_bytes() == source.read_bytes()
    assert library.list_books()[0]["series"] == "New series"


def test_same_series_keeps_number_and_empty_removes_it(stored_book):
    book, _ = stored_book
    same = library.update_book(book["id"], {"series": "Old series"})
    assert same["series_index"] == "2.5"
    zero = library.update_book(book["id"], {"series_index": 0})
    assert zero["series_index"] == 0
    fraction = library.update_book(book["id"], {"series_index": 2.5})
    assert fraction["series_index"] == 2.5
    cleared = library.update_book(book["id"], {"series_index": None})
    assert cleared["series_index"] is None and cleared["series"] == "Old series"
    renamed = library.update_book(book["id"], {"series": "New", "series_index": 10})
    assert renamed["series_index"] == 10
    removed = library.update_book(book["id"], {"series": "  "})
    assert removed["series"] == "" and removed["series_index"] is None
    with pytest.raises(ValueError, match="Сначала"):
        library.update_book(book["id"], {"series_index": 1})


@pytest.mark.parametrize("patch", [
    {"series": None}, {"series": 12}, {"series": ["Bad"]}, {"series": "a" * 301}, {"series": "Bad\nName"},
    {"series_index": "2"}, {"series_index": True}, {"series_index": -1}, {"series_index": float("nan")},
    {"series_index": float("inf")}, {"series_index": 10**400}, {"series": "", "series_index": 1},
])
def test_bad_series_patch_is_atomic(stored_book, patch):
    book, _ = stored_book
    with pytest.raises(ValueError):
        library.update_book(book["id"], {"progress": 70, "media_type": "comic", **patch})
    assert library.get_book(book["id"]) == book


def test_series_patch_api(stored_book):
    book, _ = stored_book
    headers = {"X-Pereplet": "1", "X-Pereplet-Token": server.SESSION_TOKEN}
    with TestClient(server.app, base_url="http://127.0.0.1:18765") as client:
        result = client.patch(f'/api/books/{book["id"]}', headers=headers, json={"series": "Комиксы", "series_index": 3})
        assert result.status_code == 200
        assert result.json()["series"] == "Комиксы" and result.json()["series_index"] == 3
        invalid = client.patch(f'/api/books/{book["id"]}', headers=headers, json={"series_index": "guess"})
        assert invalid.status_code == 422
        assert client.get(f'/api/books/{book["id"]}').json()["series_index"] == 3
