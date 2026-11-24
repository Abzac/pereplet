"""Reading intent/completion is separate from a saved page or percentage."""

import pytest

from backend import library


@pytest.fixture
def status_book(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path / "library")
    source = tmp_path / "status.fb2"
    source.write_text(
        '<FictionBook><description><title-info><book-title>Status test</book-title>'
        '<sequence name="Series" number="2.5"/></title-info></description>'
        '<body><section><p>First paragraph.</p><p>Second paragraph.</p>'
        '</section></body></FictionBook>',
        encoding="utf-8",
    )
    imported = library.import_path(source)["book"]
    return library.update_book(imported["id"], {
        "status": "reading", "progress": 42,
        "locator": {"id": "p1", "ratio": 0.42},
        "last_opened": True,
        "bookmarks": [{"chapter": 0, "title": "Saved place"}],
        "reading_settings": {"useGlobalAppearance": False, "appearance": {"fontSize": 28}},
    })


@pytest.mark.parametrize("previous,normalized", [
    ("unread", "unread"), ("reading", "reading"), ("read", "read"), ("finished", "read"),
])
@pytest.mark.parametrize("queued", ["planned", "want"])
def test_planned_queue_remembers_the_prior_status_and_survives_repeat_updates(status_book, previous, normalized, queued):
    book_id = status_book["id"]
    library.update_book(book_id, {"status": previous})
    queued_book = library.update_book(book_id, {"status": queued})
    assert queued_book["planned_previous_status"] == normalized
    # Repeating a click, switching a legacy alias, or editing series must not
    # replace the pre-queue status with 'planned'.
    for patch in ({"status": queued}, {"status": "want" if queued == "planned" else "planned"}, {"series": "Another series"}):
        changed = library.update_book(book_id, patch)
        assert changed["planned_previous_status"] == normalized
    assert library.get_book(book_id)["planned_previous_status"] == normalized
    assert library.list_books()[0]["planned_previous_status"] == normalized
    restored = library.update_book(book_id, {"status": normalized})
    assert restored["status"] == normalized
    assert "planned_previous_status" not in restored


@pytest.mark.parametrize("following", ["unread", "reading", "read", "finished"])
def test_any_explicit_exit_from_the_queue_clears_its_return_status(status_book, following):
    book_id = status_book["id"]
    library.update_book(book_id, {"status": "planned"})
    changed = library.update_book(book_id, {"status": following})
    assert changed["status"] == following
    assert "planned_previous_status" not in changed
    assert "planned_previous_status" not in library.get_book(book_id)


@pytest.mark.parametrize("status", sorted(library.STATUSES))
def test_status_changes_preserve_exact_reading_position_and_preferences(status_book, status):
    changed = library.update_book(status_book["id"], {"status": status})
    assert changed["status"] == status
    for field in ("progress", "chapter", "locator", "reading_settings", "bookmarks", "last_opened", "chapters"):
        assert changed[field] == status_book[field], field


def test_page_at_one_hundred_percent_does_not_complete_reading(status_book):
    book_id = status_book["id"]
    end = {"id": "p2", "ratio": 1}
    jumped = library.update_book(book_id, {"progress": 100, "locator": end})
    assert jumped["status"] == "reading"
    assert jumped["progress"] == 100 and jumped["locator"] == end
    queued = library.update_book(book_id, {"status": "planned"})
    assert queued["planned_previous_status"] == "reading"
    returned = library.update_book(book_id, {"status": queued["planned_previous_status"]})
    assert returned["status"] == "reading" and returned["progress"] == 100


@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize("invalid", ["not-a-status", "", None])
def test_invalid_status_keeps_combined_metadata_and_reading_patch_atomic(status_book, queued, invalid):
    book_id = status_book["id"]
    original = library.update_book(book_id, {"status": "planned"}) if queued else status_book
    with pytest.raises(ValueError, match="Неизвестный статус"):
        library.update_book(book_id, {
            "status": invalid, "archived": True, "media_type": "comic",
            "series": "Must not be saved", "series_index": 9,
            "progress": 90, "locator": {"id": "elsewhere", "ratio": 0.9},
            "bookmarks": [], "reading_settings": {},
        })
    assert library.get_book(book_id) == original


def test_invalid_series_does_not_leave_a_partial_queue_transition(status_book):
    with pytest.raises(ValueError, match="Название серии"):
        library.update_book(status_book["id"], {"status": "planned", "series": "Invalid\nseries"})
    assert library.get_book(status_book["id"]) == status_book
