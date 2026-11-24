import asyncio
import hashlib
import wave
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import tts
from backend.tts_text import russian_yo


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(tts.router)
    with TestClient(app) as test_client:
        yield test_client


def test_yo_preserves_canonical_offsets_case_and_ambiguous_words():
    original = "Еще ЕЛКА, елки, самолет и береза. Все осел берет узнаем передохнем. 😀"
    prepared, count = russian_yo(original)
    assert prepared == "Ещё ЁЛКА, ёлки, самолёт и берёза. Все осел берет узнаем передохнем. 😀"
    assert len(prepared) == len(original)
    assert len(prepared.encode("utf-16-le")) == len(original.encode("utf-16-le"))
    assert count == 5
    assert original.index("Все") == prepared.index("Все")
    assert russian_yo("Ёлка, всё, осёл.") == ("Ёлка, всё, осёл.", 0)


def test_yo_is_opt_in_applies_to_russian_only_and_separates_audio_cache(client, monkeypatch, tmp_path):
    seen = []
    class FakeWorker:
        generation = 0
        loaded = False
        def stop(self):
            pass
        def synthesize(self, text, rate, destination, generation, voice):
            seen.append((text, voice))
            with wave.open(str(destination), "wb") as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050)
                wav.writeframes(b"\0\0" * 100)
            return {"duration": 100 / 22050, "sample_rate": 22050}
    monkeypatch.setattr(tts, "worker", FakeWorker())
    monkeypatch.setattr(tts, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(tts, "model_ready", lambda _id: (True, "ready"))
    payload = {"text": "Еще самолет, все замки.", "voice": tts.VOICE_ID}
    original = client.post("/api/tts/synthesize", json=payload).json()
    normalized = client.post("/api/tts/synthesize", json={**payload, "russian_yo": True}).json()
    english = client.post("/api/tts/synthesize", json={**payload, "voice": "en_US-lessac-medium", "russian_yo": True}).json()
    assert seen[0][0] == payload["text"]
    assert seen[1][0] == "Ещё самолёт, все замки."
    assert seen[2][0] == payload["text"]
    assert original["url"] != normalized["url"]
    assert normalized["normalization"] == {"russian_yo": True, "replacements": 2}
    assert english["normalization"]["russian_yo"] is False
    assert payload["text"] == "Еще самолет, все замки."
    cached = client.post("/api/tts/synthesize", json={**payload, "russian_yo": True}).json()
    assert cached["cached"] is True and cached["url"] == normalized["url"]
    assert cached["normalization"] == normalized["normalization"]
    assert len(seen) == 3


@pytest.fixture
def download_fixture(monkeypatch, tmp_path):
    contents = {"ru_RU-ruslan-medium.onnx": b"model fixture", "ru_RU-ruslan-medium.onnx.json": b'{"test":1}', "MODEL_CARD": b"Fixture license"}
    files = tuple({"name": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "url": "https://models.test/" + name} for name, raw in contents.items())
    voice = replace(tts.VOICES["ru_RU-ruslan-medium"], path=tmp_path / "models" / "piper-ru-ruslan" / "ru_RU-ruslan-medium.onnx",
                    model_sha256=files[0]["sha256"], config_sha256=files[1]["sha256"], files=files)
    monkeypatch.setattr(tts, "DATA_DIR", tmp_path)
    monkeypatch.setitem(tts.VOICES, voice.id, voice)
    monkeypatch.setattr(tts, "_integrity_cache", {})
    original_client = httpx.AsyncClient
    calls = []
    def use_response(response_factory):
        def respond(request):
            calls.append(request.url.path.rsplit("/", 1)[-1])
            return response_factory(request)
        monkeypatch.setattr(tts.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    use_response(lambda request: httpx.Response(200, content=contents[request.url.path.rsplit("/", 1)[-1]]))
    return voice, contents, calls, use_response


def test_download_installs_only_pinned_files_and_reuses_verified_files(client, download_fixture):
    voice, contents, calls, _ = download_fixture
    response = client.post(f"/api/tts/voices/{voice.id}/download")
    assert response.status_code == 200, response.text
    assert response.json()["ready"] is True
    assert calls == list(contents)
    for name, raw in contents.items():
        assert (voice.path.parent / name).read_bytes() == raw
    assert not list(voice.path.parent.glob("*.download"))
    calls.clear()
    assert client.post(f"/api/tts/voices/{voice.id}/download").status_code == 200
    assert calls == []
    assert voice.id not in tts._downloading


@pytest.mark.parametrize("failure", ["hash", "oversize", "network"])
def test_download_failure_leaves_existing_files_unchanged_and_cleans_staging(client, download_fixture, failure):
    voice, contents, calls, use_response = download_fixture
    voice.path.parent.mkdir(parents=True)
    voice.path.write_bytes(b"existing invalid file left unchanged until successful replacement")
    existing = voice.path.read_bytes()
    def respond(request):
        name = request.url.path.rsplit("/", 1)[-1]
        if name.endswith(".json"):
            if failure == "network":
                raise httpx.ConnectError("fixture offline")
            raw = b"X" * (len(contents[name]) + (1 if failure == "oversize" else 0))
            return httpx.Response(200, content=raw)
        return httpx.Response(200, content=contents[name])
    use_response(respond)
    response = client.post(f"/api/tts/voices/{voice.id}/download")
    assert response.status_code == (502 if failure == "network" else 422)
    assert voice.path.read_bytes() == existing
    assert not voice.path.with_suffix(".onnx.json").exists()
    assert not list(voice.path.parent.glob("*.download"))
    assert voice.id not in tts._downloading


def test_download_cancellation_removes_partial_files(download_fixture):
    voice, _, _, use_response = download_fixture
    class CancelledStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise asyncio.CancelledError()
            yield b""
    use_response(lambda request: httpx.Response(200, stream=CancelledStream()))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tts._download_voice(voice))
    assert not list(voice.path.parent.iterdir())


def test_download_detects_closed_client_and_removes_partial_files(download_fixture):
    voice, _, _, _ = download_fixture
    class ClosedRequest:
        async def is_disconnected(self):
            return True
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tts._download_voice(voice, ClosedRequest()))
    assert not list(voice.path.parent.iterdir())


def test_unknown_voice_never_starts_network_and_busy_download_rejected(client, download_fixture):
    voice, _, calls, _ = download_fixture
    assert client.post("/api/tts/voices/not-in-manifest/download").status_code == 404
    asyncio.run(tts._download_slot.acquire())
    try:
        assert client.post(f"/api/tts/voices/{voice.id}/download").status_code == 409
    finally:
        tts._download_slot.release()
    assert calls == []


def test_status_distinguishes_installed_and_optional_voices(client, monkeypatch):
    installed = {"ru_RU-dmitri-medium", "ru_RU-denis-medium", "ru_RU-irina-medium"}
    monkeypatch.setattr(tts, "model_ready", lambda voice_id=tts.VOICE_ID: (voice_id in installed, "fixture"))
    data = client.get("/api/tts/status").json()
    assert {voice["id"] for voice in data["voices"]} == installed
    assert {voice["id"] for voice in data["downloadable_voices"]} == {"ru_RU-ruslan-medium", "en_US-lessac-medium"}
    assert all(voice["size_mb"] == 63.2 and voice["license"] for voice in data["downloadable_voices"])
    assert data["capabilities"]["russian_yo"] is True
