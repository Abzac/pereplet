"""Local managed library. Original files are immutable; reader assets are derived."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .parsers import BookParseError, parse_book, extract_note, IMAGE_TYPES

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PEREPLET_DATA_DIR", str(APP_DIR / "data"))).resolve()
_lock = threading.RLock()
STATUSES = {"unread", "reading", "finished", "want", "planned", "read"}


def now():
    return datetime.now(timezone.utc).isoformat()


def init():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "books").mkdir(exist_ok=True)
    (DATA_DIR / "tmp").mkdir(exist_ok=True)
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS books (
          id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, metadata TEXT NOT NULL,
          added_at TEXT NOT NULL, last_opened TEXT, progress REAL NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'unread', chapter INTEGER NOT NULL DEFAULT 0,
          locator TEXT NOT NULL DEFAULT 'null', reading_settings TEXT NOT NULL DEFAULT '{}',
          bookmarks TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS catalogs (id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL, added_at TEXT NOT NULL);
        """)


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR / "library.sqlite", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=30000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _public(row, detail=False):
    meta = json.loads(row["metadata"])
    result = {k: v for k, v in meta.items() if k not in {"resources", "chapters", "anchors", "original_file", "cover_resource"}}
    result.update(id=row["id"], added_at=row["added_at"], last_opened=row["last_opened"], progress=row["progress"], status=row["status"], chapter=row["chapter"], locator=json.loads(row["locator"]), reading_settings=json.loads(row["reading_settings"]), bookmarks=json.loads(row["bookmarks"]))
    result["author"] = ", ".join(meta.get("authors") or []) or "Автор не указан"
    result["media_type"] = meta.get("media_type") if meta.get("media_type") in {"book", "comic"} else ("comic" if meta.get("format") in {"CBZ", "CBR"} else "book")
    result["archived"] = meta.get("archived") is True
    result["is_reader_guide"] = (meta.get("format") == "FB2" and meta.get("title") == "Переплёт. Руководство читателя" and meta.get("authors") == ["Переплёт"])
    result["chapter_count"] = len(meta.get("chapters", []))
    cover = meta.get("cover_resource")
    result["cover_url"] = f'/api/books/{row["id"]}/resources/{quote(cover, safe="/")}' if cover else None
    if detail:
        result["chapters"] = meta.get("chapters", [])
        result["anchors"] = meta.get("anchors", {})
    return result


def list_books():
    init()
    with connect() as db:
        return [_public(r) for r in db.execute("SELECT * FROM books ORDER BY added_at DESC")]


def get_book(book_id, detail=True):
    init()
    with connect() as db:
        row = db.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if row is None:
            raise KeyError("Книга не найдена")
        return _public(row, detail=detail)


def _book_dir(book_id):
    if not re.fullmatch(r"[a-f0-9]{32}", str(book_id)):
        raise KeyError("Книга не найдена")
    path = (DATA_DIR / "books" / book_id).resolve()
    if path.parent != (DATA_DIR / "books").resolve():
        raise ValueError("Неверный путь книги")
    return path


def get_chapter(book_id, index):
    book = get_book(book_id)
    if index < 0 or index >= book["chapter_count"]:
        raise KeyError("Раздел не найден")
    path = _book_dir(book_id) / "chapters" / f"{index}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["count"] = book["chapter_count"]
    return data


def get_page(book_id, index, width=1600):
    init()
    with connect() as db:
        row = db.execute("SELECT metadata FROM books WHERE id=?", (book_id,)).fetchone()
    if row is None:
        raise KeyError("Книга не найдена")
    from .paged import render_page
    return render_page(_book_dir(book_id), json.loads(row["metadata"]), index, width)


