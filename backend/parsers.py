"""Bounded, non-executing FB2/EPUB import into small reader documents."""
from __future__ import annotations

import base64
import codecs
import copy
import hashlib
import html
import io
import json
import mimetypes
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree as ET
from xml.parsers import expat

from lxml import html as lxml_html

MAX_EXPANDED = 2 * 1024**3
MAX_SINGLE = 1024**3
MAX_META = 8 * 1024**2
MAX_RESOURCE = 128 * 1024**2
CHUNK_TARGET = 45_000
CHUNK_HARD = 100_000
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif", "image/bmp", "image/svg+xml"}


class BookParseError(ValueError):
    pass


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()


def anchor(key: str) -> str:
    return "a-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def safe_zip_path(name: str) -> str:
    if "\\" in name or "\x00" in name or name.startswith("/"):
        raise BookParseError("Небезопасный путь внутри архива")
    parts = PurePosixPath(name).parts
    if any(p in {"..", ":"} or ":" in p for p in parts):
        raise BookParseError("Небезопасный путь внутри архива")
    return str(PurePosixPath(name))


def verify_zip(z: zipfile.ZipFile) -> None:
    total = 0
    if len(z.infolist()) > 30_000:
        raise BookParseError("В архиве слишком много файлов")
    for info in z.infolist():
        safe_zip_path(info.filename)
        if info.file_size > MAX_SINGLE:
            raise BookParseError("Один файл в архиве превышает лимит 1 ГБ")
        if info.flag_bits & 1:
            raise BookParseError("Зашифрованные архивы пока не поддерживаются")
        total += info.file_size
    if total > MAX_EXPANDED:
        raise BookParseError("Распакованная книга превышает лимит 2 ГБ")


def xml_tree(raw: bytes) -> ET.Element:
    if len(raw) > MAX_META or re.search(br"<!\s*(DOCTYPE|ENTITY)\b", raw.replace(b"\x00", b""), re.I):
        raise BookParseError("Небезопасные или слишком большие XML-метаданные")
    return ET.fromstring(raw)


def text_content(el: ET.Element) -> str:
    return " ".join(" ".join(el.itertext()).split())


