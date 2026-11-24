import asyncio
import json
import pytest
from fastapi import HTTPException
from backend import opds


def test_published_acquisition_sizes_atom_and_json():
    xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Book</title>
    <link rel="http://opds-spec.org/acquisition" href="/book.epub" type="application/epub+zip" length="1048576"/>
    <link rel="http://opds-spec.org/acquisition" href="/book.pdf" type="application/pdf" length="unknown"/>
    </entry></feed>'''
    acquisitions = opds.parse_feed(xml, 'https://books.example/opds')['entries'][0]['acquisitions']
    assert acquisitions[0]['size_bytes'] == 1048576
    assert 'size_bytes' not in acquisitions[1]
    data = {'publications': [{'metadata': {'title': 'Book'}, 'links': [
        {'href': '/book.epub', 'rel': opds.ACQUISITION, 'type': 'application/epub+zip', 'size': 512000, 'duration': 20},
        {'href': '/book.pdf', 'rel': opds.ACQUISITION, 'type': 'application/pdf', 'properties': {'numberOfItems': 999}}
    ]}]}
    acquisitions = opds.parse_json(data, 'https://books.example/opds')['entries'][0]['acquisitions']
    assert acquisitions[0]['size_bytes'] == 512000
    assert 'size_bytes' not in acquisitions[1]


def test_published_languages_atom_json_and_flibusta_fallback():
    xml = '''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/terms/" xmlns:dce="http://purl.org/dc/elements/1.1/">
    <entry xml:lang="pl"><title>Book</title><dc:language>ru-RU</dc:language><dce:language>en</dce:language><dc:language>RU_ru</dc:language><link rel="http://opds-spec.org/acquisition" href="/book.epub" type="application/epub+zip"/></entry>
    <entry xml:lang="pl"><title>Unknown</title><link rel="http://opds-spec.org/acquisition" href="/other.epub" type="application/epub+zip"/></entry></feed>'''.encode()
    entries = opds.parse_feed(xml, 'https://books.example/opds')['entries']
    assert entries[0]['languages'] == ['ru-RU', 'en']
    assert entries[1]['languages'] == []  # xml:lang describes feed text, not publication language.
    for language, expected in [('en-GB', ['en-GB']), (['ru', 'en', 'RU'], ['ru', 'en']), (None, []), ({'name': 'ru'}, [])]:
        data = {'publications': [{'metadata': {'title': 'Book', 'language': language}, 'links': [{'href': '/book.epub', 'rel': opds.ACQUISITION, 'type': 'application/epub+zip'}]}]}
        assert opds.parse_json(data, 'https://books.example/opds')['entries'][0]['languages'] == expected
    assert opds.flibusta_metadata('<br/>Язык: ru<br/>', 'https://flibusta.is/opds', []) == {'languages': ['ru']}


@pytest.mark.parametrize('value', [None, '', '1.5', -1, 0, True, [], {}, float('inf'), '9007199254740992'])
def test_invalid_published_sizes_are_not_zero_or_estimated(value):
    assert opds.published_size(value) is None


def test_flibusta_footer_metadata_preserves_source_format_and_fractional_sequence():
    xml = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Book 99</title>
    <content type="text/html">&lt;p&gt;Описание книги, а не метаданные.&lt;/p&gt;&lt;br/&gt;Формат: fb2&lt;br/&gt;Язык: ru&lt;br/&gt;Размер: 1536 Kb&lt;br/&gt;Серия: Космос #2.5&lt;br/&gt;</content>
    <link href="/opds/sequencebooks/8" rel="related" type="application/atom+xml" title="Все книги серии &quot;Космос&quot;"/>
    <link rel="http://opds-spec.org/acquisition" href="/book.epub" type="application/epub+zip"/>
    </entry></feed>'''.encode()
    entry = opds.parse_feed(xml, 'https://flibusta.is/opds/sequence/8')['entries'][0]
    assert entry['catalog_size'] == {'bytes': 1572864, 'format': 'FB2'}
    assert 'size_bytes' not in entry['acquisitions'][0]  # The generated EPUB size is unknown.
    assert entry['series'][0]['name'] == 'Космос'
    assert entry['series'][0]['position'] == '2.5'
    assert entry['series'][0]['links'][0]['url'] == 'https://flibusta.is/opds/sequencebooks/8'
    other = opds.parse_feed(xml, 'https://example.com/opds')['entries'][0]
    assert 'catalog_size' not in other and other['series'] == []


