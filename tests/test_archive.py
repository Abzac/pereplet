"""Archiving is reversible library metadata, not deletion or a reading status."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from backend import library, server


@pytest.fixture
def stored_book(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path / "library")
    source = tmp_path / "book.fb2"
    source.write_text('<FictionBook><description><title-info><book-title>Archive test</book-title><sequence name="Series" number="2.5"/></title-info></description><body><section><p>Text.</p></section></body></FictionBook>', encoding="utf-8")
    book = library.import_path(source)["book"]
    book = library.update_book(book["id"], {
        "progress": 27, "status": "reading", "locator": {"id": "p1", "ratio": 0.27},
        "last_opened": True, "bookmarks": [{"chapter": 0, "title": "Here"}],
        "reading_settings": {"useGlobalAppearance": False, "appearance": {"fontSize": 28}},
    })
    return book, source


@pytest.mark.parametrize("status", sorted(library.STATUSES))
@pytest.mark.parametrize("media_type", ["book", "comic"])
def test_archive_restore_preserves_reading_state_and_original(stored_book, status, media_type):
    book, source = stored_book
    book = library.update_book(book["id"], {"status": status, "media_type": media_type})
    original = library.DATA_DIR / "books" / book["id"] / "original.fb2"
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    assert book["archived"] is False
    archived = library.update_book(book["id"], {"archived": True})
    assert archived == {**book, "archived": True}
    assert next(item for item in library.list_books() if item["id"] == book["id"])["archived"] is True
    restored = library.update_book(book["id"], {"archived": False})
    assert restored == book
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    assert original.read_bytes() == source.read_bytes()


def test_archive_combines_with_media_and_series_without_overwriting_metadata(stored_book):
    book, _ = stored_book
    changed = library.update_book(book["id"], {"archived": True, "media_type": "comic", "series": "New", "series_index": 0})
    assert changed["archived"] is True
    assert changed["media_type"] == "comic" and changed["series"] == "New" and changed["series_index"] == 0
    for field in ("progress", "status", "locator", "reading_settings", "bookmarks", "last_opened", "chapters"):
        assert changed[field] == book[field]
    progressed = library.update_book(book["id"], {"progress": 40, "status": "reading"})
    assert progressed["archived"] is True and progressed["series_index"] == 0
    reclassified = library.update_book(book["id"], {"media_type": "book", "series": "Another"})
    assert reclassified["archived"] is True and reclassified["progress"] == 40
    restored = library.update_book(book["id"], {"archived": False})
    assert restored["media_type"] == "book" and restored["series"] == "Another" and restored["progress"] == 40


@pytest.mark.parametrize("invalid", [None, 0, 1, "true", "false", [], {}])
def test_archive_boolean_is_strict_and_invalid_patch_atomic(stored_book, invalid):
    book, _ = stored_book
    with pytest.raises(ValueError, match="true или false"):
        library.update_book(book["id"], {"archived": invalid, "media_type": "comic", "progress": 60})
    assert library.get_book(book["id"]) == book


def test_duplicate_import_keeps_archived_record_and_all_files(stored_book):
    book, source = stored_book
    archived = library.update_book(book["id"], {"archived": True})
    result = library.import_path(source)
    assert result["duplicate"] is True and result["book"] == archived
    assert len(library.list_books()) == 1
    assert (library.DATA_DIR / "books" / book["id"] / "original.fb2").is_file()


def test_legacy_metadata_defaults_to_not_archived(stored_book):
    book, _ = stored_book
    with library.connect() as db:
        metadata = json.loads(db.execute("SELECT metadata FROM books WHERE id=?", (book["id"],)).fetchone()[0])
        assert "archived" not in metadata
    assert library.get_book(book["id"])["archived"] is False


def test_archive_api_round_trip_and_validation(stored_book):
    book, _ = stored_book
    headers = {"X-Pereplet": "1", "X-Pereplet-Token": server.SESSION_TOKEN}
    with TestClient(server.app, base_url="http://127.0.0.1:18765") as client:
        result = client.patch(f'/api/books/{book["id"]}', headers=headers, json={"archived": True})
        assert result.status_code == 200 and result.json()["archived"] is True
        invalid = client.patch(f'/api/books/{book["id"]}', headers=headers, json={"archived": "false", "series": "Wrong"})
        assert invalid.status_code == 422
        current = client.get(f'/api/books/{book["id"]}').json()
        assert current["archived"] is True and current["series"] == book["series"]
        restored = client.patch(f'/api/books/{book["id"]}', headers=headers, json={"archived": False})
        assert restored.status_code == 200 and restored.json() == book
