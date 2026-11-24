"""A small OPDS 1.2 / 2.0 client. All network and import work stays off the UI."""
from __future__ import annotations

import asyncio
import hashlib
import html
import io
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from lxml import etree
from pydantic import BaseModel, Field
from PIL import Image, UnidentifiedImageError

router = APIRouter(prefix="/api/opds", tags=["opds"])
ATOM = "{http://www.w3.org/2005/Atom}"
ACQUISITION = "http://opds-spec.org/acquisition"
MAX_FEED = 12 * 1024 * 1024
MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_IMAGE = 12 * 1024 * 1024
TIMEOUT = httpx.Timeout(45.0, connect=15.0)
_cover_cache: dict[str, tuple[bytes, str]] = {}


class CatalogResponseError(ValueError):
    """An unusable upstream response, rather than an invalid user-supplied URL."""
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class Browse(BaseModel):
    url: str = Field(min_length=1, max_length=4096)
    query: str | None = Field(default=None, max_length=500)


class Download(BaseModel):
    url: str = Field(min_length=1, max_length=4096)
    title: str = "Книга"
    filename: str | None = None
    type: str | None = None


def valid_url(value: str, base: str | None = None) -> str:
    result = urljoin(base, value) if base else value
    parts = urlsplit(result)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Каталог должен использовать http:// или https://")
    if parts.username or parts.password:
        raise ValueError("Каталоги с паролем пока не поддерживаются")
    return result


def absolute(value: str | None, base: str) -> str | None:
    if not value:
        return None
    try:
        return valid_url(value, base)
    except ValueError:
        return None


def plain(value) -> str:
    if isinstance(value, dict):
        value = next(iter(value.values()), "")
    return html.unescape(re.sub(r"<[^>]*>", " ", str(value or ""))).strip()


def cover_url(value: str | None) -> str | None:
    return "/api/opds/cover?url=" + quote(value, safe="") if value else None


def thumbnail(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as source:
        if source.width * source.height > 40_000_000:
            raise ValueError("Слишком большое изображение обложки")
        source.draft("RGB", (640, 960))
        source.thumbnail((640, 960))
        rgba = source.convert("RGBA")
        image = Image.new("RGB", rgba.size, "white")
        image.paste(rgba, mask=rgba.getchannel("A"))
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=87)
        return output.getvalue()


def acquired_book(url: str):
    from . import library
    library.init()
    with library.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS opds_acquisitions (url TEXT PRIMARY KEY, book_id TEXT NOT NULL)")
        row = db.execute("SELECT a.book_id FROM opds_acquisitions a JOIN books b ON b.id=a.book_id WHERE a.url=?", (url,)).fetchone()
    return library.get_book(row[0]) if row else None


def remember_acquisition(url: str, book_id: str):
    from . import library
    with library.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS opds_acquisitions (url TEXT PRIMARY KEY, book_id TEXT NOT NULL)")
        db.execute("INSERT OR REPLACE INTO opds_acquisitions(url,book_id) VALUES (?,?)", (url, book_id))


def annotate_local(feed: dict) -> dict:
    from . import library
    library.init()
    with library.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS opds_acquisitions (url TEXT PRIMARY KEY, book_id TEXT NOT NULL)")
        local = dict(db.execute("SELECT a.url,a.book_id FROM opds_acquisitions a JOIN books b ON b.id=a.book_id"))
    for entry in feed['entries']:
        entry['local_book_id'] = next((local[a['url']] for a in entry['acquisitions'] if a['url'] in local), None)
    return feed


def supported(mime: str, url: str) -> bool:
    mime = mime.split(";")[0].strip().lower()
    name = unquote(urlsplit(url).path).lower()
    return mime in {"application/epub+zip", "application/fb2+xml", "application/x-fictionbook+xml", "application/fb2+zip", "application/x-fictionbook+zip", "text/plain", "application/pdf", "application/vnd.comicbook+zip", "application/x-cbz", "application/vnd.comicbook-rar", "application/x-cbr"} or name.endswith((".epub", ".fb2", ".fb2.zip", ".txt", ".pdf", ".cbz", ".cbr"))