def clean_svg(raw: bytes) -> bytes:
    root = xml_tree(raw)
    bad = {"script", "foreignobject", "iframe", "object", "embed", "style", "animate", "set", "animatetransform", "animatemotion"}
    for parent in root.iter():
        for child in list(parent):
            if local_name(child.tag) in bad:
                parent.remove(child)
        for key, value in list(parent.attrib.items()):
            k = local_name(key)
            if k.startswith("on") or k == "style" or (k in {"href", "src"} and not value.startswith("#")):
                del parent.attrib[key]
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class Writer:
    """Writes bounded HTML chunks, preserving text identities across pagination."""

    def __init__(self, destination: Path, book_id: str):
        self.destination = destination
        self.book_id = book_id
        (destination / "chapters").mkdir(parents=True, exist_ok=True)
        (destination / "resources").mkdir(parents=True, exist_ok=True)
        self.parts: list[str] = []
        self.stack: list[tuple[str, str]] = []
        self.note_anchors: dict[int, str] = {}
        self.paragraph_stack: list[dict] = []
        self.paragraphs: list[dict] = []
        self.chapters: list[dict] = []
        self.anchors: dict[str, int] = {}
        self.resources: dict[str, str] = {}
        self.length = 0
        self.size = 0
        self.counter = 0
        self.title = "Начало"
        self.has_content = False

    def url(self, name: str) -> str:
        return f"/api/books/{self.book_id}/resources/{quote(name, safe='/')}"

    def push(self, value: str):
        self.parts.append(value)
        self.size += len(value)

    def mark(self, key: str):
        self.anchors[key] = len(self.chapters)

    def start(self, tag: str, attrs: dict | None = None, *, paragraph=False):
        attrs = dict(attrs or {})
        if paragraph and not attrs.get("id"):
            self.counter += 1
            attrs["id"] = f"p-{self.counter:07d}"
        if "id" in attrs:
            self.mark(attrs["id"])
        rendered = "".join(f' {html.escape(str(k), quote=True)}="{html.escape(str(v), quote=True)}"' for k, v in attrs.items())
        self.push(f"<{tag}{rendered}>")
        if tag in {"img", "br", "hr"}:
            if tag == "img":
                self.has_content = True
            return
        clean_attrs = {k: v for k, v in attrs.items() if k != "id"}
        reopen = f"<{tag}" + "".join(f' {k}="{html.escape(str(v), quote=True)}"' for k, v in clean_attrs.items()) + ">"
        self.stack.append((tag, reopen))
        if attrs.get("role") in {"doc-footnote", "doc-endnote"} and attrs.get("id"):
            self.note_anchors[len(self.stack)] = attrs["id"]
        if paragraph:
            self.paragraph_stack.append({"id": attrs["id"], "text": [], "depth": len(self.stack)})

    def end(self, tag: str):
        if not any(t == tag for t, _ in self.stack):
            return
        while self.stack:
            current, _ = self.stack.pop()
            self.note_anchors.pop(len(self.stack) + 1, None)
            while self.paragraph_stack and self.paragraph_stack[-1]["depth"] > len(self.stack):
                p = self.paragraph_stack.pop()
                text = " ".join("".join(p["text"]).split())
                if text:
                    self.paragraphs.append({"id": p["id"], "text": text})
            self.push(f"</{current}>")
            if current == tag:
                break
        if self.size >= CHUNK_TARGET and not self.paragraph_stack:
            self.flush()

    def text(self, value: str):
        if not value:
            return
        # Split enormous individual paragraphs too, while ordinary paragraphs stay intact.
        for pos in range(0, len(value), 8192):
            part = value[pos:pos + 8192]
            self.push(html.escape(part))
            self.length += len(part)
            self.has_content |= bool(part.strip())
            if self.paragraph_stack:
                self.paragraph_stack[-1]["text"].append(part)
            if self.size > CHUNK_HARD:
                self.flush(hard=True)

    def set_title(self, value: str):
        value = " ".join(value.split())[:250]
        if value:
            self.title = value

    def break_section(self, title: str | None = None):
        if self.has_content:
            self.flush()
        if title:
            self.set_title(title)

    def flush(self, hard=False):
        if not self.has_content:
            return
        paragraphs = self.paragraphs[:]
        if hard:
            for p in self.paragraph_stack:
                value = " ".join("".join(p["text"]).split())
                if value:
                    paragraphs.append({"id": p["id"], "text": value})
        body = "".join(self.parts) + "".join(f"</{t}>" for t, _ in reversed(self.stack))
        idx = len(self.chapters)
        data = {"html": body, "title": self.title, "index": idx, "paragraphs": paragraphs, "continued_notes": list(self.note_anchors.values())}
        (self.destination / "chapters" / f"{idx}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.chapters.append({"index": idx, "title": self.title, "id": f"chapter-{idx}", "length": self.length})
        self.parts = [opening for _, opening in self.stack]
        self.size = sum(map(len, self.parts))
        self.length = 0
        self.paragraphs = []
        self.has_content = False
        if hard:
            for p in self.paragraph_stack:
                self.counter += 1
                p["id"] = f"p-{self.counter:07d}"
                p["text"] = []
                self.mark(p["id"])
                self.push(f'<span id="{p["id"]}"></span>')

    def finish(self):
        self.flush(hard=True)
        if not self.chapters:
            raise BookParseError("В книге не найдено читаемого текста или изображений")


def feed_xml_stream(stream, parser):
    head = stream.read(4096)
    if head.removeprefix(codecs.BOM_UTF8).lstrip().lower().startswith(b"{\\rtf"):
        raise BookParseError("Внутри файла находится RTF, а не FB2. Переименование расширения не преобразует формат. Сохраните книгу как FB2, EPUB или TXT и добавьте её снова.")
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    else:
        m = re.search(br"encoding\s*=\s*['\"]([^'\"]+)", head[:512], re.I)
        encoding = m.group(1).decode("ascii") if m else "utf-8-sig"
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    except LookupError as e:
        raise BookParseError(f"Неизвестная кодировка: {encoding}") from e
    total = 0
    raw = head
    while raw:
        total += len(raw)
        if total > MAX_SINGLE:
            raise BookParseError("Книга превышает лимит 1 ГБ")
        parser.Parse(decoder.decode(raw), False)
        raw = stream.read(65536)
    parser.Parse(decoder.decode(b"", final=True), True)


class FB2Parser:
    def __init__(self, writer: Writer):
        self.w = writer
        self.stack: list[str] = []
        self.rendered: list[str | None] = []
        self.meta = {"title": "", "authors": [], "annotation": "", "language": "ru", "series": "", "series_index": ""}
        self.author: dict[str, str] | None = None
        self.capture: list[dict] = []
        self.binary = None
        self.binary_tail = ""
        self.binary_size = 0
        self.cover_id = None
        self.heading_text: list[str] | None = None
        self.body_depth = 0
        self.notes_body = False

    def binary_name(self, ident: str):
        return "images/" + hashlib.sha256(ident.encode()).hexdigest()[:32] + ".img"

    def start(self, tag, attrs):
        tag = local_name(tag)
        attrs = {local_name(k): v for k, v in attrs.items()}
        self.stack.append(tag)
        self.rendered.append(None)
        in_title_info = "title-info" in self.stack and "description" in self.stack
        if tag == "binary":
            name = self.binary_name(attrs.get("id", "binary"))
            path = self.w.destination / "resources" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            self.binary = path.open("wb")
            self.binary_tail = ""
            self.binary_size = 0
            kind = attrs.get("content-type", "application/octet-stream").split(";")[0]
            self.w.resources[name] = kind
            return
        if in_title_info:
            if tag == "author":
                self.author = {}
            if tag in {"book-title", "lang", "annotation", "first-name", "middle-name", "last-name", "nickname"}:
                self.capture.append({"tag": tag, "depth": len(self.stack), "text": []})
            if tag == "sequence":
                self.meta["series"] = attrs.get("name", "")
                self.meta["series_index"] = attrs.get("number", "")
            if tag == "image" and "coverpage" in self.stack:
                self.cover_id = attrs.get("href", "").lstrip("#")
        if tag == "body":
            self.body_depth = len(self.stack)
            self.notes_body = attrs.get("name", "").lower() in {"notes", "comments", "footnotes", "endnotes", "примечания", "сноски", "комментарии"}
            self.w.break_section("Примечания" if attrs.get("name") else "Начало")
            return
        if not self.body_depth:
            return
        if tag == "section":
            if self.w.size > 2500:
                self.w.break_section()
            at = {"id": anchor(attrs["id"])} if attrs.get("id") else {}
            if self.notes_body and attrs.get("id"):
                at["role"] = "doc-footnote"
            self.w.start("section", at)
            self.rendered[-1] = "section"
            return
        if tag == "title":
            self.heading_text = []
        if tag == "image":
            ident = attrs.get("href", "").lstrip("#")
            if ident:
                self.w.start("img", {"src": self.w.url(self.binary_name(ident)), "alt": attrs.get("alt", "Иллюстрация"), "loading": "lazy"})
            return
        mapped = {"p": "h2" if "title" in self.stack else "p", "v": "p", "stanza": "div", "poem": "div", "title": "div", "subtitle": "h3", "strong": "strong", "emphasis": "em", "strikethrough": "s", "sup": "sup", "sub": "sub", "code": "code", "cite": "blockquote", "epigraph": "blockquote", "text-author": "p", "a": "a", "table": "table", "tr": "tr", "td": "td", "th": "th", "empty-line": "br"}.get(tag)
        if mapped:
            at = {"id": anchor(attrs["id"])} if attrs.get("id") else {}
            if tag in {"poem", "stanza", "v", "title", "text-author"}:
                at["class"] = "book-" + tag
            if tag == "a":
                href = attrs.get("href", "")
                if href.startswith("#"):
                    at["href"] = "#" + anchor(href[1:])
                    if attrs.get("type", "").lower() == "note":
                        at["role"] = "doc-noteref"
                elif urlsplit(href).scheme in {"https", "http", "mailto"}:
                    at.update(href=href, target="_blank", rel="noopener noreferrer")
            if tag in {"td", "th"}:
                for key in ("colspan", "rowspan"):
                    if attrs.get(key, "").isdigit():
                        at[key] = str(min(100, int(attrs[key])))
            self.w.start(mapped, at, paragraph=mapped in {"p", "h2", "h3", "td", "th"})
            if mapped != "br":
                self.rendered[-1] = mapped

    def data(self, text):
        if self.binary:
            clean = re.sub(r"\s+", "", text)
            self.binary_tail += clean
            usable = len(self.binary_tail) // 4 * 4
            if usable:
                raw = base64.b64decode(self.binary_tail[:usable], validate=True)
                self.binary_size += len(raw)
                if self.binary_size > MAX_RESOURCE:
                    raise BookParseError("Иллюстрация превышает лимит 128 МБ")
                self.binary.write(raw)
                self.binary_tail = self.binary_tail[usable:]
            return
        for cap in self.capture:
            if sum(map(len, cap["text"])) < 100_000:
                cap["text"].append(text)
        if self.body_depth:
            self.w.text(text)
            if self.heading_text is not None:
                self.heading_text.append(text)

    def end(self, tag):
        tag = local_name(tag)
        if tag == "binary" and self.binary:
            if self.binary_tail:
                self.binary.write(base64.b64decode(self.binary_tail, validate=True))
            binary_path = Path(self.binary.name)
            self.binary.close()
            self.binary = None
            resource = binary_path.relative_to(self.w.destination / "resources").as_posix()
            if self.w.resources.get(resource) == "image/svg+xml":
                try:
                    binary_path.write_bytes(clean_svg(binary_path.read_bytes()))
                except (ET.ParseError, BookParseError):
                    binary_path.unlink(missing_ok=True)
                    self.w.resources.pop(resource, None)
        for cap in list(self.capture):
            if cap["depth"] == len(self.stack):
                value = " ".join("".join(cap["text"]).split())
                if cap["tag"] in {"book-title", "lang", "annotation"}:
                    key = {"book-title": "title", "lang": "language", "annotation": "annotation"}[cap["tag"]]
                    self.meta[key] = value
                elif self.author is not None:
                    self.author[cap["tag"]] = value
                self.capture.remove(cap)
        if tag == "author" and self.author is not None:
            name = " ".join(self.author[k] for k in ("first-name", "middle-name", "last-name") if self.author.get(k))
            if name or self.author.get("nickname"):
                self.meta["authors"].append(name or self.author["nickname"])
            self.author = None
        rendered = self.rendered.pop()
        if rendered:
            self.w.end(rendered)
        if tag == "title" and self.heading_text is not None:
            self.w.set_title("".join(self.heading_text))
            self.heading_text = None
        if tag == "body":
            self.w.break_section()
            self.body_depth = 0
            self.notes_body = False
        self.stack.pop()

    def parse(self, stream):
        parser = expat.ParserCreate(namespace_separator="}")
        parser.StartElementHandler = self.start
        parser.EndElementHandler = self.end
        parser.CharacterDataHandler = self.data
        def forbidden(*_):
            raise BookParseError("Внешние сущности и DTD в книгах не поддерживаются")
        parser.StartDoctypeDeclHandler = forbidden
        parser.EntityDeclHandler = forbidden
        parser.ExternalEntityRefHandler = forbidden
        try:
            feed_xml_stream(stream, parser)
        finally:
            if self.binary:
                self.binary.close()
        if self.cover_id:
            self.meta["cover_resource"] = self.binary_name(self.cover_id)
        return self.meta


class EPUBHTML(HTMLParser):
    SAFE = {"p", "div", "section", "article", "aside", "span", "h1", "h2", "h3", "h4", "h5", "h6", "em", "i", "strong", "b", "u", "s", "sup", "sub", "blockquote", "pre", "code", "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th", "caption", "a", "br", "hr", "img", "figure", "figcaption"}
    BLOCKED = {"script", "style", "iframe", "object", "embed", "form", "head", "svg", "math", "noscript"}

    def __init__(self, writer: Writer, resource: str, resource_map: dict[str, str]):
        super().__init__(convert_charrefs=True)
        self.w = writer
        self.resource = resource
        self.resource_map = resource_map
        self.skip = 0
        self.opened: list[tuple[str, str | None]] = []
        self.w.start("section", {"id": anchor(resource)})

    def resolve(self, link):
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc:
            return None, parsed.fragment
        path = posixpath.normpath(posixpath.join(posixpath.dirname(self.resource), unquote(parsed.path))) if parsed.path else self.resource
        if path.startswith("../") or path.startswith("/"):
            return None, parsed.fragment
        return path, unquote(parsed.fragment)

    def handle_starttag(self, tag, attributes):
        tag = tag.lower()
        attrs = dict(attributes)
        if self.skip:
            if tag not in {"img", "br", "hr", "meta", "link", "input", "source", "wbr"}:
                self.skip += 1
            return
        if tag in self.BLOCKED:
            self.skip = 1
            return
        if tag not in self.SAFE:
            return
        at = {}
        if attrs.get("id"):
            at["id"] = anchor(self.resource + "#" + attrs["id"])
        semantic = set((attrs.get("epub:type", "") + " " + attrs.get("role", "")).lower().split())
        if tag == "a" and semantic & {"noteref", "doc-noteref"}:
            at["role"] = "doc-noteref"
        elif semantic & {"footnote", "doc-footnote", "endnote", "doc-endnote"}:
            at["role"] = "doc-endnote" if semantic & {"endnote", "doc-endnote"} else "doc-footnote"
        if tag == "a" and attrs.get("href"):
            value = attrs["href"]
            parsed = urlsplit(value)
            if parsed.scheme in {"https", "http", "mailto"}:
                at.update(href=value, target="_blank", rel="noopener noreferrer")
            elif not parsed.scheme:
                path, frag = self.resolve(value)
                if path:
                    at["href"] = "#" + anchor(path + ("#" + frag if frag else ""))
        if tag == "img":
            path, _ = self.resolve(attrs.get("src", ""))
            if path not in self.resource_map:
                return
            at.update(src=self.w.url(self.resource_map[path]), alt=attrs.get("alt", "Иллюстрация"), loading="lazy")
        for key in ("colspan", "rowspan"):
            if str(attrs.get(key, "")).isdigit():
                at[key] = str(min(int(attrs[key]), 100))
        self.w.start(tag, at, paragraph=tag in {"p", "h1", "h2", "h3", "h4", "li", "td", "th", "figcaption"})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in {"img", "br", "hr", "meta", "link", "input", "source", "wbr"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= 1
            return
        if tag in self.SAFE and tag not in {"img", "br", "hr"}:
            self.w.end(tag)

    def handle_data(self, data):
        if not self.skip:
            self.w.text(data)

    def close(self):
        super().close()
        while self.w.stack:
            self.w.end(self.w.stack[-1][0])


def parse_epub(stream_path: Path, writer: Writer) -> dict:
    with zipfile.ZipFile(stream_path) as z:
        verify_zip(z)
        container = xml_tree(z.read("META-INF/container.xml"))
        package = next((e.attrib.get("full-path") for e in container.iter() if local_name(e.tag) == "rootfile"), None)
        if not package:
            raise BookParseError("EPUB не содержит package document")
        package = safe_zip_path(package)
        opf = xml_tree(z.read(package))
        base = posixpath.dirname(package)
        meta = {"title": "", "authors": [], "annotation": "", "language": "", "series": "", "series_index": ""}
        manifest = {}
        spine = []
        cover_id = None
        for el in opf.iter():
            tag = local_name(el.tag)
            if tag == "title" and not meta["title"]:
                meta["title"] = text_content(el)
            elif tag == "creator":
                meta["authors"].append(text_content(el))
            elif tag == "language":
                meta["language"] = text_content(el)
            elif tag == "description":
                meta["annotation"] = text_content(el)[:100000]
            elif tag == "meta":
                name = el.attrib.get("name", "")
                prop = el.attrib.get("property", "")
                if name == "cover":
                    cover_id = el.attrib.get("content")
                elif name in {"calibre:series", "calibre:series_index"}:
                    meta["series" if name.endswith(":series") else "series_index"] = el.attrib.get("content", "")
                elif prop == "belongs-to-collection" and not meta["series"]:
                    meta["series"] = text_content(el)
                elif prop == "group-position" and not meta["series_index"]:
                    meta["series_index"] = text_content(el)
            elif tag == "item":
                path = posixpath.normpath(posixpath.join(base, unquote(el.attrib.get("href", ""))))
                safe_zip_path(path)
                manifest[el.attrib.get("id", path)] = {"path": path, "type": el.attrib.get("media-type", ""), "properties": el.attrib.get("properties", "")}
                if "cover-image" in el.attrib.get("properties", "").split():
                    cover_id = el.attrib.get("id")
            elif tag == "itemref":
                spine.append(el.attrib.get("idref"))
        resources = {}
        for ident, item in manifest.items():
            path, kind = item["path"], item["type"]
            if kind not in IMAGE_TYPES or path not in z.namelist():
                continue
            info = z.getinfo(path)
            if info.file_size > MAX_RESOURCE:
                continue
            name = "images/" + hashlib.sha256(path.encode()).hexdigest()[:32] + (PurePosixPath(path).suffix.lower() or ".img")
            destination = writer.destination / "resources" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if kind == "image/svg+xml":
                try:
                    destination.write_bytes(clean_svg(z.read(path)))
                except (ET.ParseError, BookParseError):
                    continue
            else:
                with z.open(path) as src, destination.open("wb") as out:
                    while part := src.read(65536):
                        out.write(part)
            resources[path] = name
            writer.resources[name] = kind
            if ident == cover_id:
                meta["cover_resource"] = name
        # Fall back only to a recognisable cover, never to an arbitrary decoration.
        if not meta.get("cover_resource"):
            for path, name in resources.items():
                if "cover" in PurePosixPath(path).stem.lower():
                    meta["cover_resource"] = name
                    break
        labels = {}
        for item in manifest.values():
            if item["type"] == "application/x-dtbncx+xml":
                try:
                    ncx = xml_tree(z.read(item["path"]))
                    for point in ncx.iter():
                        if local_name(point.tag) != "navpoint":
                            continue
                        content = next((x for x in point if local_name(x.tag) == "content"), None)
                        label = next((text_content(x) for x in point if local_name(x.tag) == "navlabel"), "")
                        if content is not None:
                            p = posixpath.normpath(posixpath.join(posixpath.dirname(item["path"]), unquote(content.attrib.get("src", "").split("#")[0])))
                            labels[p] = label
                except (KeyError, ET.ParseError, BookParseError):
                    pass
        for n, ident in enumerate(spine):
            item = manifest.get(ident)
            if not item or item["path"] not in z.namelist() or item["type"] not in {"application/xhtml+xml", "text/html"}:
                continue
            writer.break_section(labels.get(item["path"]) or ("Обложка" if n == 0 and "cover" in item["path"].lower() else f"Раздел {n+1}"))
            parser = EPUBHTML(writer, item["path"], resources)
            with z.open(item["path"]) as src:
                head = src.read(4096)
                match = re.search(br"(?:encoding\s*=|charset\s*=)\s*['\"]?([\w-]+)", head[:1024], re.I)
                enc = match.group(1).decode("ascii") if match else "utf-8-sig"
                try:
                    dec = codecs.getincrementaldecoder(enc)(errors="replace")
                except LookupError:
                    dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
                parser.feed(dec.decode(head))
                while raw := src.read(65536):
                    parser.feed(dec.decode(raw))
                parser.feed(dec.decode(b"", final=True))
            parser.close()
            writer.flush()
        return meta


def extract_note(source: str, ident: str, book_id: str, continued_notes: list[str] | None = None) -> dict | None:
    """Isolate one anchored note from one derived chapter, never a notes collection."""
    if len(source) > 1_000_000:
        return None
    document = lxml_html.fragment_fromstring(source, create_parent="div")
    matches = document.xpath('.//*[@id=$ident]', ident=ident)
    if not matches:
        return None
    target = matches[0]
    note_roles = {"doc-footnote", "doc-endnote"}
    marker = re.compile(r"^[\s\[\(]*\d{1,5}[a-zа-я]?[\s\]\).]*$|^[*†‡]{1,3}$", re.I)
    text = lambda node: " ".join(" ".join(node.itertext()).split())
    is_note = lambda node: bool(set(node.get("role", "").split()) & note_roles)
    candidate = next((node for node in [target, *target.iterancestors()] if is_note(node)), None)
    explicit = candidate is not None

    if candidate is None:
        if target.tag in {"p", "li", "blockquote", "section", "article", "aside", "div"}:
            candidate = target
        elif target.tag not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            candidate = next((node for node in target.iterancestors() if node.tag in {"p", "li", "blockquote"}), None)

    # Legacy EPUBs sometimes put a number/empty anchor before its following paragraph.
    if candidate is None or (candidate.tag in {"p", "li"} and marker.fullmatch(text(candidate))):
        start = candidate if candidate is not None else target
        if start.tag.startswith("h") and not marker.fullmatch(text(start)):
            return None
        if start is target and target.tag not in {"h1", "h2", "h3", "h4", "h5", "h6", "a", "span"}:
            return None
        candidate = lxml_html.Element("div")
        for count, node in enumerate([start, *start.itersiblings()]):
            if count and (is_note(node) or node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
                          or node.get("id", "").startswith("a-")
                          or node.xpath('.//*[starts-with(@id,"a-")]')):
                break
            if count >= 12:
                return None
            candidate.append(copy.deepcopy(node))

    # A chapter/body/outer notes section must never become a hundred-note popup.
    if candidate.get("id") in (continued_notes or []):
        return None
    descendants = list(candidate.iterdescendants())
    if any(is_note(node) or node.tag in {"section", "article", "aside"} for node in descendants):
        return None
    if not explicit:
        anchored = [node for node in descendants if node.get("id", "").startswith("a-")]
        if len(anchored) > 1 or len(candidate.xpath('.//p | .//li')) > 12:
            return None
        if candidate.tag in {"section", "article"}:
            heading = candidate.xpath('.//h1 | .//h2 | .//h3 | .//h4')
            if not heading or not marker.fullmatch(text(heading[0])):
                return None
    if len(descendants) > 250:
        return None
    value = copy.deepcopy(candidate)
    value.tail = None
    blocked = EPUBHTML.BLOCKED | {"button", "input", "textarea", "select", "audio", "video", "source", "link", "meta"}
    resource_prefix = f"/api/books/{book_id}/resources/"
    for node in [value, *value.iterdescendants()]:
        if not isinstance(node.tag, str):
            if node.getparent() is not None:
                node.getparent().remove(node)
            continue
        if node.tag in blocked:
            if node is value:
                return None
            node.drop_tree()
            continue
        if node.tag not in EPUBHTML.SAFE:
            if node is value:
                node.tag = "div"
            else:
                node.drop_tag()
                continue
        attrs = dict(node.attrib)
        node.attrib.clear()  # No duplicate IDs, event handlers, styles or custom HTML attributes.
        if node.tag == "a":
            href = attrs.get("href", "")
            if href.startswith("#") and re.fullmatch(r"#[A-Za-z0-9_-]{1,100}", href):
                node.set("href", href)
            elif urlsplit(href).scheme in {"http", "https", "mailto"}:
                node.set("href", href)
                node.set("target", "_blank")
                node.set("rel", "noopener noreferrer")
        if node.tag == "img":
            if attrs.get("src", "").startswith(resource_prefix):
                node.set("src", attrs["src"])
                node.set("alt", attrs.get("alt", "Иллюстрация"))
                node.set("loading", "lazy")
            else:
                node.drop_tree()
        for key in ("colspan", "rowspan"):
            if attrs.get(key, "").isdigit():
                node.set(key, str(min(100, int(attrs[key]))))
    plain = text(value)
    rendered = lxml_html.tostring(value, encoding="unicode", with_tail=False)
    if not plain or marker.fullmatch(plain) or len(plain) > 12_000 or len(rendered) > 32_000:
        return None
    headings = value.xpath('.//h1 | .//h2 | .//h3 | .//h4')
    title = "Примечание " + text(headings[0]).strip("[](). ") if headings and marker.fullmatch(text(headings[0])) else "Примечание"
    return {"html": rendered, "text": plain, "title": title}


def text_encoding(source: Path) -> tuple[str, str, list[str]]:
    """Prefer declared Unicode; an explicit warning accompanies the legacy fallback."""
    if source.stat().st_size > MAX_SINGLE:
        raise BookParseError("Книга превышает лимит 1 ГБ")
    with source.open("rb") as stream:
        head = stream.read(4096)
    if head.removeprefix(codecs.BOM_UTF8).lstrip().lower().startswith(b"{\\rtf"):
        raise BookParseError("Файл содержит RTF, а не обычный TXT. Сохраните его как обычный текст UTF-8 и добавьте снова.")
    if head.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        raise BookParseError("TXT в UTF-32 пока не поддерживается. Сохраните его в UTF-8 или UTF-16 с BOM.")
    if head.startswith(codecs.BOM_UTF8):
        return "utf-8-sig", "UTF-8 (BOM)", []
    if head.startswith(codecs.BOM_UTF16_LE):
        return "utf-16", "UTF-16 LE", []
    if head.startswith(codecs.BOM_UTF16_BE):
        return "utf-16", "UTF-16 BE", []
    # Check the whole input, not just a sample: a later Cyrillic paragraph may
    # determine the encoding. Both passes have bounded memory and strict decoding.
    try:
        with source.open("r", encoding="utf-8", errors="strict") as stream:
            while stream.read(65536):
                pass
        return "utf-8", "UTF-8", []
    except UnicodeDecodeError:
        return "cp1251", "Windows-1251", [
            "TXT прочитан как Windows-1251, поскольку он не является корректным UTF-8. Если буквы отображаются неверно, пересохраните исходный TXT в UTF-8."
        ]


def parse_txt(source: Path, name: str, writer: Writer) -> dict:
    encoding, label, warnings = text_encoding(source)
    title = Path(name).stem
    writer.set_title(title)
    paragraph_open = False
    line_has_text = False
    pending_newline = False
    try:
        with source.open("r", encoding=encoding, errors="strict", newline=None) as stream:
            while chunk := stream.read(65536):
                if re.search(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f]", chunk):
                    raise BookParseError("TXT содержит двоичные или управляющие символы. Для UTF-16 нужен BOM; пересохраните текст в UTF-8 или UTF-16 с BOM.")
                lines = chunk.replace("\f", "\n\n").split("\n")
                for index, part in enumerate(lines):
                    if part.strip():
                        if not paragraph_open:
                            writer.start("p", paragraph=True)
                            paragraph_open = True
                        elif pending_newline:
                            writer.text("\n")
                        pending_newline = False
                        writer.text(part)
                        line_has_text = True
                    elif paragraph_open and line_has_text:
                        writer.text(part)
                    if index < len(lines) - 1:
                        if not line_has_text and paragraph_open:
                            writer.end("p")
                            paragraph_open = False
                            pending_newline = False
                        elif paragraph_open:
                            pending_newline = True
                        line_has_text = False
    except UnicodeDecodeError as exc:
        raise BookParseError(f"TXT не соответствует кодировке {label}; текст не был заменён повреждёнными символами. Пересохраните файл в UTF-8.") from exc
    if paragraph_open:
        writer.end("p")
    return {"title": title, "authors": [], "annotation": "", "language": "", "series": "", "series_index": "",
            "text_encoding": label, "import_warnings": warnings}


def parse_book(source: Path, name: str, destination: Path, book_id: str) -> dict:
    writer = Writer(destination, book_id)
    lower = name.lower()
    try:
        if lower.endswith(".epub"):
            meta = parse_epub(source, writer)
            fmt = "EPUB"
        elif lower.endswith(".txt"):
            meta = parse_txt(source, name, writer)
            fmt = "TXT"
        elif lower.endswith(".fb2"):
            with source.open("rb") as stream:
                meta = FB2Parser(writer).parse(stream)
            fmt = "FB2"
        elif lower.endswith((".fb2.zip", ".zip")):
            with zipfile.ZipFile(source) as z:
                verify_zip(z)
                items = [x for x in z.infolist() if x.filename.lower().endswith(".fb2") and not x.is_dir()]
                if len(items) != 1:
                    raise BookParseError("FB2.zip должен содержать одну книгу FB2; архивы из нескольких книг пока распакуйте перед импортом")
                with z.open(items[0]) as stream:
                    meta = FB2Parser(writer).parse(stream)
            fmt = "FB2.zip"
        else:
            raise BookParseError("Поддерживаются FB2, FB2.zip, EPUB и TXT")
        writer.finish()
    except (zipfile.BadZipFile, KeyError, expat.ExpatError, UnicodeError, ET.ParseError, ValueError) as exc:
        if isinstance(exc, BookParseError):
            raise
        raise BookParseError("Не удалось разобрать книгу: " + str(exc)[:180]) from exc
    meta.update(format=fmt, chapters=writer.chapters, anchors=writer.anchors, resources=writer.resources)
    if not meta["title"]:
        meta["title"] = name.removesuffix(".zip").rsplit(".", 1)[0]
    return meta
