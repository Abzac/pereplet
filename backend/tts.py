"""Local neural speech API backed by a bounded, separate Piper process."""
from __future__ import annotations

import asyncio
import atexit
import hashlib
import importlib.util
import json
import os
import queue
import shutil
import re
import subprocess
import sys
import threading
import time
import uuid
import wave
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .tts_text import russian_yo

APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("PEREPLET_DATA_DIR", str(APP_DIR / "data"))).resolve()
AUDIO_DIR = DATA_DIR / "tts-cache"
CACHE_LIMIT = 256 * 1024 * 1024
MAX_TEXT_LENGTH = 6000


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    path: Path
    model_sha256: str
    config_sha256: str
    language: str = "ru-RU"
    license: str = ""
    files: tuple[dict, ...] = ()


def _load_voices() -> tuple[str, dict[str, Voice]]:
    manifest = json.loads((APP_DIR / "model-manifest.json").read_text(encoding="utf-8"))
    voices = {}
    for entry in manifest["voices"]:
        voice_id = entry["id"]
        directory = Path(entry["directory"])
        if (not re.fullmatch(r"(?:ru_RU|en_US)-[a-z]+-medium", voice_id)
                or directory.parent.as_posix() != "data/models"
                or not re.fullmatch(r"piper-(?:ru|en)-[a-z]+", directory.name)):
            raise ValueError("Invalid voice manifest path")
        files = {file["name"]: file for file in entry["files"]}
        for file in files.values():
            if (not re.fullmatch(r"[A-Za-z0-9_.-]+", file["name"])
                    or not re.fullmatch(r"[a-f0-9]{64}", file["sha256"])
                    or not 0 < file["bytes"] <= 128 * 1024**2
                    or not file["url"].startswith("https://huggingface.co/rhasspy/piper-voices/resolve/")):
                raise ValueError("Invalid voice download manifest")
        # Ship only the default voice; user downloads remain in their own data directory.
        bundled = APP_DIR / "vendor" / "voices" / directory.name
        destination = DATA_DIR / "models" / directory.name
        if voice_id == manifest["default_voice"] and bundled.is_dir():
            for file in files.values():
                source = bundled / file["name"]
                target = destination / file["name"]
                if target.exists():
                    continue
                with source.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != file["sha256"]:
                        raise ValueError("Bundled voice checksum mismatch")
                destination.mkdir(parents=True, exist_ok=True)
                temporary = destination / (file["name"] + "." + uuid.uuid4().hex + ".tmp")
                shutil.copyfile(source, temporary)
                temporary.replace(target)
        model_hash = files[voice_id + ".onnx"]["sha256"]
        config_hash = files[voice_id + ".onnx.json"]["sha256"]
        if not all(re.fullmatch(r"[a-f0-9]{64}", value) for value in (model_hash, config_hash)):
            raise ValueError("Invalid voice manifest checksum")
        voices[voice_id] = Voice(voice_id, entry["display_name"], DATA_DIR / "models" / directory.name / (voice_id + ".onnx"), model_hash, config_hash,
                                 entry.get("language", "ru-RU"), entry.get("dataset_license_in_model_card", ""), tuple(files.values()))
    default = manifest["default_voice"]
    if default not in voices:
        raise ValueError("Default voice is missing from the manifest")
    return default, voices


VOICE_ID, VOICES = _load_voices()

@asynccontextmanager
async def lifespan(_app):
    try:
        yield
    finally:
        await asyncio.to_thread(worker.stop)


router = APIRouter(prefix="/api/tts", tags=["tts"], lifespan=lifespan)


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    voice: str | None = None
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    russian_yo: bool = False


class SpeechCancelled(RuntimeError):
    pass


