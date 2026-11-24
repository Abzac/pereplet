import array
from pathlib import Path
import hashlib
import io
import os
import wave
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import tts


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(tts.router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("payload", [{"text": ""}, {"text": "   "}, {"text": "a" * 6001}, {"text": "test", "rate": 0.1}, {"text": "test", "rate": 3}])
def test_invalid_speech_is_rejected_before_loading_model(client, payload):
    assert client.post("/api/tts/synthesize", json=payload).status_code == 422


def test_unknown_voice_and_unsafe_audio_names(client):
    assert client.post("/api/tts/synthesize", json={"text": "test", "voice": "unknown"}).status_code == 400
    assert client.get("/api/tts/audio/model.onnx").status_code == 404
    assert client.get("/api/tts/audio/" + "f" * 64 + ".wav").status_code == 404


@pytest.mark.parametrize("voice_id", list(tts.VOICES))
def test_model_and_configuration_integrity(monkeypatch, tmp_path, voice_id):
    model = tmp_path / "voice.onnx"
    config = tmp_path / "voice.onnx.json"
    model.write_bytes(b"model fixture")
    config.write_bytes(b"configuration fixture")
    voice = replace(tts.VOICES[voice_id], path=model, model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(), config_sha256=hashlib.sha256(config.read_bytes()).hexdigest())
    monkeypatch.setitem(tts.VOICES, voice_id, voice)
    monkeypatch.setattr(tts, "_integrity_cache", {})
    monkeypatch.setattr(tts.importlib.util, "find_spec", lambda _: object())
    assert tts.model_ready(voice_id)[0]
    old_stat = config.stat()
    config.write_bytes(b"changed configuration")
    os.utime(config, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert not tts.model_ready(voice_id)[0]


@pytest.mark.parametrize("voice_id", list(tts.VOICES))
def test_cancel_invalidates_queued_generation_without_starting_model(tmp_path, voice_id):
    worker = tts.Worker()
    old_generation = worker.generation
    worker.stop()
    with pytest.raises(tts.SpeechCancelled):
        worker.synthesize("queued", 1.0, tmp_path / "unused.wav", old_generation, voice_id)
    assert not worker.loaded
    assert not (tmp_path / "unused.wav").exists()


def test_cache_limit_preserves_current_fragment(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(tts, "CACHE_LIMIT", 6)
    old = tmp_path / "old.wav"
    current = tmp_path / "current.wav"
    old.write_bytes(b"123456")
    current.write_bytes(b"123456")
    tts._trim_cache(current)
    assert current.exists()
    assert not old.exists()


def test_included_router_stops_worker_at_server_shutdown(monkeypatch):
    calls = []
    class FakeWorker:
        def stop(self):
            calls.append("stopped")
    monkeypatch.setattr(tts, "worker", FakeWorker())
    app = FastAPI()
    app.include_router(tts.router)
    with TestClient(app):
        assert not calls
    assert calls == ["stopped"]


def test_status_lists_available_voices_and_keeps_dmitri_default(client, monkeypatch):
    monkeypatch.setattr(tts, "model_ready", lambda voice_id=tts.VOICE_ID: (True, "ready"))
    data = client.get("/api/tts/status").json()
    assert data["default_voice"] == data["voice"] == "ru_RU-dmitri-medium"
    assert [voice["id"] for voice in data["voices"]] == list(tts.VOICES)
    assert len(data["voices"]) == len(tts.VOICES)
    assert data["voices"][-1]["language"] == "en-US"
    assert "английский" in data["voices"][-1]["name"]
    monkeypatch.setattr(tts, "model_ready", lambda voice_id=tts.VOICE_ID: (voice_id != "ru_RU-denis-medium", "damaged"))
    data = client.get("/api/tts/status").json()
    assert data["ready"]
    assert {voice["id"] for voice in data["voices"]} == set(tts.VOICES) - {"ru_RU-denis-medium"}
    assert [voice["id"] for voice in data["downloadable_voices"]] == ["ru_RU-denis-medium"]


def test_cache_separates_voices_and_model_configuration(monkeypatch):
    paths = {tts._cache_path("Одинаковый текст", 1.0, voice_id) for voice_id in tts.VOICES}
    assert len(paths) == len(tts.VOICES)
    original = tts._cache_path("Одинаковый текст", 1.0)
    voice = tts.VOICES[tts.VOICE_ID]
    monkeypatch.setitem(tts.VOICES, tts.VOICE_ID, replace(voice, config_sha256="0" * 64))
    assert tts._cache_path("Одинаковый текст", 1.0) != original
    monkeypatch.setitem(tts.VOICES, tts.VOICE_ID, replace(voice, model_sha256="0" * 64))
    assert tts._cache_path("Одинаковый текст", 1.0) != original


def test_cancel_during_integrity_check_prevents_new_synthesis(client, monkeypatch):
    def checked(_voice_id):
        tts.worker.stop()
        return True, "ready"
    monkeypatch.setattr(tts, "model_ready", checked)
    response = client.post("/api/tts/synthesize", json={"text":"Отменённый фрагмент", "voice":"ru_RU-irina-medium"})
    assert response.status_code == 409
    assert not tts.worker.loaded


def test_real_russian_synthesis_speed_cache_and_audio_ranges(client, monkeypatch, tmp_path):
    ready, message = tts.model_ready()
    if not ready:
        pytest.skip(message)
    monkeypatch.setattr(tts, "AUDIO_DIR", tmp_path)
    text = "Привет, мир! Сегодня прекрасный день."
    try:
        normal = client.post("/api/tts/synthesize", json={"text": text, "rate": 1})
        assert normal.status_code == 200, normal.text
        data = normal.json()
        assert data["sample_rate"] == 22050
        # A legacy Windows codepage corrupts Russian into much longer speech.
        assert 0.5 < data["duration"] < 8
        sound = client.get(data["url"])
        assert sound.status_code == 200
        with wave.open(io.BytesIO(sound.content), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            samples = array.array("h", wav.readframes(wav.getnframes()))
        assert max(abs(x) for x in samples) > 100
        ranged = client.get(data["url"], headers={"Range": "bytes=0-43"})
        assert ranged.status_code == 206
        assert len(ranged.content) == 44
        fast = client.post("/api/tts/synthesize", json={"text": text, "rate": 1.7})
        assert fast.status_code == 200, fast.text
        assert fast.json()["duration"] < data["duration"] * 0.85
        tts.worker.stop()
        cached = client.post("/api/tts/synthesize", json={"text": text, "rate": 1})
        assert cached.status_code == 200
        assert cached.json()["cached"] is True
        assert not tts.worker.loaded
    finally:
        tts.worker.stop()


def test_real_voice_switching_in_one_worker_and_separate_audio_cache(client, monkeypatch, tmp_path):
    available = [voice.id for voice in tts.VOICES.values() if voice.language == "ru-RU" and tts.model_ready(voice.id)[0]]
    if len(available) < 2:
        pytest.skip("Two installed Russian models are required; optional voices are never auto-downloaded")
    monkeypatch.setattr(tts, "AUDIO_DIR", tmp_path)
    text = "Добрый вечер. Откроем любимую книгу."
    urls, hashes, pids = [], [], set()
    try:
        for voice_id in available:
            response = client.post("/api/tts/synthesize", json={"text":text, "voice":voice_id})
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["voice"] == voice_id
            assert not data["cached"]
            assert data["sample_rate"] == 22050
            assert 0.5 < data["duration"] < 10
            sound = client.get(data["url"])
            with wave.open(io.BytesIO(sound.content), "rb") as wav:
                samples = array.array("h", wav.readframes(wav.getnframes()))
            assert max(abs(sample) for sample in samples) > 100
            urls.append(data["url"])
            hashes.append(hashlib.sha256(sound.content).hexdigest())
            pids.add(tts.worker._process.pid)
        assert len(set(urls)) == len(set(hashes)) == len(available)
        # Switch back to the default with fresh text, exercising model reload.
        response = client.post("/api/tts/synthesize", json={"text":text + " Продолжаем читать."})
        assert response.status_code == 200, response.text
        assert response.json()["voice"] == tts.VOICE_ID
        pids.add(tts.worker._process.pid)
        assert len(pids) == 1
        tts.worker.stop()
        for voice_id, url in zip(available, urls):
            data = client.post("/api/tts/synthesize", json={"text":text, "voice":voice_id}).json()
            assert data["cached"] and data["url"] == url
        assert not tts.worker.loaded
    finally:
        tts.worker.stop()

def test_bundled_default_voice_seeds_without_overwriting_user_files(monkeypatch, tmp_path):
    import json
    manifest = json.loads((tts.APP_DIR / 'model-manifest.json').read_text(encoding='utf-8'))
    voice = manifest['voices'][0]
    bundle = tmp_path / 'vendor/voices' / Path(voice['directory']).name
    bundle.mkdir(parents=True)
    for item in voice['files']:
        content = ('fixture-' + item['name']).encode()
        item['bytes'] = len(content)
        item['sha256'] = hashlib.sha256(content).hexdigest()
        (bundle / item['name']).write_bytes(content)
    (tmp_path / 'model-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setattr(tts, 'APP_DIR', tmp_path)
    monkeypatch.setattr(tts, 'DATA_DIR', tmp_path / 'profile')
    _, voices = tts._load_voices()
    model = voices[voice['id']].path
    assert model.read_bytes() == (bundle / model.name).read_bytes()
    model.write_bytes(b'existing-user-file')
    tts._load_voices()
    assert model.read_bytes() == b'existing-user-file'
    assert not (tmp_path / 'profile/models/piper-ru-ruslan').exists()

