from backend import library


def test_last_opened_changes_only_on_explicit_open(tmp_path, monkeypatch):
    monkeypatch.setattr(library, 'DATA_DIR', tmp_path / 'data')
    source = tmp_path / 'book.fb2'
    source.write_text('<FictionBook><description><title-info><book-title>Recent</book-title></title-info></description><body><section><p>Text.</p></section></body></FictionBook>')
    book = library.import_path(source)['book']
    assert book['last_opened'] is None
    monkeypatch.setattr(library, 'now', lambda: '2026-01-01T00:00:00Z')
    opened = library.update_book(book['id'], {'last_opened': True})
    assert opened['last_opened'] == '2026-01-01T00:00:00Z'
    monkeypatch.setattr(library, 'now', lambda: '2026-02-01T00:00:00Z')
    changed = library.update_book(book['id'], {'progress': 100, 'status': 'read', 'chapter': 0, 'locator': {'id':'p1'}, 'media_type': 'comic'})
    assert changed['last_opened'] == opened['last_opened']
    reopened = library.update_book(book['id'], {'last_opened': True})
    assert reopened['last_opened'] == '2026-02-01T00:00:00Z'
    assert reopened['progress'] == 100 and reopened['locator'] == {'id':'p1'}