class Worker:
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._messages: queue.Queue | None = None
        self._state_lock = threading.RLock()
        self._io_lock = threading.Lock()
        self._idle_timer: threading.Timer | None = None
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._state_lock:
            return self._generation

    @property
    def loaded(self) -> bool:
        with self._state_lock:
            return bool(self._process and self._process.poll() is None)

    def _start(self, generation: int) -> tuple[subprocess.Popen, queue.Queue]:
        with self._state_lock:
            if generation != self._generation:
                raise SpeechCancelled("Озвучка остановлена")
            if self._idle_timer:
                self._idle_timer.cancel()
            if self._process is not None and self._process.poll() is None:
                return self._process, self._messages  # type: ignore[return-value]
            AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            messages: queue.Queue = queue.Queue()
            process = subprocess.Popen(
                [sys.executable, "-X", "utf8", "-u", str(Path(__file__).with_name("tts_worker.py"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                cwd=str(APP_DIR),
            )
            self._process, self._messages = process, messages

            def read_output() -> None:
                try:
                    assert process.stdout
                    for line in process.stdout:
                        try:
                            messages.put(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                finally:
                    messages.put({"closed": True})

            threading.Thread(target=read_output, daemon=True, name="pereplet-tts-output").start()
            return process, messages

    def stop(self) -> None:
        with self._state_lock:
            self._generation += 1
            process = self._process
            self._process, self._messages = None, None
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for stream in [process.stdin, process.stdout]:
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def synthesize(self, text: str, rate: float, destination: Path, generation: int | None = None, voice_id: str = VOICE_ID) -> dict:
        generation = self.generation if generation is None else generation
        with self._io_lock:
            process, messages = self._start(generation)
            request_id = uuid.uuid4().hex
            request = {"id": request_id, "text": text, "rate": rate, "model": str(VOICES[voice_id].path), "output": str(destination)}
            try:
                assert process.stdin
                process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                process.stdin.flush()
                deadline = time.monotonic() + 120
                while True:
                    result = messages.get(timeout=max(0.1, deadline - time.monotonic()))
                    if result.get("closed"):
                        raise SpeechCancelled("Озвучка остановлена")
                    if result.get("id") == request_id:
                        if generation != self.generation:
                            raise SpeechCancelled("Озвучка остановлена")
                        if not result.get("ok"):
                            raise RuntimeError(result.get("error", "Ошибка локального синтеза"))
                        return result
                    if time.monotonic() >= deadline:
                        raise queue.Empty
            except queue.Empty:
                self.stop()
                raise RuntimeError("Локальный синтез не ответил за 120 секунд") from None
            except (BrokenPipeError, OSError):
                self.stop()
                raise SpeechCancelled("Процесс озвучки остановлен") from None
            finally:
                destination.with_suffix(".part.wav").unlink(missing_ok=True)
                with self._state_lock:
                    if self._process is process:
                        self._idle_timer = threading.Timer(180, self.stop)
                        self._idle_timer.daemon = True
                        self._idle_timer.start()


worker = Worker()
atexit.register(worker.stop)
_integrity_cache: dict[str, tuple[tuple, bool]] = {}
_integrity_lock = threading.Lock()
_slots = asyncio.Semaphore(2)
_download_slot = asyncio.Lock()
_downloading: set[str] = set()


def model_ready(voice_id: str = VOICE_ID) -> tuple[bool, str]:
    voice = VOICES.get(voice_id)
    if voice is None:
        return False, "Этот голос не установлен"
    if importlib.util.find_spec("piper") is None:
        return False, "Для локальной озвучки запустите setup-tts.ps1 в папке приложения."
    config = voice.path.with_suffix(".onnx.json")
    try:
        stat = voice.path.stat()
        config_stat = config.stat()
        key = (str(voice.path), voice.model_sha256, voice.config_sha256, stat.st_size, stat.st_mtime_ns, config_stat.st_size, config_stat.st_mtime_ns)
        with _integrity_lock:
            previous = _integrity_cache.get(voice_id)
            if previous is None or previous[0] != key:
                with voice.path.open("rb") as model_file:
                    model_ok = hashlib.file_digest(model_file, "sha256").hexdigest() == voice.model_sha256
                with config.open("rb") as config_file:
                    config_ok = hashlib.file_digest(config_file, "sha256").hexdigest() == voice.config_sha256
                _integrity_cache[voice_id] = (key, model_ok and config_ok)
            integrity_ok = _integrity_cache[voice_id][1]
    except OSError:
        return False, f"Голос {voice.name} ещё не загружен. Нажмите «Скачать ещё голоса» и выберите голос."
    return (integrity_ok, f"Готов к чтению. {voice.name}, локально на CPU." if integrity_ok else f"Проверка голоса {voice.name} не пройдена. Скачайте этот голос повторно через «Скачать ещё голоса».")


def _cache_path(text: str, rate: float, voice_id: str = VOICE_ID) -> Path:
    voice = VOICES[voice_id]
    key = json.dumps({"text": text, "rate": rate, "voice": voice_id, "model": voice.model_sha256, "config": voice.config_sha256, "engine": "piper-1.8.0", "v": 3}, sort_keys=True, ensure_ascii=False)
    return AUDIO_DIR / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".wav")


def _audio_info(path: Path) -> dict:
    with wave.open(str(path), "rb") as audio:
        return {"duration": audio.getnframes() / audio.getframerate(), "sample_rate": audio.getframerate()}


def _trim_cache(keep: Path) -> None:
    entries = []
    for path in AUDIO_DIR.glob("*.wav"):
        try:
            stat = path.stat()
            entries.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            continue
    total = sum(size for _, size, _ in entries)
    for _, size, path in sorted(entries):
        if total <= CACHE_LIMIT:
            break
        if path == keep or path.name.endswith(".part.wav"):
            continue
        try:
            path.unlink()
            total -= size
        except OSError:
            pass


def _file_verified(path: Path, expected: dict) -> bool:
    try:
        if path.stat().st_size != expected["bytes"]:
            return False
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == expected["sha256"]
    except OSError:
        return False


async def _download_voice(voice: Voice, request: Request | None = None) -> None:
    directory = voice.path.parent.resolve()
    if directory.parent != (DATA_DIR / "models").resolve():
        raise ValueError("Некорректная папка модели")
    directory.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[Path, Path]] = []
    try:
        # Download into adjacent temporary files. Nothing replaces an existing
        # model until every requested file has passed its pinned checksum.
        async with asyncio.timeout(600), httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20), follow_redirects=True, max_redirects=6) as client:
            for entry in voice.files:
                target = directory / entry["name"]
                if await asyncio.to_thread(_file_verified, target, entry):
                    continue
                temporary = directory / f".{entry['name']}.{uuid.uuid4().hex}.download"
                staged.append((temporary, target))
                digest, size = hashlib.sha256(), 0
                async with client.stream("GET", entry["url"]) as response:
                    response.raise_for_status()
                    with temporary.open("xb") as stream:
                        async for chunk in response.aiter_bytes(512 * 1024):
                            if request is not None and await request.is_disconnected():
                                raise asyncio.CancelledError("Загрузка голоса отменена")
                            size += len(chunk)
                            if size > entry["bytes"]:
                                raise ValueError("Размер загружаемого голоса не совпадает с manifest")
                            digest.update(chunk)
                            stream.write(chunk)
                if size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
                    raise ValueError("Проверка SHA-256 загруженного голоса не пройдена")
            for temporary, target in staged:
                temporary.replace(target)
        with _integrity_lock:
            _integrity_cache.pop(voice.id, None)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


