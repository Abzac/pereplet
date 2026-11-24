"""Lazy, bounded image pages for immutable PDF and CBZ/CBR originals.

Only the cover is rendered during import. Page images are derived PNGs; the
original is never edited and a CBZ is never extracted into the filesystem.
"""
from __future__ import annotations

import json
import io
import math
import os
import re
import threading
import time
import uuid
import warnings
import zipfile
import zlib
from pathlib import Path

from PIL import Image, ImageOps

from .parsers import BookParseError, local_name, safe_zip_path, verify_zip, xml_tree

MAX_SOURCE_BYTES = 1024**3
MAX_PAGES = 10_000
MAX_IMAGE_BYTES = 128 * 1024**2
MAX_IMAGE_PIXELS = 40_000_000
MAX_RENDER_PIXELS = 12_000_000
MAX_RENDER_SIDE = 4096
MAX_MANIFEST_BYTES = 4 * 1024**2
MAX_CACHE_BYTES = 64 * 1024**2
MAX_CACHE_FILES = 32
WIDTHS = (480, 800, 1200, 1600, 2000, 2400)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "AVIF"}
MANIFEST = "paged-manifest.json"
# PDFium must never be called concurrently, even for different documents.
# Serializing the small CBZ render jobs also bounds peak decoded-image memory.
_render_lock = threading.RLock()
_cache_clock_ns = 0


def _pdfium():
    try:
        import pypdfium2
    except ImportError as exc:
        raise BookParseError("Для PDF установите зависимости Переплёта: pypdfium2") from exc
    return pypdfium2


def _source_check(source: Path) -> None:
    if not source.is_file():
        raise BookParseError("Исходный файл книги не найден")
    if not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
        raise BookParseError("Пустой файл или книга превышает лимит 1 ГБ")


def _page_count(count: int) -> None:
    if not 0 < count <= MAX_PAGES:
        raise BookParseError(f"В книге должно быть от 1 до {MAX_PAGES} страниц")


def _text(value: str | None, maximum: int = 2000) -> str:
    return " ".join((value or "").replace("\x00", "").split())[:maximum]


def _natural_key(name: str):
    # Type-tagged pieces keep comparisons deterministic even for mixed names.
    return [(1, int(part)) if part.isdigit() else (0, part.casefold())
            for part in re.split(r"([0-9]+)", name)]


def _comic_manifest(source: Path) -> tuple[list[str], dict]:
    with zipfile.ZipFile(source) as archive:
        verify_zip(archive)
        names = set()
        pages = []
        comic = None
        for info in archive.infolist():
            # ZipInfo normalizes backslashes on Windows and truncates NULs;
            # check the archive's original spelling before using its name.
            safe_zip_path(info.orig_filename)
            normalized = safe_zip_path(info.filename)
            folded = normalized.casefold()
            if folded in names:
                raise BookParseError("В CBZ есть повторяющиеся имена файлов")
            names.add(folded)
            if info.is_dir():
                continue
            if len(info.filename) > 1024:
                raise BookParseError("Слишком длинное имя файла в CBZ")
            parts = Path(normalized).parts
            if any(part.startswith(".") or part == "__MACOSX" for part in parts):
                continue
            if Path(normalized).suffix.lower() in IMAGE_EXTENSIONS:
                if info.file_size > MAX_IMAGE_BYTES:
                    raise BookParseError("Изображение в CBZ превышает лимит 128 МБ")
                pages.append(info.filename)
            elif normalized.casefold() == "comicinfo.xml" and info.file_size <= 1024**2:
                comic = info
        _page_count(len(pages))
        pages.sort(key=lambda name: (_natural_key(name), name))
        metadata = {}
        if comic is not None:
            try:
                root = xml_tree(archive.read(comic))
                metadata = {local_name(item.tag): _text(item.text) for item in root}
            except Exception:
                # Optional malformed ComicInfo does not make image pages unreadable.
                metadata = {}
        return pages, metadata


