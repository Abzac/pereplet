"""Footnotes read one derived chapter and never rewrite the user's imported books."""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import library, parsers, server
from backend.parsers import anchor, extract_note


@pytest.fixture
def local_library(monkeypatch, tmp_path):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path / "data")
    return tmp_path


def import_fb2(root, count=100):
    notes = ''.join(f'<section id="note-{i}"><title><p>{i}</p></title><p>Пояснение номер {i}: <emphasis>важная деталь</emphasis>.</p><p>Продолжение сноски {i}.</p></section>' for i in range(1, count + 1))
    source = root / "notes.fb2"
    source.write_text(f'''<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
      <description><title-info><book-title>Сноски</book-title></title-info></description>
      <body><section id="main"><title><p>Глава</p></title><p>Основной текст<a type="note" l:href="#note-1">[1]</a>.</p></section></body>
      <body name="notes"><section id="all-notes">{notes}</section></body>
    </FictionBook>''', encoding="utf-8")
    return library.import_path(source)["book"]


def import_epub(root, first, notes):
    source = root / "notes.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
        archive.writestr("OPS/book.opf", '''<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>EPUB notes</dc:title></metadata><manifest><item id="main" href="main.xhtml" media-type="application/xhtml+xml"/><item id="notes" href="notes.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="main"/><itemref idref="notes"/></spine></package>''')
        archive.writestr("OPS/main.xhtml", f'<html><body>{first}</body></html>')
        archive.writestr("OPS/notes.xhtml", f'<html><body>{notes}</body></html>')
    return library.import_path(source)["book"]


def test_fb2_one_of_one_hundred_notes_and_existing_import_heuristics(local_library):
    book = import_fb2(local_library)
    root = library._book_dir(book["id"])
    assert 'role="doc-noteref"' in library.get_chapter(book["id"], 0)["html"]
    for number in (1, 37, 100):
        note = library.get_note(book["id"], anchor(f"note-{number}"))
        assert note["chapter"] == book["anchors"][note["anchor"]]
        assert f"Пояснение номер {number}:" in note["text"]
        assert f"Продолжение сноски {number}." in note["text"]
        assert note["text"].count("Пояснение номер") == 1
        assert "<em>важная деталь</em>" in note["html"]
        assert ' id=' not in note["html"]
    # Reproduce old derived files, which did not retain FB2 note roles.
    for path in (root / "chapters").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["html"] = data["html"].replace(' role="doc-footnote"', '').replace(' role="doc-noteref"', '')
        data.pop("continued_notes", None)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    before = {path:hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}
    note = library.get_note(book["id"], anchor("note-1"))
    assert "Продолжение сноски 1." in note["text"]
    assert "Пояснение номер 2:" not in note["text"]
    assert before == {path:hashlib.sha256(path.read_bytes()).hexdigest() for path in before}
    with pytest.raises(KeyError):
        library.get_note(book["id"], anchor("all-notes"))
    with pytest.raises(KeyError):
        library.get_note(book["id"], anchor("main"))


def test_note_lookup_reads_only_target_chapter(local_library, monkeypatch):
    book = import_fb2(local_library)
    reads = []
    original = Path.read_text
    def read_text(path, *args, **kwargs):
        if path.parent.name == "chapters": reads.append(path.name)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read_text)
    target = anchor("note-90")
    note = library.get_note(book["id"], target)
    assert reads == [f'{book["anchors"][target]}.json']
    assert "Пояснение номер 90:" in note["text"]


@pytest.mark.parametrize("semantic", ['epub:type="footnote"', 'role="doc-endnote"'])
def test_epub_noteref_aside_and_endnote_preserve_semantics(local_library, semantic):
    book = import_epub(local_library, '<p>Текст<a epub:type="noteref" href="notes.xhtml#note1">[1]</a></p>',
        f'<aside {semantic} id="note1"><p>Первое пояснение.</p><p>Второй абзац.</p></aside><aside role="doc-footnote" id="note2"><p>Чужая сноска.</p></aside>')
    assert 'role="doc-noteref"' in library.get_chapter(book["id"], 0)["html"]
    note = library.get_note(book["id"], anchor("OPS/notes.xhtml#note1"))
    assert note["text"] == "Первое пояснение. Второй абзац."
    assert "Чужая" not in note["html"]