def test_flibusta_footer_does_not_guess_from_title_or_prose():
    assert opds.flibusta_metadata('<p>Формат: fb2<br/>Размер: 20 Kb</p>', 'https://flibusta.is/opds', []) == {}
    assert opds.flibusta_metadata('<br/>Размер: 200 Kb<br/>Серия: Год 2000<br/>', 'https://flibusta.is/opds', []) == {'series': [{'name': 'Год 2000', 'position': None, 'links': []}]}
    assert opds.flibusta_metadata('<br/>Формат: fb2<br/>Размер: ' + '9' * 500 + ' Kb<br/>', 'https://flibusta.is/opds', []) == {}


def test_atom_relative_links_and_html_description():
    xml = b'''<feed xmlns="http://www.w3.org/2005/Atom" xml:base="https://books.example/root/">
    <title>Library</title><link rel="next" href="?page=2"/><link rel="search" href="search.xml" type="application/opensearchdescription+xml"/>
    <entry><title>Authors</title><link href="authors/" type="application/atom+xml"/></entry>
    <entry><id>a</id><title>Test</title><author><name>Author</name></author>
    <summary type="html">&lt;b&gt;Hello&lt;/b&gt;</summary>
    <link rel="http://opds-spec.org/image/thumbnail" href="cover.png"/>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/epub+zip" href="download/123"/>
    <link rel="http://opds-spec.org/acquisition" type="application/pdf" href="file.pdf"/>
    </entry></feed>'''
    data = opds.parse_feed(xml, 'https://books.example/feed')
    assert data['next'] == 'https://books.example/root/?page=2'
    assert data['navigation'][0]['url'] == 'https://books.example/root/authors/'
    book = data['entries'][0]
    assert book['summary'] == 'Hello'
    assert len(book['acquisitions']) == 2
    assert book['acquisitions'][0]['url'].endswith('/root/download/123')
    assert book['cover_url'].startswith('/api/opds/cover?')


def test_json_groups_search_and_authors():
    feed = {'metadata': {'title': 'Demo'}, 'links': [{'rel': ['search'], 'href': '/search{?query}'}], 'groups': [{'publications': [{'metadata': {'title': 'Test', 'author': [{'name': 'One'}, 'Two']}, 'links': [{'rel': 'http://opds-spec.org/acquisition/open-access', 'type': 'application/fb2+zip', 'href': '/download/3'}]}]}]}
    result = opds.parse_feed(json.dumps(feed).encode(), 'https://example.com/feeds')
    assert result['entries'][0]['authors'] == ['One', 'Two']
    assert opds.search_template(result['search']['url'], 'test book').endswith('?query=test%20book')


def test_atom_preserves_published_author_and_series_links_with_xml_base():
    xml = '''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:x="urn:series" xml:base="https://books.example/opds/">
    <entry><title>Book</title><!-- metadata -->
      <author><name>Автор</name><uri>/a/42</uri></author>
      <link rel="related" type="application/atom+xml" href="author/42" title="Все книги автора Автор"/>
      <link rel="related" type="application/atom+xml" href="sequence/8" title="Все книги серии Космос"/>
      <link rel="alternate" type="text/html" href="/b/1"/>
      <x:series name="Космос" index="3"/>
      <link rel="http://opds-spec.org/acquisition" type="application/epub+zip" href="/b/1/epub"/>
    </entry></feed>'''.encode()
    entry = opds.parse_feed(xml, 'https://books.example/opaque')['entries'][0]
    assert entry['author_details'][0]['uri'] == 'https://books.example/a/42'
    assert [link['url'] for link in entry['related_links']] == ['https://books.example/opds/author/42', 'https://books.example/opds/sequence/8']
    assert entry['series'][0]['name'] == 'Космос' and entry['series'][0]['position'] == '3'