def get_note(book_id, anchor_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", anchor_id):
        raise KeyError("Примечание не найдено")
    book = get_book(book_id)
    index = book.get("anchors", {}).get(anchor_id)
    if type(index) is not int or not 0 <= index < book["chapter_count"]:
        raise KeyError("Примечание не найдено")
    path = _book_dir(book_id) / "chapters" / f"{index}.json"
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise KeyError("Примечание нельзя показать отдельно; откройте его раздел")
    chapter = get_chapter(book_id, index)
    if anchor_id in chapter.get("continued_notes", []):
        raise KeyError("Длинное примечание продолжается в следующем разделе")
    note = extract_note(chapter.get("html", ""), anchor_id, book_id, chapter.get("continued_notes", []))
    if note is None:
        raise KeyError("Примечание нельзя показать отдельно; откройте его раздел")
    return {"anchor": anchor_id, "chapter": index, **note}


def resource_path(book_id, resource):
    init()
    with connect() as db:
        row = db.execute("SELECT metadata FROM books WHERE id=?", (book_id,)).fetchone()
    if row is None:
        raise KeyError("Книга не найдена")
    resources = json.loads(row["metadata"]).get("resources", {})
    if resource not in resources:
        raise KeyError("Ресурс не найден")
    root = (_book_dir(book_id) / "resources").resolve()
    path = (root / resource).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise KeyError("Ресурс не найден")
    kind = resources[resource]
    if kind not in IMAGE_TYPES:
        # Only allow actual image files to render from book-provided MIME declarations.
        try:
            from PIL import Image
            with Image.open(path) as img:
                kind = Image.MIME.get(img.format, "application/octet-stream")
        except Exception:
            raise KeyError("Неподдерживаемый ресурс")
    return path, kind


def _cover_thumbnail(destination, meta):
    name = meta.get("cover_resource")
    if not name or name not in meta["resources"]:
        meta.pop("cover_resource", None)
        return
    source = destination / "resources" / name
    if not source.is_file():
        meta.pop("cover_resource", None)
        return
    try:
        from PIL import Image, ImageOps
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail((600, 900), Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA", "P"}:
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                image = Image.alpha_composite(background, rgba).convert("RGB")
            else:
                image = image.convert("RGB")
            target = "cover.jpg"
            image.save(destination / "resources" / target, "JPEG", quality=88, optimize=True)
            meta["resources"][target] = "image/jpeg"
            meta["cover_resource"] = target
    except Exception:
        # A valid SVG or an unsupported image can still be displayed through the safe resource route.
        pass


def import_path(source, original_name=None):
    source = Path(source)
    name = str(original_name or source.name).replace("\\", "/").rsplit("/", 1)[-1]
    if not name or len(name) > 300:
        raise BookParseError("Некорректное имя файла")
    if not name.lower().endswith((".fb2", ".epub", ".fb2.zip", ".zip", ".txt", ".pdf", ".cbz", ".cbr")):
        raise BookParseError("Поддерживаются FB2, FB2.zip, EPUB, TXT, PDF, CBZ и CBR")
    init()
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        while piece := stream.read(1024 * 1024):
            digest.update(piece)
    hexdigest = digest.hexdigest()
    with _lock:
        with connect() as db:
            duplicate = db.execute("SELECT * FROM books WHERE digest=?", (hexdigest,)).fetchone()
        if duplicate:
            return {"book": _public(duplicate, True), "duplicate": True}
        book_id = uuid.uuid4().hex
        destination = _book_dir(book_id)
        destination.mkdir(parents=True)
        try:
            suffix = ".fb2.zip" if name.lower().endswith(".fb2.zip") else Path(name).suffix.lower()
            original = destination / ("original" + suffix)
            shutil.copyfile(source, original)
            if suffix in {".pdf", ".cbz", ".cbr"}:
                from .paged import prepare_paged
                meta = prepare_paged(original, name, destination, book_id)
            else:
                meta = parse_book(original, name, destination, book_id)
            meta.update(original_file=original.name, original_name=name, size=original.stat().st_size)
            _cover_thumbnail(destination, meta)
            with connect() as db:
                db.execute("INSERT INTO books(id,digest,metadata,added_at) VALUES(?,?,?,?)", (book_id, hexdigest, json.dumps(meta, ensure_ascii=False), now()))
            return {"book": get_book(book_id), "duplicate": False}
        except Exception:
            if destination.is_relative_to((DATA_DIR / "books").resolve()):
                shutil.rmtree(destination, ignore_errors=True)
            raise


def update_book(book_id, values):
    book = get_book(book_id)
    updates = {}
    if "status" in values and values["status"] not in STATUSES:
        raise ValueError("Неизвестный статус книги")
    queue_transition = "status" in values and (values["status"] in {"planned", "want"} or book["status"] in {"planned", "want"} or "planned_previous_status" in book)
    if queue_transition or any(key in values for key in ("media_type", "series", "series_index", "archived")):
        with connect() as db:
            metadata = json.loads(db.execute("SELECT metadata FROM books WHERE id=?", (book_id,)).fetchone()[0])
        if "media_type" in values:
            if values["media_type"] not in {"book", "comic"}:
                raise ValueError("Тип издания должен быть «Книга» или «Комикс»")
            metadata["media_type"] = values["media_type"]
        if "archived" in values:
            if not isinstance(values["archived"], bool):
                raise ValueError("Признак архива должен быть true или false")
            metadata["archived"] = values["archived"]
        if "status" in values:
            previous = {"want": "planned", "finished": "read"}.get(book["status"], book["status"])
            following = {"want": "planned", "finished": "read"}.get(values["status"], values["status"])
            if following == "planned" and previous != "planned":
                metadata["planned_previous_status"] = previous if previous in {"unread", "reading", "read"} else "unread"
            elif following != "planned":
                metadata.pop("planned_previous_status", None)
        if "series" in values:
            name = values["series"]
            if not isinstance(name, str) or len(name) > 300 or any(ord(char) < 32 for char in name):
                raise ValueError("Название серии должно быть строкой до 300 символов без переносов")
            name = name.strip()
            # A number from another series must not silently move to the new one.
            if name != metadata.get("series", "") or not name:
                metadata["series_index"] = None
            metadata["series"] = name
        if "series_index" in values:
            position = values["series_index"]
            if position is not None:
                if isinstance(position, bool) or not isinstance(position, (int, float)) or not 0 <= position <= 1_000_000 or not math.isfinite(position):
                    raise ValueError("Номер в серии должен быть числом от 0 до 1000000 или null")
                if not metadata.get("series"):
                    raise ValueError("Сначала укажите серию книги")
            metadata["series_index"] = position
        updates["metadata"] = json.dumps(metadata, ensure_ascii=False)
    if "status" in values:
        if values["status"] not in STATUSES:
            raise ValueError("Неизвестный статус книги")
        updates["status"] = values["status"]
    if "progress" in values:
        progress = float(values["progress"])
        if not 0 <= progress <= 100:
            raise ValueError("Процент должен быть от 0 до 100")
        updates["progress"] = progress
    if "chapter" in values:
        chapter = int(values["chapter"])
        if not 0 <= chapter < book["chapter_count"]:
            raise ValueError("Неизвестный раздел")
        updates["chapter"] = chapter
    for key in ("locator", "reading_settings", "bookmarks"):
        if key in values:
            encoded = json.dumps(values[key], ensure_ascii=False)
            if len(encoded) > 300_000:
                raise ValueError("Слишком большое состояние чтения")
            updates[key] = encoded
    if "last_opened" in values:
        updates["last_opened"] = now()
    if updates:
        with connect() as db:
            db.execute("UPDATE books SET " + ", ".join(k + "=?" for k in updates) + " WHERE id=?", (*updates.values(), book_id))
    return get_book(book_id)


def delete_book(book_id):
    get_book(book_id)
    path = _book_dir(book_id)
    with _lock:
        with connect() as db:
            db.execute("DELETE FROM books WHERE id=?", (book_id,))
        if path.is_relative_to((DATA_DIR / "books").resolve()) and path.exists():
            shutil.rmtree(path)
    return {"ok": True}


def get_settings():
    init()
    with connect() as db:
        row = db.execute("SELECT value FROM settings WHERE id=1").fetchone()
    return json.loads(row[0]) if row else {}


def save_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError("Настройки должны быть объектом")
    merged = {**get_settings(), **settings}
    raw = json.dumps(merged, ensure_ascii=False)
    if len(raw) > 100_000:
        raise ValueError("Слишком большие настройки")
    with connect() as db:
        db.execute("INSERT INTO settings(id,value) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value", (raw,))
    return merged


def list_catalogs():
    init()
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM catalogs ORDER BY added_at")]


def add_catalog(values):
    from urllib.parse import urlsplit
    url = str(values.get("url", "")).strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Укажите HTTP(S)-адрес OPDS без пароля в URL")
    name = str(values.get("name") or parsed.hostname).strip()[:150]
    item = {"id": uuid.uuid4().hex, "name": name, "url": url, "added_at": now()}
    init()
    with connect() as db:
        db.execute("INSERT INTO catalogs(id,name,url,added_at) VALUES(:id,:name,:url,:added_at)", item)
    return item


def delete_catalog(catalog_id):
    init()
    with connect() as db:
        db.execute("DELETE FROM catalogs WHERE id=?", (catalog_id,))
    return {"ok": True}


def backup_to(path):
    """Consistent SQLite snapshot. Book originals live alongside it and are not modified."""
    init()
    with connect() as source:
        target = sqlite3.connect(path)
        try:
            source.backup(target)
        finally:
            target.close()