def _target_size(width: float, height: float, requested: int, upscale=True) -> tuple[int, int]:
    if not all(math.isfinite(v) and 0 < v <= 1_000_000 for v in (width, height)):
        raise BookParseError("Некорректный размер страницы")
    scale = min(requested / width, MAX_RENDER_SIDE / max(width, height),
                math.sqrt(MAX_RENDER_PIXELS / (width * height)))
    if not upscale:
        scale = min(scale, 1.0)
    return max(1, int(width * scale)), max(1, int(height * scale))


def _rar_manifest(source: Path) -> tuple[list[str], dict]:
    from .rar import members, read_member
    pages, comic = [], None
    for item in members(source):
        name = item["name"]
        if item["directory"] or any(part.startswith(".") or part == "__MACOSX" for part in Path(name).parts):
            continue
        if Path(name).suffix.lower() in IMAGE_EXTENSIONS:
            if item["size"] > MAX_IMAGE_BYTES:
                raise BookParseError("Изображение в CBR превышает лимит 128 МБ")
            pages.append(name)
        elif name.casefold() == "comicinfo.xml" and item["size"] <= 1024**2:
            comic = name
    _page_count(len(pages))
    pages.sort(key=lambda name: (_natural_key(name), name))
    metadata = {}
    if comic:
        try:
            root = xml_tree(read_member(source, comic, 1024**2))
            metadata = {local_name(item.tag): _text(item.text) for item in root}
        except Exception:
            pass  # Optional ComicInfo must not hide otherwise readable pages.
    return pages, metadata


def _pdf_image(source: Path, index: int, width: int) -> Image.Image:
    pdfium = _pdfium()
    try:
        # Own the file handle too: PDFium construction can fail before its
        # context manager is entered (notably on password-protected PDFs).
        with source.open("rb") as stream, pdfium.PdfDocument(stream) as document:
            if not 0 <= index < len(document):
                raise KeyError("Страница не найдена")
            page = document[index]
            try:
                page_width, page_height = page.get_size()
                target_width, target_height = _target_size(page_width, page_height, width)
                scale = min(target_width / page_width, target_height / page_height)
                bitmap = page.render(scale=scale, fill_color=(255, 255, 255, 255), may_draw_forms=False)
                try:
                    pil = bitmap.to_pil()
                    try:
                        return pil.convert("RGB")
                    finally:
                        pil.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
    except pdfium.PdfiumError as exc:
        if getattr(exc, "err_code", None) == 4:
            raise BookParseError("PDF защищён паролем; такие файлы пока не поддерживаются") from exc
        raise BookParseError("Не удалось прочитать или отрисовать PDF") from exc


def _comic_image(source: Path, name: str, width: int) -> Image.Image:
    safe_zip_path(name)
    with zipfile.ZipFile(source) as archive:
        try:
            info = archive.getinfo(name)
        except KeyError as exc:
            raise BookParseError("Страница отсутствует в исходном CBZ") from exc
        if info.file_size > MAX_IMAGE_BYTES or info.flag_bits & 1:
            raise BookParseError("Зашифрованная или слишком большая страница CBZ")
        # Open one member as a stream, rather than archive.read() + another copy.
        with archive.open(info) as stream:
            return _image_stream(stream, width, "CBZ")


def _rar_image(source: Path, name: str, width: int) -> Image.Image:
    from .rar import read_member
    with io.BytesIO(read_member(source, name, MAX_IMAGE_BYTES)) as stream:
        return _image_stream(stream, width, "CBR")