def unavailable_reason(links: list[dict]) -> str:
    formats = []
    for link in links:
        mime = link.get("type", "").split(";")[0].strip().lower()
        label = {"application/pdf": "PDF", "application/djvu": "DJVU", "image/vnd.djvu": "DJVU", "application/x-djvu": "DJVU", "application/x-mobipocket-ebook": "MOBI"}.get(mime)
        if label and label not in formats:
            formats.append(label)
    return ("Только " + ", ".join(formats)) if formats else "Нет поддерживаемого формата"


def rels(link: dict) -> list[str]:
    rel = link.get("rel", [])
    return [rel] if isinstance(rel, str) else rel


def _result(title: str, url: str) -> dict:
    return {"title": title or "Каталог", "url": url, "entries": [], "navigation": [], "up": None, "next": None, "prev": None, "search": None}


def catalog_links(links: list[dict], base: str) -> list[dict]:
    """Keep published OPDS destinations; author web URIs are separate metadata."""
    result = []
    for link in links:
        if not isinstance(link, dict): continue
        target = absolute(link.get('href'), base)
        mime = link.get('type', '').lower()
        if target and ('atom+xml' in mime or 'opds+json' in mime):
            result.append({'url': target, 'title': plain(link.get('title')), 'type': link.get('type', ''), 'rel': rels(link)})
    return result


def named_values(value) -> list:
    return value if isinstance(value, list) else [value] if isinstance(value, (str, dict)) else []


def published_languages(value) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result = []
    seen = set()
    for language in values:
        if not isinstance(language, str):
            continue
        language = language.strip()
        key = language.lower().replace('_', '-')
        if language and len(language) <= 80 and key not in seen:
            result.append(language)
            seen.add(key)
    return result