def test_legacy_epub_paragraph_anchor_returns_just_that_paragraph(local_library):
    book = import_epub(local_library, '<p>Текст<a href="notes.xhtml#note1">[1]</a></p>',
        '<p id="note1">Первое пояснение.</p><p id="note2">Второе пояснение.</p>')
    assert library.get_note(book["id"], anchor("OPS/notes.xhtml#note1"))["text"] == "Первое пояснение."
    with pytest.raises(KeyError):
        library.get_note(book["id"], anchor("OPS/notes.xhtml"))


def test_number_heading_and_empty_anchor_stop_at_next_note():
    ident, other = anchor("n1"), anchor("n2")
    for source in [f'<h2 id="{ident}">1</h2><p>Первое пояснение.</p><p>Продолжение.</p><h2 id="{other}">2</h2><p>Чужая сноска.</p>',
                   f'<a id="{ident}"></a>Первое пояснение.<p>Продолжение.</p><a id="{other}"></a>Чужая сноска.']:
        note = extract_note(source, ident, "a" * 32)
        assert "Первое пояснение." in note["text"]
        assert "Продолжение." in note["text"]
        assert "Чужая" not in note["html"]


def test_popup_html_is_sanitized_and_has_no_duplicate_dom_ids():
    ident = anchor("n1")
    note = extract_note(f'''<aside role="doc-footnote" id="{ident}" style="color:red" onclick="evil()"><p>Текст <em>сноски</em>.</p>
      <script>alert(1)</script><img src="https://tracker.example/pixel" onerror="evil()"/>
      <a href="javascript:evil()">опасная ссылка</a><a href="#{anchor('back')}">назад</a>
      <img src="/api/books/{'a'*32}/resources/figure.png" alt="Схема"/>
    </aside>''', ident, "a" * 32)
    for forbidden in ("script", "alert", "onclick", "onerror", "javascript:", "style=", "tracker.example", ' id='):
        assert forbidden not in note["html"]
    assert "<em>сноски</em>" in note["html"]
    assert '/resources/figure.png' in note["html"]


def test_split_or_oversized_notes_fall_back_to_section(local_library, monkeypatch):
    monkeypatch.setattr(parsers, "CHUNK_TARGET", 500)
    book = import_epub(local_library, '<p>Текст<a epub:type="noteref" href="notes.xhtml#note1">[1]</a></p>',
        '<p>' + 'Начало. ' * 45 + '</p><aside epub:type="footnote" id="note1"><p>' + 'Первая часть. ' * 30 + '</p><p>Окончание сноски.</p></aside>')
    target = anchor("OPS/notes.xhtml#note1")
    chapter = library.get_chapter(book["id"], book["anchors"][target])
    assert target in chapter["continued_notes"]
    with pytest.raises(KeyError, match="продолжается"):
        library.get_note(book["id"], target)
    assert extract_note(f'<p id="{target}">' + 'я' * 12001 + '</p>', target, book["id"]) is None
    inner = anchor("inner")
    assert extract_note(f'<aside role="doc-footnote" id="{target}"><p id="{inner}">Только начало сноски.</p></aside>', inner, book["id"], [target]) is None


def test_notes_api_missing_and_invalid_anchors_return_404(local_library):
    book = import_fb2(local_library, count=2)
    with TestClient(server.app, base_url=f"http://127.0.0.1:{server.PORT}") as client:
        response = client.get(f'/api/books/{book["id"]}/notes/{anchor("note-1")}')
        assert response.status_code == 200, response.text
        assert response.json()["anchor"] == anchor("note-1")
        for ident in ("missing", "invalid.anchor", anchor("all-notes")):
            assert client.get(f'/api/books/{book["id"]}/notes/{ident}').status_code == 404
        assert client.get(f'/api/books/{"0"*32}/notes/{anchor("note-1")}').status_code == 404
    with pytest.raises(KeyError):
        library.get_note(book["id"], "../../original.fb2")