def _image_stream(stream, width: int, kind: str) -> Image.Image:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(stream) as image:
            if image.format not in IMAGE_FORMATS:
                raise BookParseError(f"Формат изображения {kind} не поддерживается")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise BookParseError(f"Изображение {kind} превышает лимит 40 мегапикселей")
            size = _target_size(image.width, image.height, width, upscale=False)
            image.draft("RGB", size)
            oriented = ImageOps.exif_transpose(image)
            try:
                size = _target_size(oriented.width, oriented.height, width, upscale=False)
                oriented.thumbnail(size, Image.Resampling.LANCZOS)
                rgba = oriented.convert("RGBA")
                try:
                    result = Image.new("RGB", rgba.size, "white")
                    result.paste(rgba, mask=rgba.getchannel("A"))
                    return result
                finally:
                    rgba.close()
            finally:
                oriented.close()


def _pdf_metadata(source: Path) -> tuple[int, dict]:
    pdfium = _pdfium()
    try:
        with source.open("rb") as stream, pdfium.PdfDocument(stream) as document:
            count = len(document)
            _page_count(count)
            return count, document.get_metadata_dict()
    except pdfium.PdfiumError as exc:
        if getattr(exc, "err_code", None) == 4:
            raise BookParseError("PDF защищён паролем; такие файлы пока не поддерживаются") from exc
        raise BookParseError("Не удалось открыть PDF: файл повреждён или имеет неподдерживаемый формат") from exc