@router.post("/voices/{voice_id}/download")
async def download_voice(voice_id: str, request: Request) -> dict:
    voice = VOICES.get(voice_id)
    if voice is None:
        raise HTTPException(404, "Голос не найден в списке доступных моделей")
    if _download_slot.locked():
        raise HTTPException(409, "Другой голос уже загружается. Дождитесь завершения.")
    async with _download_slot:
        _downloading.add(voice_id)
        try:
            await _download_voice(voice, request)
            ready, message = await asyncio.to_thread(model_ready, voice_id)
            return {"ok": True, "ready": ready, "voice": voice_id, "message": message}
        except (httpx.HTTPError, TimeoutError) as exc:
            raise HTTPException(502, "Загрузить голос не удалось. Проверьте соединение и повторите.") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            _downloading.discard(voice_id)


@router.get("/status")
def status() -> dict:
    available = [voice for voice in VOICES.values() if model_ready(voice.id)[0]]
    preferred = next((voice for voice in available if voice.id == VOICE_ID), available[0] if available else None)
    message = "Готовы к чтению: " + ", ".join(voice.name for voice in available) + ". Локально на CPU." if available else model_ready()[1]
    return {
        "ready": bool(available), "model": "Piper · " + (preferred.name if preferred else VOICES[VOICE_ID].name), "voice": preferred.id if preferred else VOICE_ID,
        "default_voice": VOICE_ID,
        "voices": [{"id": voice.id, "name": f"{voice.name} · {'русский' if voice.language.startswith('ru') else 'английский'} · локально", "display_name": voice.name, "language": voice.language, "engine": "Piper"} for voice in available],
        "downloadable_voices": [{"id": voice.id, "name": voice.name,
                                  "label": f"{voice.name} · {'русский' if voice.language.startswith('ru') else 'английский'} · Piper",
                                  "language": voice.language, "license": voice.license,
                                  "size_mb": round(sum(file['bytes'] for file in voice.files) / 1_000_000, 1),
                                  "downloading": voice.id in _downloading}
                                 for voice in VOICES.values() if voice not in available],
        "message": message, "loaded": worker.loaded, "local": True,
        "capabilities": {"rate": True, "volume": True, "pitch": False, "word_timestamps": False, "highlight": "paragraph", "russian_yo": True},
    }


