from __future__ import annotations

import importlib
import os
import secrets
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from . import library, search
from .parsers import BookParseError

app = FastAPI(title="Переплёт", docs_url=None, redoc_url=None)
PORT = int(os.environ.get("PEREPLET_PORT", "18765"))
LOCAL_AUTHORITIES = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
SESSION_TOKEN = secrets.token_urlsafe(32)
FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "dist"
STATIC_MIME = {".js": "application/javascript", ".mjs": "application/javascript", ".css": "text/css", ".html": "text/html", ".json": "application/json", ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".txt": "text/plain"}


@app.middleware("http")
async def local_only(request: Request, call_next):
    authority = request.headers.get("host", "").lower()
    if authority not in LOCAL_AUTHORITIES:
        return JSONResponse({"detail": "Допускается только локальный доступ"}, status_code=403)
    if request.url.path.startswith("/api/") and request.headers.get("sec-fetch-site", "same-origin") not in {"same-origin", "none"}:
        return JSONResponse({"detail": "Недопустимый источник запроса"}, status_code=403)
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or parsed.netloc.lower() != authority:
            return JSONResponse({"detail": "Недопустимый источник запроса"}, status_code=403)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/"):
        token = request.headers.get("x-pereplet-token", "")
        if request.headers.get("x-pereplet") != "1" or not secrets.compare_digest(token, SESSION_TOKEN):
            return JSONResponse({"detail": "Запрос должен выполняться из приложения"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if "/resources/" in request.url.path:
        response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    return response


@app.exception_handler(BookParseError)
async def parse_error(_request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(KeyError)
async def missing(_request, exc):
    return JSONResponse({"detail": str(exc).strip("'")}, status_code=404)


@app.exception_handler(ValueError)
async def invalid(_request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.get("/api/health")
def health():
    return {"ok": True, "app": "pereplet", "version": "0.1.0", "instance": os.environ.get("PEREPLET_INSTANCE_ID", "")}


@app.get("/api/session")
def session(request: Request):
    if request.headers.get("sec-fetch-site", "same-origin") not in {"same-origin", "none"}:
        raise HTTPException(403, "Откройте приложение по его локальному адресу")
    return JSONResponse({"token": SESSION_TOKEN}, headers={"Cache-Control": "no-store"})


@app.get("/api/books")
def books():
    return library.list_books()


@app.post("/api/help/reader-guide")
def reader_guide():
    from .starter_library import reader_guide as get_guide
    return get_guide()


@app.post("/api/import")
async def import_files(files: list[UploadFile] = File(...)):
    library.init()
    result = {"imported": [], "duplicates": [], "errors": []}
    if len(files) > 2000:
        raise HTTPException(413, "За один раз можно добавить не более 2000 файлов")
    for upload in files:
        name = upload.filename or "book.fb2"
        temporary = library.DATA_DIR / "tmp" / (uuid.uuid4().hex + ".upload")
        try:
            size = 0
            with temporary.open("wb") as out:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > 1024**3:
                        raise BookParseError("Файл превышает лимит 1 ГБ")
                    out.write(chunk)
            item = await run_in_threadpool(library.import_path, temporary, name)
            result["duplicates" if item["duplicate"] else "imported"].append(item["book"])
        except (BookParseError, ValueError, OSError) as exc:
            result["errors"].append({"name": name, "error": str(exc)[:300]})
        finally:
            temporary.unlink(missing_ok=True)
            await upload.close()
    return result


@app.get("/api/books/{book_id}")
def book(book_id: str):
    return library.get_book(book_id)


@app.patch("/api/books/{book_id}")
def update_book(book_id: str, values: dict):
    return library.update_book(book_id, values)


@app.delete("/api/books/{book_id}")
def delete_book(book_id: str):
    return library.delete_book(book_id)


@app.get("/api/books/{book_id}/chapters/{index}")
def chapter(book_id: str, index: int):
    return library.get_chapter(book_id, index)


@app.get("/api/books/{book_id}/search")
def search_book(book_id: str, q: str = Query(..., min_length=1, max_length=160),
                scope: str = "book", chapter: int = Query(0, ge=0),
                offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)):
    return search.search_book(book_id, q, scope, chapter, offset, limit)


@app.get("/api/books/{book_id}/notes/{anchor_id}")
def note(book_id: str, anchor_id: str):
    return library.get_note(book_id, anchor_id)


@app.get("/api/books/{book_id}/pages/{index}")
def document_page(book_id: str, index: int, width: int = 1600):
    path = library.get_page(book_id, index, width)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/books/{book_id}/resources/{resource:path}")
def resource(book_id: str, resource: str):
    path, kind = library.resource_path(book_id, resource)
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/settings")
def settings():
    return library.get_settings()


@app.put("/api/settings")
def save_settings(values: dict):
    return library.save_settings(values)


@app.get("/api/catalogs")
def catalogs():
    return library.list_catalogs()


@app.post("/api/catalogs")
def add_catalog(values: dict):
    return library.add_catalog(values)


@app.delete("/api/catalogs/{catalog_id}")
def delete_catalog(catalog_id: str):
    return library.delete_catalog(catalog_id)


for module_name in ("opds", "tts"):
    try:
        module = importlib.import_module(f"backend.{module_name}")
    except ModuleNotFoundError as exc:
        if exc.name != f"backend.{module_name}":
            raise
    else:
        app.include_router(module.router)


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "API endpoint не найден")
    root = FRONTEND.resolve()
    asset = (root / path).resolve()
    if not asset.is_relative_to(root):
        raise HTTPException(404)
    if asset.is_file():
        return FileResponse(asset, media_type=STATIC_MIME.get(asset.suffix.lower(), "application/octet-stream"))
    index = root / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Интерфейс ещё не собран. Выполните сборку frontend."}, status_code=503)
