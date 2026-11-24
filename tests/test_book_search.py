import json

import pytest
from fastapi.testclient import TestClient

from backend import library, search
from backend.server import app


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    """Real chapter JSON, isolated from the user's SQLite and book directory."""
    metadata = {"chapter_count": 0, "format": "FB2"}
    monkeypatch.setattr(library, 'get_book', lambda book_id: metadata)
    monkeypatch.setattr(library, '_book_dir', lambda book_id: tmp_path)
    (tmp_path / 'chapters').mkdir()

    def write(chapters):
        metadata['chapter_count'] = len(chapters)
        for index, paragraphs in enumerate(chapters):
            payload = {'index': index, 'title': f'Глава {index + 1}', 'html': '<p>ONLY_HTML</p>',
                       'paragraphs': [{'id': f'p{index}-{n}', 'text': text} for n, text in enumerate(paragraphs)]}
            (tmp_path / 'chapters' / f'{index}.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return metadata
    return write


def test_multiple_chapters_and_occurrences_are_separate_results(prepared):
    prepared([['Начало: Книга, книга.'], ['Продолжение КНИГА', 'Без совпадений']])
    result = search.search_book('fixture', 'книга')
    assert result['total'] == 3
    assert [hit['chapter'] for hit in result['results']] == [0, 0, 1]
    assert [hit['id'] for hit in result['results']] == ['p0-0', 'p0-0', 'p1-0']
    assert [hit['match'] for hit in result['results']] == ['Книга', 'книга', 'КНИГА']
    assert result['results'][2]['chapter_title'] == 'Глава 2'
    assert result['next_offset'] is None
    assert search.search_book('fixture', 'ONLY_HTML')['total'] == 0


def test_emoji_offsets_are_utf16_and_context_is_plain_actual_case(prepared):
    text = '😀 🐈 КниГа 😀 книга'
    prepared([[text]])
    hits = search.search_book('fixture', 'КНИГА')['results']
    assert [(hit['start'], hit['end']) for hit in hits] == [(6, 11), (15, 20)]
    encoded = text.encode('utf-16-le')
    for hit in hits:
        assert encoded[hit['start'] * 2:hit['end'] * 2].decode('utf-16-le') == hit['match']
        assert hit['before'] + hit['match'] + hit['after'] == text


def test_literal_regex_characters_and_canonical_whitespace(prepared):
    prepared([['В начале [a].* и снова [a].*.', 'Белый\n  \t кит\u00a0плывёт.']])
    assert search.search_book('fixture', '[a].*')['total'] == 2
    result = search.search_book('fixture', '  белый\t кит ')
    assert result['query'] == 'белый кит'
    assert result['total'] == 1
    assert result['results'][0]['match'] == 'Белый кит'
    assert result['results'][0]['start'] == 0


def test_chapter_scope_and_result_pagination(prepared):
    prepared([['слово слово'], ['слово слово слово']])
    scoped = search.search_book('fixture', 'слово', scope='chapter', chapter=1, offset=1, limit=1)
    assert scoped['total'] == 3
    assert scoped['offset'] == 1 and scoped['next_offset'] == 2
    assert scoped['results'][0]['chapter'] == 1
    assert scoped['results'][0]['start'] == 6
    result = search.search_book('fixture', 'слово', offset=2, limit=2)
    assert result['total'] == 5 and result['next_offset'] == 4
    assert all(hit['chapter'] == 1 for hit in result['results'])
    last = search.search_book('fixture', 'слово', offset=4, limit=2)
    assert len(last['results']) == 1 and last['next_offset'] is None
    assert search.search_book('fixture', 'слово', offset=100)['results'] == []


def test_count_remains_exact_after_return_page_is_full_and_context_is_bounded(prepared):
    prepared([['слово ' * 110], ['слово ' * 110], ['x' * 200 + 'слово' + 'y' * 200]])
    result = search.search_book('fixture', 'слово')
    assert result['total'] == 221 and len(result['results']) == 100 and result['next_offset'] == 100
    last = search.search_book('fixture', 'слово', offset=220)['results'][0]
    assert len(last['before']) == 70 and len(last['after']) == 70


def test_chapter_scope_does_not_load_other_chapter_files(prepared, monkeypatch):
    prepared([['слово'], ['слово'], ['слово']])
    original = search.json.load
    names = []
    def capture(source):
        names.append(source.name)
        return original(source)
    monkeypatch.setattr(search.json, 'load', capture)
    search.search_book('fixture', 'слово', scope='chapter', chapter=1)
    assert len(names) == 1 and names[0].endswith('1.json')


@pytest.mark.parametrize('format', ['PDF', 'CBZ', 'CBR'])
def test_image_publications_return_clear_422_without_ocr(prepared, format):
    metadata = prepared([])
    metadata.update(format=format, reader_type='pages')
    with TestClient(app, base_url='http://127.0.0.1:18765') as client:
        result = client.get('/api/books/fixture/search', params={'q': 'книга'})
    assert result.status_code == 422
    assert 'распознавание' in result.json()['detail']


def test_route_contract_and_input_validation(prepared):
    prepared([['😀 КНИГА книга']])
    with TestClient(app, base_url='http://127.0.0.1:18765') as client:
        result = client.get('/api/books/fixture/search', params={'q': 'книга', 'scope': 'book', 'offset': 1, 'limit': 1})
        assert result.status_code == 200
        data = result.json()
        assert set(data) == {'query', 'scope', 'total', 'offset', 'next_offset', 'results'}
        assert set(data['results'][0]) == {'chapter', 'chapter_title', 'id', 'start', 'end', 'before', 'match', 'after'}
        for params in [{'q': '   '}, {'q': 'a' * 161}, {'q': 'a', 'scope': 'invalid'}, {'q': 'a', 'limit': 101}, {'q': 'a', 'offset': -1}]:
            assert client.get('/api/books/fixture/search', params=params).status_code == 422
        assert client.get('/api/books/fixture/search', params={'q': 'a', 'scope': 'chapter', 'chapter': 5}).status_code == 404


def test_real_fb2_import_returns_ids_and_offsets_from_prepared_chapters(tmp_path, monkeypatch):
    monkeypatch.setattr(library, 'DATA_DIR', tmp_path / 'library')
    source = tmp_path / 'book.fb2'
    source.write_text('''<FictionBook><description><title-info><book-title>Поиск</book-title></title-info></description><body>
    <section><title><p>Первая глава</p></title><p>😀 Игла, игла.</p></section>
    <section><title><p>Вторая глава</p></title><p>Другая ИГЛА.</p></section>
    </body></FictionBook>''', encoding='utf-8')
    book = library.import_path(source)['book']
    result = search.search_book(book['id'], 'игла')
    assert result['total'] == 3
    for hit in result['results']:
        chapter = library.get_chapter(book['id'], hit['chapter'])
        text = next(p['text'] for p in chapter['paragraphs'] if p['id'] == hit['id'])
        assert text.encode('utf-16-le')[hit['start'] * 2:hit['end'] * 2].decode('utf-16-le') == hit['match']