def prepare_paged(source: Path, name: str, destination: Path, book_id: str) -> dict:
    """Return library metadata and derive a cover, without rendering other pages.

    The caller owns the immutable source copy and cleanup on a failed import.
    Page indices are zero-based and intentionally match chapter indices so the
    existing progress/bookmark storage can be reused by the paged reader.
    """
    source, destination = Path(source), Path(destination)
    _source_check(source)
    kind = Path(name).suffix.lower()
    if kind not in {".pdf", ".cbz", ".cbr"}:
        raise BookParseError("Страничный режим поддерживает PDF, CBZ и CBR")
    title = Path(name).stem
    with _render_lock:
        try:
            if kind == ".pdf":
                count, raw_meta = _pdf_metadata(source)
                authors = [_text(raw_meta.get("Author"))] if raw_meta.get("Author") else []
                title = _text(raw_meta.get("Title")) or title
                annotation = _text(raw_meta.get("Subject"), 8000)
                language, series, series_index = "", "", ""
                manifest = {"version": 1, "format": "PDF", "count": count}
                cover = _pdf_image(source, 0, 600)
            else:
                pages, raw_meta = (_rar_manifest if kind == ".cbr" else _comic_manifest)(source)
                count = len(pages)
                title = raw_meta.get("title") or title
                authors = [v.strip() for v in raw_meta.get("writer", "").split(",") if v.strip()]
                annotation = raw_meta.get("summary", "")
                language = raw_meta.get("languageiso", "")
                series, series_index = raw_meta.get("series", ""), raw_meta.get("number", "")
                manifest = {"version": 1, "format": kind[1:].upper(), "count": count, "entries": pages}
                cover = (_rar_image if kind == ".cbr" else _comic_image)(source, pages[0], 600)
            encoded = json.dumps(manifest, ensure_ascii=False)
            if len(encoded.encode("utf-8")) > MAX_MANIFEST_BYTES:
                cover.close()
                raise BookParseError("Слишком большой список страниц комикса")
            try:
                (destination / "resources").mkdir(parents=True, exist_ok=True)
                cover.save(destination / "resources" / "cover.png", "PNG")
            finally:
                cover.close()
            (destination / MANIFEST).write_text(encoded, encoding="utf-8")
        except (zipfile.BadZipFile, OSError, EOFError, RuntimeError, zlib.error,
                Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise BookParseError("Не удалось прочитать страницы книги: файл повреждён или изображение слишком велико") from exc
    return {
        "title": title, "authors": authors, "annotation": annotation, "language": language,
        "series": series, "series_index": series_index, "format": kind[1:].upper(),
        "reader_type": "pages", "page_count": count, "original_file": source.name,
        "chapters": [{"index": index, "id": f"page-{index}", "title": f"Страница {index + 1}", "length": 0}
                     for index in range(count)],
        "anchors": {}, "resources": {"cover.png": "image/png"}, "cover_resource": "cover.png",
    }


def _managed_child(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).name != name or any(c in name for c in "/\\:"):
        raise BookParseError("Некорректный путь ресурса книги")
    child = (root / name).resolve()
    if child.parent != root:
        raise BookParseError("Некорректный путь ресурса книги")
    return child


def _touch_cache(path: Path) -> None:
    # Called under _render_lock. Rapid accesses can share a Windows clock tick;
    # give each access a distinct persisted timestamp to keep eviction ordered.
    global _cache_clock_ns
    _cache_clock_ns = max(time.time_ns(), _cache_clock_ns + 1_000_000)
    os.utime(path, ns=(_cache_clock_ns, _cache_clock_ns))


def _prune_cache(cache: Path, keep: Path) -> None:
    files = [item for item in cache.glob("v1-p*-w*.png") if item.is_file() and not item.is_symlink()]
    sizes = {item: item.stat().st_size for item in files}
    total = sum(sizes.values())
    count = len(files)
    for item in sorted(files, key=lambda path: path.stat().st_mtime_ns):
        if count <= MAX_CACHE_FILES and total <= MAX_CACHE_BYTES:
            break
        if item == keep:
            continue
        try:
            item.unlink()
        except OSError:
            # A response may still have a cached page open on Windows.
            continue
        total -= sizes[item]
        count -= 1


def render_page(book_dir: Path, metadata: dict, page_index: int, width: int = 1600) -> Path:
    """Return a cached PNG for exactly one page; never expose archive paths.

    Widths use six buckets to bound resize variants. The per-book on-disk cache
    retains at most 32 pages/64 MiB when files are not actively being served.
    """
    if metadata.get("reader_type") != "pages" or metadata.get("format") not in {"PDF", "CBZ", "CBR"}:
        raise KeyError("Книга не использует страничный формат")
    count = metadata.get("page_count", 0)
    if type(count) is not int or type(page_index) is not int or not 0 <= page_index < count <= MAX_PAGES:
        raise KeyError("Страница не найдена")
    if type(width) is not int:
        raise ValueError("Ширина страницы должна быть целым числом")
    width = next((value for value in WIDTHS if value >= width), WIDTHS[-1])
    root = Path(book_dir).resolve()
    source = _managed_child(root, metadata.get("original_file", ""))
    _source_check(source)
    cache = _managed_child(root, "pages")
    cache.mkdir(exist_ok=True)
    output = _managed_child(cache, f"v1-p{page_index:05d}-w{width}.png")
    with _render_lock:
        if output.is_file():
            _touch_cache(output)
            _prune_cache(cache, output)
            return output
        manifest_path = _managed_child(root, MANIFEST)
        if not manifest_path.is_file() or manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise BookParseError("Повреждён список страниц книги")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (not isinstance(manifest, dict) or manifest.get("version") != 1 or manifest.get("format") != metadata["format"]
                    or manifest.get("count") != count):
                raise BookParseError("Повреждён список страниц книги")
            if metadata["format"] == "PDF":
                image = _pdf_image(source, page_index, width)
            else:
                entries = manifest.get("entries", [])
                if not isinstance(entries, list) or len(entries) != count or not isinstance(entries[page_index], str):
                    raise BookParseError("Повреждён список страниц книги")
                image = (_rar_image if metadata["format"] == "CBR" else _comic_image)(source, entries[page_index], width)
        except (ValueError, zipfile.BadZipFile, OSError, EOFError, RuntimeError, zlib.error,
                Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            if isinstance(exc, BookParseError):
                raise
            raise BookParseError("Не удалось прочитать страницу книги") from exc
        temporary = _managed_child(cache, f"{uuid.uuid4().hex}.tmp")
        try:
            image.save(temporary, format="PNG")
            os.replace(temporary, output)
        finally:
            image.close()
            temporary.unlink(missing_ok=True)
        _touch_cache(output)
        _prune_cache(cache, output)
        return output