@router.post("/synthesize")
async def synthesize(req: SpeechRequest) -> dict:
    generation = worker.generation
    text = req.text.strip()
    if not text:
        raise HTTPException(422, "Для озвучки нужен текст")
    voice_id = req.voice or VOICE_ID
    if voice_id not in VOICES:
        raise HTTPException(400, "Этот голос не установлен")
    yo_enabled = bool(req.russian_yo and VOICES[voice_id].language.startswith("ru"))
    text, replacements = russian_yo(text) if yo_enabled else (text, 0)
    normalization = {"russian_yo": yo_enabled, "replacements": replacements}
    ready, message = await asyncio.to_thread(model_ready, voice_id)
    if not ready:
        raise HTTPException(503, message)
    if generation != worker.generation:
        raise HTTPException(409, "Озвучка остановлена")
    destination = _cache_path(text, req.rate, voice_id)
    if destination.is_file():
        try:
            info = _audio_info(destination)
            os.utime(destination, None)
            return {"url": f"/api/tts/audio/{destination.name}", "cached": True, "voice": voice_id, "normalization": normalization, **info}
        except (wave.Error, EOFError):
            destination.unlink(missing_ok=True)
    # Limit accepted background synthesis to the current and one prefetched paragraph.
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=0.1)
    except asyncio.TimeoutError:
        raise HTTPException(429, "Озвучка занята. Повторите через несколько секунд.") from None
    try:
        result = await asyncio.to_thread(worker.synthesize, text, req.rate, destination, generation, voice_id)
        await asyncio.to_thread(_trim_cache, destination)
        return {"url": f"/api/tts/audio/{destination.name}", "cached": False, "voice": voice_id, "normalization": normalization, "duration": result["duration"], "sample_rate": result["sample_rate"]}
    except SpeechCancelled as exc:
        raise HTTPException(409, str(exc)) from None
    except Exception as exc:
        raise HTTPException(500, f"Ошибка локальной озвучки: {exc}") from None
    finally:
        _slots.release()


@router.post("/cancel")
async def cancel() -> dict:
    await asyncio.to_thread(worker.stop)
    return {"stopped": True}


@router.get("/audio/{filename}")
def audio(filename: str) -> FileResponse:
    if not re.fullmatch(r"[a-f0-9]{64}\.wav", filename):
        raise HTTPException(404, "Фрагмент не найден")
    path = AUDIO_DIR / filename
    if not path.is_file():
        raise HTTPException(404, "Фрагмент больше не хранится в кеше")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, max-age=86400"})