def test_nested_json_author_and_series_links_are_resolved_and_unsafe_links_dropped():
    data = {'groups':[{'publications':[{'metadata':{'title':'Book', 'author':[
        {'name':'One','identifier':'/website/one','links':[{'href':'authors/1','type':'application/opds+json'}]}, 'Two'],
        'belongsTo':{'series':[{'name':'Космос','position':2,'links':[{'href':'series/8','type':'application/opds+json'}, {'href':'javascript:bad','type':'application/opds+json'}]},'Без ссылки']}},
        'links':[{'href':'/book.epub','type':'application/epub+zip','rel':'http://opds-spec.org/acquisition'}]}]}]}
    entry = opds.parse_json(data, 'https://books.example/opds/')['entries'][0]
    assert entry['authors'] == ['One','Two']
    assert entry['author_details'][0]['links'][0]['url'] == 'https://books.example/opds/authors/1'
    assert entry['author_details'][0]['uri'] == 'https://books.example/website/one'
    assert entry['series'][0]['position'] == 2 and len(entry['series'][0]['links']) == 1
    assert entry['series'][1]['name'] == 'Без ссылки' and entry['series'][1]['links'] == []


def test_atom_explicit_up_uses_xml_base_and_is_distinct_from_catalog_start():
    xml = b'''<feed xmlns="http://www.w3.org/2005/Atom" xml:base="https://books.example/catalog/authors/">
      <link rel="start" href="/catalog"/><link rel="up" xml:base="../" href="genres"/>
      <entry><title>Author books</title><link rel="up" href="/unrelated-entry-parent"/></entry>
    </feed>'''
    result = opds.parse_feed(xml, 'https://books.example/opaque?id=123')
    assert result['up'] == 'https://books.example/catalog/genres'
    assert result['navigation'] == [
        {'title': 'Начало каталога', 'url': 'https://books.example/catalog'},
        {'title': 'На уровень выше', 'url': 'https://books.example/catalog/genres'},
    ]


@pytest.mark.parametrize('up_relation', ['up', ['alternate', 'up']])
def test_json_top_level_up_is_not_replaced_by_group_or_start_links(up_relation):
    feed = {'metadata': {'title': 'Author'}, 'links': [
        {'rel': 'start', 'href': '/catalog'},
        {'rel': up_relation, 'href': '../index?letter=A'},
    ], 'groups': [{'links': [{'rel':'up', 'href':'/group-parent'}]}]}
    result = opds.parse_json(feed, 'https://books.example/catalog/authors/42')
    assert result['up'] == 'https://books.example/catalog/index?letter=A'


@pytest.mark.parametrize('format', ['atom', 'json'])
def test_missing_explicit_up_does_not_infer_parent_from_url_or_catalog_start(format):
    url = 'https://books.example/catalog/authors/42'
    if format == 'atom':
        result = opds.parse_feed(b'''<feed xmlns="http://www.w3.org/2005/Atom">
          <link rel="start" href="/catalog"/><link rel="up" href="javascript:alert(1)"/>
          <entry><title>Book</title><link rel="up" href="/entry-parent"/></entry>
        </feed>''', url)
    else:
        result = opds.parse_json({'links':[
            {'rel':'start', 'href':'/catalog'}, {'rel':'up', 'href':'javascript:alert(1)'},
        ], 'groups':[{'links':[{'rel':'up', 'href':'/group-parent'}]}]}, url)
    assert result['up'] is None