def published_size(value) -> int | None:
    """Only byte counts explicitly published on a link, never a network probe."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,16}", text):
        return None
    size = int(text)
    return size if 0 < size <= 2**53 - 1 else None


def flibusta_metadata(content: str, url: str, related: list[dict]) -> dict:
    """Flibusta publishes source size and sequence position in its metadata footer.

    The source FB2 size is not the size of a generated EPUB or download archive.
    Keep it separate from acquisition-link byte counts.
    """
    if not re.fullmatch(r"(?:[a-z0-9-]+\.)*flibusta\.[a-z]{2,}", urlsplit(url).hostname or "", re.I):
        return {}
    # Match complete <br>-delimited fields, not words embedded in a synopsis.
    lines = [plain(part) for part in re.split(r"<br\s*/?>", content, flags=re.I) if '<' not in part]
    fields = [re.fullmatch(r"(Формат|Размер|Серия|Язык):\s*(.+)", line, re.I) for line in lines]
    fields = [(match[1].lower(), match[2].strip()) for match in fields if match]
    source_format = next((value.lower() for key, value in fields if key == "формат"), "")
    result = {}
    for key, value in fields:
        if key == "размер" and source_format:
            match = re.fullmatch(r"([0-9]{1,16}(?:[.,][0-9]{1,6})?)\s*(Kb|Кб|KB|MB|Мб|B|байт)", value, re.I)
            if match:
                unit = match[2].lower()
                multiplier = 1024**2 if unit in {"mb", "мб"} else 1024 if unit in {"kb", "кб"} else 1
                size = published_size(round(float(match[1].replace(",", ".")) * multiplier))
                if size:
                    result["catalog_size"] = {"bytes": size, "format": source_format.upper()}
        elif key == "серия":
            match = re.fullmatch(r"(.+?)\s+#([0-9]+(?:[.,][0-9]+)?)", value)
            name = match[1].strip() if match else value
            position = match[2].replace(",", ".") if match else None
            destinations = [link for link in related if re.sub(r'^Все книги серии\s+', '', link.get('title', ''), flags=re.I).strip(' "«»').casefold() == name.strip(' "«»').casefold()]
            result.setdefault("series", []).append({"name": name, "position": position, "links": destinations})
        elif key == "язык":
            result["languages"] = published_languages(value)
    return result


def parse_xml(content: bytes, url: str):
    stripped = content.removeprefix(b"\xef\xbb\xbf").strip()
    without_declaration = re.sub(br"^<\?xml\b[^>]*\?>", b"", stripped, count=1).strip()
    if not without_declaration:
        raise CatalogResponseError("Раздел временно недоступен: сервер каталога прислал пустой или незавершённый ответ. Попробуйте обновить его позже.", retryable=True)
    if re.match(br"(?:<!doctype\s+html\b|<html\b)", without_declaration, re.I):
        raise CatalogResponseError("Вместо OPDS-каталога сервер прислал веб-страницу. Проверьте адрес каталога; возможно, этот раздел требует входа на сайт.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    try:
        root = etree.fromstring(content, parser, base_url=url)
    except etree.XMLSyntaxError as exc:
        # Lib.ru publishes otherwise valid Atom with HTML's undeclared &nbsp;.
        # Repair only that entity outside literal sections; keep strict XML parsing
        # and never change a document with its own DTD/entity declarations.
        repaired = content
        if b"&nbsp;" in content and not re.search(br"<!DOCTYPE\b", content, re.I):
            parts = re.split(br"(<!\[CDATA\[.*?\]\]>|<!--.*?-->)", content, flags=re.S)
            repaired = b"".join(part if index % 2 else part.replace(b"&nbsp;", b"&#160;") for index, part in enumerate(parts))
        try:
            if repaired == content:
                raise exc
            root = etree.fromstring(repaired, parser, base_url=url)
        except etree.XMLSyntaxError as invalid:
            raise CatalogResponseError("Сервер прислал повреждённый или незавершённый XML-каталог. Попробуйте обновить раздел позже.", retryable=True) from invalid
    if etree.QName(root).localname.lower() == "html":
        raise CatalogResponseError("Вместо OPDS-каталога сервер прислал веб-страницу. Проверьте адрес каталога; возможно, этот раздел требует входа на сайт.")
    return root


def parse_feed(content: bytes, url: str) -> dict:
    if content.removeprefix(b"\xef\xbb\xbf").lstrip().startswith((b"{", b"[")):
        try:
            data = json.loads(content)
        except (ValueError, UnicodeError) as exc:
            raise CatalogResponseError("Сервер прислал повреждённый или незавершённый JSON-каталог. Попробуйте обновить раздел позже.", retryable=True) from exc
        return parse_json(data, url)
    root = parse_xml(content, url)
    if etree.QName(root).localname not in {"feed", "entry"}:
        raise CatalogResponseError("По этому адресу сервер не предоставил OPDS-каталог. Проверьте адрес раздела.")
    # XML base can appear at feed, entry or individual link level.
    def links(node):
        return [dict(e.attrib, href=absolute(e.get("href"), e.base or url)) for e in node.findall(ATOM + "link") if absolute(e.get("href"), e.base or url)]
    result = _result(plain(root.findtext(ATOM + "title")), url)
    for link in links(root):
        rel = link.get("rel", "alternate")
        if rel == "next": result["next"] = link["href"]
        elif rel in {"previous", "prev"}: result["prev"] = link["href"]
        elif rel == "search": result["search"] = {"url": link["href"], "type": link.get("type", "")}
        elif rel in {"up", "start", "http://opds-spec.org/facet"}:
            if rel == "up": result["up"] = link["href"]
            result["navigation"].append({"title": link.get("title") or ("На уровень выше" if rel == "up" else "Начало каталога"), "url": link["href"]})
    nodes = [root] if etree.QName(root).localname == "entry" else root.findall(ATOM + "entry")
    for entry in nodes:
        title = plain(entry.findtext(ATOM + "title")) or "Без названия"
        all_links = links(entry)
        download_links = [l for l in all_links if l.get("rel", "").startswith(ACQUISITION) and l.get("type", "").split(";")[0].strip().lower() not in {"text/html", "application/xhtml+xml"}]
        acquisitions = [{"url": l["href"], "type": l.get("type", ""), "title": l.get("title") or l.get("type", "Файл"), **({"size_bytes": size} if (size := published_size(l.get("length"))) else {})} for l in download_links if supported(l.get("type", ""), l["href"])]
        if download_links:
            images = [l["href"] for l in all_links if l.get("rel", "") in {"http://opds-spec.org/image", "http://opds-spec.org/image/thumbnail", "http://opds-spec.org/thumbnail", "http://opds-spec.org/cover"}]
            summary = entry.find(ATOM + "summary")
            if summary is None: summary = entry.find(ATOM + "content")
            summary_text = " ".join(summary.itertext()) if summary is not None else ""
            author_details = [{'name': plain(a.findtext(ATOM + 'name')), 'uri': absolute(a.findtext(ATOM + 'uri'), a.base or url), 'links': catalog_links(links(a), a.base or url)} for a in entry.findall(ATOM + 'author')]
            series = [{'name': plain(node.get('name') or node.text), 'position': node.get('index') or node.get('position'), 'links': catalog_links(links(node), node.base or url)} for node in entry if isinstance(node.tag, str) and etree.QName(node).localname == 'series' and plain(node.get('name') or node.text)]
            related = catalog_links(all_links, url)
            extra = flibusta_metadata(summary_text, url, related)
            for item in extra.pop("series", []):
                if not any(existing['name'].casefold() == item['name'].casefold() for existing in series):
                    series.append(item)
            languages = published_languages([node.text for node in entry if isinstance(node.tag, str) and node.tag in {'{http://purl.org/dc/terms/}language', '{http://purl.org/dc/elements/1.1/}language'}])
            footer_languages = extra.pop('languages', [])
            result["entries"].append({"id": entry.findtext(ATOM + "id") or download_links[0]["href"], "title": title, "authors": [a['name'] for a in author_details], "author_details": author_details, "series": series, "related_links": related, "languages": languages or footer_languages, "summary": plain(summary_text), "cover_url": cover_url(images[0] if images else None), "acquisitions": acquisitions, "unavailable_reason": unavailable_reason(download_links) if not acquisitions else None, **extra})
        else:
            for link in all_links:
                mime = link.get("type", "")
                # A related author/series link does not make this entry a section.
                if link.get("rel", "subsection") in {"subsection", "alternate"} and ("atom+xml" in mime or "opds+json" in mime):
                    result["navigation"].append({"title": title, "url": link["href"]})
                    break
    return result


def parse_json(data: dict, url: str) -> dict:
    if not isinstance(data, dict): raise ValueError("Неверный JSON OPDS")
    result = _result(plain(data.get("metadata", {}).get("title")), url)
    collections = [data] + data.get("groups", [])
    for collection in collections:
        for link in collection.get("links", []):
            target = absolute(link.get("href"), url)
            if not target: continue
            if collection is data and "next" in rels(link): result["next"] = target
            if collection is data and any(rel in {"previous", "prev"} for rel in rels(link)): result["prev"] = target
            if "search" in rels(link): result["search"] = {"url": target, "type": link.get("type", "")}
            if collection is data and "up" in rels(link): result["up"] = target
        for nav in collection.get("navigation", []):
            target = absolute(nav.get("href"), url)
            if target: result["navigation"].append({"title": plain(nav.get("title")), "url": target})
        for pub in collection.get("publications", []):
            meta = pub.get("metadata", {})
            acquisitions = []
            download_links = []
            for link in pub.get("links", []):
                target = absolute(link.get("href"), url)
                if target and any(r.startswith(ACQUISITION) for r in rels(link)):
                    download_links.append(dict(link, href=target))
                    if supported(link.get("type", ""), target):
                        acquisitions.append({"url": target, "type": link.get("type", ""), "title": plain(link.get("title") or link.get("type")), **({"size_bytes": size} if (size := published_size(link.get("size"))) else {})})
            if not download_links: continue
            authors = meta.get("author", [])
            if isinstance(authors, (str, dict)): authors = [authors]
            author_details = [{'name': plain(a.get('name')) if isinstance(a, dict) else plain(a), 'uri': absolute(a.get('identifier'), url) if isinstance(a, dict) else None, 'links': catalog_links(a.get('links', []), url) if isinstance(a, dict) else []} for a in authors]
            belongs_to = meta.get('belongsTo', {})
            series = [{'name': plain(s.get('name')) if isinstance(s, dict) else plain(s), 'position': s.get('position') if isinstance(s, dict) else None, 'links': catalog_links(s.get('links', []), url) if isinstance(s, dict) else []} for s in named_values(belongs_to.get('series') if isinstance(belongs_to, dict) else None)]
            images = pub.get("images", [])
            image = absolute(images[0].get("href"), url) if images else None
            result["entries"].append({"id": meta.get("identifier") or download_links[0]["href"], "title": plain(meta.get("title")), "authors": [a['name'] for a in author_details], "author_details": author_details, "series": series, "related_links": catalog_links(pub.get('links', []), url), "languages": published_languages(meta.get('language')), "summary": plain(meta.get("description")), "cover_url": cover_url(image), "acquisitions": acquisitions, "unavailable_reason": unavailable_reason(download_links) if not acquisitions else None})
    return result


async def fetch(url: str, limit: int) -> tuple[bytes, str, str]:
    target = valid_url(url)
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": "Pereplet/0.1 personal-reader"}) as client:
        for _ in range(6):
            async with client.stream("GET", target) as response:
                if response.is_redirect:
                    target = valid_url(response.headers.get("location", ""), target)
                    continue
                response.raise_for_status()
                size = 0
                chunks = []
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > limit: raise ValueError("Ответ каталога превышает допустимый размер")
                    chunks.append(chunk)
                return b"".join(chunks), str(response.url), response.headers.get("content-type", "")
    raise ValueError("Слишком много перенаправлений каталога")


def search_template(template: str, query: str) -> str:
    value = template.replace("{searchTerms}", quote(query)).replace("{searchTerms?}", quote(query))
    value = value.replace("{?query}", "?query=" + quote(query)).replace("{query}", quote(query))
    value = re.sub(r"\{(?:count\??)\}", "30", value)
    value = re.sub(r"\{(?:startIndex\??|startPage\??)\}", "1", value)
    value = re.sub(r"\{(?:inputEncoding|outputEncoding)\??\}", "UTF-8", value)
    value = re.sub(r"\{atom:(?:author|contributor|title)\??\}", "", value)
    value = re.sub(r"\{[^{}]+\?\}", "", value)
    if "{" in value: raise ValueError("Этот шаблон поиска пока не поддерживается")
    return value


async def read_catalog(url: str, parser):
    # Some catalog servers return HTTP 200 with only an XML declaration, or a
    # truncated feed. Retry once, never turn an invalid response into an empty feed.
    for attempt in range(2):
        content, base, _ = await fetch(url, MAX_FEED)
        try:
            return parser(content, base)
        except CatalogResponseError as exc:
            if not exc.retryable or attempt:
                raise
        await asyncio.sleep(.25)


def opensearch_url(content: bytes, base: str) -> str:
    root = parse_xml(content, base)
    templates = [e.get("template") for e in root.iter() if isinstance(e.tag, str) and etree.QName(e).localname == "Url" and e.get("template") and ("atom" in e.get("type", "") or "opds" in e.get("type", ""))]
    if not templates:
        raise ValueError("Каталог не предоставил шаблон поиска")
    return urljoin(base, templates[0])


def http_error_detail(status: int) -> str:
    if status == 401:
        return "Этот раздел каталога требует входа. Авторизация в OPDS пока не поддерживается. Открытые разделы доступны без входа."
    if status == 403:
        return "Каталог запретил доступ к разделу (HTTP 403). Возможно, требуется вход. Авторизация в OPDS пока не поддерживается."
    return f"Каталог вернул HTTP {status}"


@router.post("/browse")
async def browse(body: Browse):
    try:
        target = body.url
        if body.query is not None:
            if "{" in target:
                target = search_template(target, body.query)
            else:
                template = await read_catalog(target, opensearch_url)
                target = search_template(template, body.query)
        feed = await read_catalog(target, parse_feed)
        return await asyncio.to_thread(annotate_local, feed)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, http_error_detail(exc.response.status_code)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Не удалось соединиться с каталогом. Проверьте адрес и подключение.") from exc
    except CatalogResponseError as exc:
        raise HTTPException(502, str(exc)) from exc
    except (ValueError, etree.XMLSyntaxError, TypeError, KeyError) as exc:
        raise HTTPException(400, str(exc)[:300]) from exc


@router.get("/cover")
async def cover(url: str):
    try:
        key = hashlib.sha256(url.encode()).hexdigest()
        if key not in _cover_cache:
            data, _, mime = await fetch(url, MAX_IMAGE)
            mime = mime.split(";")[0]
            # Raster only: downloaded SVG must never execute under our app's origin.
            if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}:
                raise ValueError("Обложка не является растровым изображением")
            data = await asyncio.to_thread(thumbnail, data)
            if len(_cover_cache) >= 40: _cover_cache.pop(next(iter(_cover_cache)))
            _cover_cache[key] = (data, "image/webp")
        data, mime = _cover_cache[key]
        return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
    except (ValueError, httpx.HTTPError, OSError, UnidentifiedImageError):
        raise HTTPException(404, "Обложка недоступна")


@router.post("/download")
async def download(body: Download):
    from . import library
    temp_path = None
    try:
        target = valid_url(body.url)
        existing = await asyncio.to_thread(acquired_book, target)
        if existing:
            return {"book": existing, "duplicate": True}
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": "Pereplet/0.1 personal-reader"}) as client:
            for _ in range(6):
                async with client.stream("GET", target) as response:
                    if response.is_redirect:
                        target = valid_url(response.headers.get("location", ""), target)
                        continue
                    response.raise_for_status()
                    mime = response.headers.get("content-type", "").split(";")[0]
                    name = body.filename or unquote(urlsplit(target).path.rsplit("/", 1)[-1])
                    if not name.lower().endswith((".fb2", ".fb2.zip", ".epub", ".txt", ".pdf", ".cbz", ".cbr")):
                        extensions = {"application/epub+zip": ".epub", "application/fb2+xml": ".fb2", "application/x-fictionbook+xml": ".fb2", "application/fb2+zip": ".fb2.zip", "application/x-fictionbook+zip": ".fb2.zip", "text/plain": ".txt", "application/pdf": ".pdf", "application/vnd.comicbook+zip": ".cbz", "application/x-cbz": ".cbz", "application/vnd.comicbook-rar": ".cbr", "application/x-cbr": ".cbr"}
                        ext = extensions.get((body.type or "").split(";")[0].strip().lower()) or extensions.get(mime.strip().lower())
                        if not ext: raise ValueError("Ссылка не содержит книгу поддерживаемого формата")
                        name = "download" + ext
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".download") as dest:
                        temp_path = Path(dest.name)
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_DOWNLOAD: raise ValueError("Файл больше 512 МБ; добавьте его с диска")
                            dest.write(chunk)
                    result = await asyncio.to_thread(library.import_path, temp_path, original_name=name)
                    await asyncio.to_thread(remember_acquisition, body.url, result['book']['id'])
                    return result
        raise ValueError("Слишком много перенаправлений")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, http_error_detail(exc.response.status_code)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Скачивание прервано. Можно попробовать ещё раз.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)[:300]) from exc
    finally:
        if temp_path: temp_path.unlink(missing_ok=True)
