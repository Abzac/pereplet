"""Actual import/render/state API contract with isolated synthetic documents."""
import io
import zipfile

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from backend import library, server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path / "library")
    with TestClient(server.app, base_url="http://127.0.0.1:18765") as value:
        yield value


def headers():
    return {"X-Pereplet": "1", "X-Pereplet-Token": server.SESSION_TOKEN}


def document(extension):
    pages = [Image.new("RGB", (240, 480), color) for color in ("red", "blue")]
    result = io.BytesIO()
    if extension == "pdf":
        pages[0].save(result, "PDF", save_all=True, append_images=pages[1:])
    else:
        with zipfile.ZipFile(result, "w") as archive:
            for index, page in enumerate(pages):
                image = io.BytesIO()
                page.save(image, "PNG")
                archive.writestr(f"{index+1}.png", image.getvalue())
    return result.getvalue()


@pytest.mark.parametrize("extension", ["pdf", "cbz"])
def test_import_render_position_and_immutable_source(client, extension):
    original = document(extension)
    response = client.post("/api/import", files=[("files", (f"test.{extension}", original))], headers=headers())
    assert response.status_code == 200
    assert response.json()["errors"] == []
    book = response.json()["imported"][0]
    assert book["reader_type"] == "pages" and book["page_count"] == 2
    assert book["media_type"] == ("comic" if extension == "cbz" else "book")
    assert (library.DATA_DIR / "books" / book["id"] / f"original.{extension}").read_bytes() == original
    assert book["cover_url"] and client.get(book["cover_url"]).status_code == 200
    first = client.get(f'/api/books/{book["id"]}/pages/0?width=480')
    second = client.get(f'/api/books/{book["id"]}/pages/1?width=480')
    assert first.status_code == second.status_code == 200
    assert first.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(second.content)) as image:
        red, green, blue = image.convert("RGB").getpixel((image.width // 2, image.height // 2))
        assert blue > 200 and red < 30
    assert first.content != second.content
    assert client.get(f'/api/books/{book["id"]}/pages/2').status_code in (404, 422)
    saved = client.patch(f'/api/books/{book["id"]}', headers=headers(), json={"chapter": 1, "locator": {"page": 1, "ratio": .62}, "reading_settings": {"pageWidth": 1080}})
    assert saved.status_code == 200
    restored = client.get(f'/api/books/{book["id"]}').json()
    assert restored["chapter"] == 1 and restored["locator"]["ratio"] == .62
    assert restored["reading_settings"]["pageWidth"] == 1080
    original_title = restored["title"]
    switched = client.patch(f'/api/books/{book["id"]}', headers=headers(), json={"media_type": "comic" if extension == "pdf" else "book"})
    assert switched.status_code == 200
    assert switched.json()["media_type"] == ("comic" if extension == "pdf" else "book")
    assert switched.json()["title"] == original_title and switched.json()["locator"]["ratio"] == .62
    assert client.get('/api/books').json()[0]["media_type"] == switched.json()["media_type"]
    assert client.patch(f'/api/books/{book["id"]}', headers=headers(), json={"media_type": "invalid"}).status_code == 422


def test_txt_is_reflowable_not_a_page_image(client):
    response = client.post("/api/import", files=[("files", ("Тест.txt", "Первый абзац.\n\nВторой абзац.".encode()))], headers=headers())
    assert response.status_code == 200 and response.json()["errors"] == []
    book = response.json()["imported"][0]
    assert book["format"] == "TXT" and book.get("reader_type") != "pages"
    assert book["media_type"] == "book"
    assert len(client.get(f'/api/books/{book["id"]}/chapters/0').json()["paragraphs"]) == 2
    assert client.get(f'/api/books/{book["id"]}/pages/0').status_code in (404, 422)