def test_unsupported_atom_book_stays_visible_instead_of_becoming_author_navigation():
    xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><title>Books</title>
    <entry><title>Scanned book</title><author><name>Author</name></author>
    <link rel="related" type="application/atom+xml" href="/author/1"/>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/djvu" href="/book/1/download"/>
    </entry></feed>'''
    result = opds.parse_feed(xml, 'https://example.com/opds')
    assert result['navigation'] == []
    assert len(result['entries']) == 1
    assert result['entries'][0]['acquisitions'] == []
    assert result['entries'][0]['unavailable_reason'] == 'Только DJVU'


def test_related_atom_links_do_not_hide_the_real_subsection():
    xml = b'''<feed xmlns="http://www.w3.org/2005/Atom">
    <entry><title>Biography</title><content>About this author</content><link rel="related" type="application/atom+xml" href="/series/1"/><link rel="http://opds-spec.org/acquisition" type="text/html" href="/author/1"/></entry>
    <entry><title>Books</title><link rel="related" type="application/atom+xml" href="/wrong"/><link rel="subsection" type="application/atom+xml" href="/books"/></entry>
    </feed>'''
    result = opds.parse_feed(xml, 'https://example.com/opds')
    assert result['entries'] == []
    assert result['navigation'] == [{'title': 'Books', 'url': 'https://example.com/books'}]


def test_unsupported_json_publication_is_not_silently_dropped():
    data = {'metadata': {'title': 'Demo'}, 'publications': [{'metadata': {'title': 'Scan'}, 'links': [{'rel': 'http://opds-spec.org/acquisition/open-access', 'href': '/scan', 'type': 'application/djvu'}]}]}
    result = opds.parse_json(data, 'https://example.com/opds')
    assert result['entries'][0]['title'] == 'Scan'
    assert result['entries'][0]['acquisitions'] == []
    assert result['entries'][0]['unavailable_reason'] == 'Только DJVU'


@pytest.mark.parametrize('relation', ['previous', 'prev'])
def test_previous_page_relation_is_absolute_and_top_level(relation):
    xml = f'''<feed xmlns="http://www.w3.org/2005/Atom" xml:base="https://books.example/list/">
      <link rel="{relation}" href="?page=1"/><entry><title>Book</title><link rel="previous" href="/wrong"/></entry>
    </feed>'''.encode()
    assert opds.parse_feed(xml, 'https://books.example/opaque')['prev'] == 'https://books.example/list/?page=1'
    data = {'links': [{'rel': ['alternate', relation], 'href': '?page=1'}, {'rel': 'next', 'href': '?page=3'}],
            'groups': [{'links': [{'rel': 'previous', 'href': '/wrong'}, {'rel': 'next', 'href': '/wrong-next'}]}]}
    result = opds.parse_json(data, 'https://books.example/list/?page=2')
    assert result['prev'] == 'https://books.example/list/?page=1'
    assert result['next'] == 'https://books.example/list/?page=3'
    assert opds.parse_json({}, 'https://books.example/list/')['prev'] is None


@pytest.mark.parametrize('mime,extension', [('text/plain', '.txt'), ('application/pdf', '.pdf'), ('application/vnd.comicbook+zip', '.cbz'), ('application/x-cbz', '.cbz'), ('application/vnd.comicbook-rar', '.cbr'), ('application/x-cbr', '.cbr')])
def test_new_opds_formats_accept_mime_or_filename(mime, extension):
    assert opds.supported(mime, 'https://books.example/download/123')
    assert opds.supported('application/octet-stream', 'https://books.example/book' + extension)
    assert not opds.supported('application/vnd.rar', 'https://books.example/unknown.rar')


def test_unsafe_schemes_are_rejected():
    for url in ['file:///etc/hosts', 'javascript:alert(1)', 'http://user:secret@localhost/a']:
        with pytest.raises(ValueError): opds.valid_url(url)
    assert opds.valid_url('http://192.168.1.5:8080/opds')


def test_opensearch_atom_filters_can_be_empty_with_global_query():
    template = 'https://example.com/search/?q={searchTerms}&author={atom:author}&translator={atom:contributor}&title={atom:title}'
    assert opds.search_template(template, 'test') == 'https://example.com/search/?q=test&author=&translator=&title='


def test_external_entities_are_never_resolved():
    data = opds.parse_feed(b'''<!DOCTYPE feed [<!ENTITY xxe SYSTEM "file:///C:/Windows/win.ini">]><feed xmlns="http://www.w3.org/2005/Atom"><title>&xxe;</title></feed>''', 'https://example.com/')
    assert '[fonts]' not in data['title']


def test_libru_legacy_nbsp_is_supported_without_loose_xml_recovery():
    content = b'''<feed xmlns="http://www.w3.org/2005/Atom"><title>Books&nbsp;Library</title>
    <entry><title><![CDATA[Literal &nbsp;]]></title><link href="/next" type="application/atom+xml"/></entry></feed>'''
    result = opds.parse_feed(content, 'https://lib.ru/opds/')
    assert result['title'] == 'Books\u00a0Library'
    # The XML-level CDATA content remains literal (plain() later unescapes display text).
    assert opds.parse_xml(content, 'https://lib.ru/opds/').find(opds.ATOM + 'entry').findtext(opds.ATOM + 'title') == 'Literal &nbsp;'
    with pytest.raises(opds.CatalogResponseError):
        opds.parse_feed(b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Broken&nbsp;</feed>', 'https://example.com/')
    with pytest.raises(opds.CatalogResponseError):
        opds.parse_feed(b'<!DOCTYPE feed [<!ENTITY custom "x">]><feed xmlns="http://www.w3.org/2005/Atom"><title>&nbsp;</title></feed>', 'https://example.com/')


@pytest.mark.parametrize('mime,extension', [('application/fb2+xml', '.fb2'), ('text/plain; charset=utf-8', '.txt'), ('application/pdf', '.pdf'), ('application/vnd.comicbook+zip', '.cbz'), ('application/x-cbz', '.cbz'), ('application/vnd.comicbook-rar', '.cbr'), ('application/x-cbr', '.cbr')])
def test_download_extensionless_api_uses_mime_and_cleans_temp(monkeypatch, mime, extension):
    import httpx
    from backend import library
    captured = {}
    def handler(request):
        return httpx.Response(200, content=b'<FictionBook/>', headers={'content-type': mime})
    real = httpx.AsyncClient
    monkeypatch.setattr(opds.httpx, 'AsyncClient', lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    def importer(path, original_name):
        captured['path'] = path
        captured['name'] = original_name
        captured['data'] = path.read_bytes()
        return {'book': {'id': 'x'}, 'duplicate': False}
    monkeypatch.setattr(library, 'import_path', importer)
    monkeypatch.setattr(opds, 'acquired_book', lambda url: None)
    monkeypatch.setattr(opds, 'remember_acquisition', lambda url, book_id: None)
    result = asyncio.run(opds.download(opds.Download(url='https://example.com/download/10')))
    assert result['book']['id'] == 'x'
    assert captured['name'].endswith(extension)
    assert not captured['path'].exists()


def test_previously_downloaded_book_opens_without_network(monkeypatch):
    monkeypatch.setattr(opds, 'acquired_book', lambda url: {'id': 'existing'})
    def forbidden(*args, **kwargs):
        raise AssertionError('Repeated acquisition must not download again')
    monkeypatch.setattr(opds.httpx, 'AsyncClient', forbidden)
    result = asyncio.run(opds.download(opds.Download(url='https://example.com/book.epub')))
    assert result == {'book': {'id': 'existing'}, 'duplicate': True}


def test_local_catalog_marker_tracks_library_deletion(monkeypatch, tmp_path):
    from backend import library
    monkeypatch.setattr(library, 'DATA_DIR', tmp_path / 'data')
    file = tmp_path / 'book.fb2'
    file.write_text('<FictionBook><description><title-info><book-title>Test</book-title></title-info></description><body><section><p>Text</p></section></body></FictionBook>')
    book = library.import_path(file)['book']
    url = 'https://example.com/book.fb2'
    opds.remember_acquisition(url, book['id'])
    feed = {'entries': [{'acquisitions': [{'url': url}]}]}
    assert opds.annotate_local(feed)['entries'][0]['local_book_id'] == book['id']
    library.delete_book(book['id'])
    assert opds.annotate_local(feed)['entries'][0]['local_book_id'] is None


def test_network_failures_return_actionable_error(monkeypatch):
    async def unavailable(*args):
        import httpx
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(opds, 'fetch', unavailable)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(opds.browse(opds.Browse(url='https://example.com/feed')))
    assert caught.value.status_code == 502


XML_DECLARATION_ONLY = b'<?xml version="1.0" encoding="utf-8"?>\n'
VALID_EMPTY_FEED = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Empty</title></feed>'


def test_declaration_only_response_is_not_an_empty_catalog():
    # Reproduces the 39-byte HTTP 200 body returned by /opds/genres/Фантастика.
    with pytest.raises(opds.CatalogResponseError) as caught:
        opds.parse_feed(XML_DECLARATION_ONLY, 'https://example.com/opds/genres/test')
    assert caught.value.retryable is True
    assert 'незавершённый ответ' in str(caught.value)
    assert 'Start tag' not in str(caught.value)


@pytest.mark.parametrize('content', [
    b'<!DOCTYPE html><html><body>Sign in<input type=password></body></html>',
    b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>Sign in</body></html>',
])
def test_html_instead_of_catalog_is_explained_not_silently_accepted(content):
    with pytest.raises(opds.CatalogResponseError, match='веб-страницу') as caught:
        opds.parse_feed(content, 'https://example.com/opds')
    assert not caught.value.retryable


def test_gzipped_declaration_only_response_retries_then_recovers(monkeypatch):
    import gzip
    import httpx
    requests = []
    def handler(request):
        requests.append(str(request.url))
        content = XML_DECLARATION_ONLY if len(requests) == 1 else VALID_EMPTY_FEED
        return httpx.Response(200, content=gzip.compress(content), headers={
            'content-type': 'application/atom+xml;charset=utf-8', 'content-encoding': 'gzip',
        })
    real = httpx.AsyncClient
    monkeypatch.setattr(opds.httpx, 'AsyncClient', lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(opds, 'annotate_local', lambda feed: feed)
    result = asyncio.run(opds.browse(opds.Browse(url='https://example.com/opds')))
    assert result['title'] == 'Empty'
    assert result['entries'] == []
    assert len(requests) == 2


def test_persistently_incomplete_feed_returns_upstream_error_after_one_retry(monkeypatch):
    requests = []
    async def fetch(url, limit):
        requests.append(url)
        return XML_DECLARATION_ONLY, url, 'application/atom+xml;charset=utf-8'
    monkeypatch.setattr(opds, 'fetch', fetch)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(opds.browse(opds.Browse(url='https://example.com/opds')))
    assert caught.value.status_code == 502
    assert 'незавершённый ответ' in caught.value.detail
    assert 'line 2' not in caught.value.detail
    assert len(requests) == 2


def test_valid_empty_feed_is_not_retried(monkeypatch):
    requests = []
    async def fetch(url, limit):
        requests.append(url)
        return VALID_EMPTY_FEED, url, 'application/atom+xml'
    monkeypatch.setattr(opds, 'fetch', fetch)
    monkeypatch.setattr(opds, 'annotate_local', lambda feed: feed)
    result = asyncio.run(opds.browse(opds.Browse(url='https://example.com/opds')))
    assert result['entries'] == []
    assert result['navigation'] == []
    assert len(requests) == 1


def test_opensearch_incomplete_response_retries_before_search(monkeypatch):
    requests = []
    description = b'''<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">
      <!-- A comment is not an XML element. -->
      <Url type="application/atom+xml" template="/search?q={searchTerms}"/>
    </OpenSearchDescription>'''
    async def fetch(url, limit):
        requests.append(url)
        content = XML_DECLARATION_ONLY if len(requests) == 1 else description if len(requests) == 2 else VALID_EMPTY_FEED
        return content, url, 'application/xml'
    monkeypatch.setattr(opds, 'fetch', fetch)
    monkeypatch.setattr(opds, 'annotate_local', lambda feed: feed)
    result = asyncio.run(opds.browse(opds.Browse(url='https://example.com/search.xml', query='test book')))
    assert requests == ['https://example.com/search.xml', 'https://example.com/search.xml', 'https://example.com/search?q=test%20book']
    assert result['title'] == 'Empty'


@pytest.mark.parametrize('status', [401, 403])
def test_private_catalog_sections_explain_login_requirement_without_retries(monkeypatch, status):
    import httpx
    requests = []
    async def fetch(url, limit):
        requests.append(url)
        response = httpx.Response(status, request=httpx.Request('GET', url), content=b'<html>Login</html>')
        response.raise_for_status()
    monkeypatch.setattr(opds, 'fetch', fetch)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(opds.browse(opds.Browse(url='https://example.com/my-books')))
    assert caught.value.status_code == 502
    assert 'вход' in caught.value.detail
    assert 'Авторизация в OPDS пока не поддерживается' in caught.value.detail
    assert len(requests) == 1
