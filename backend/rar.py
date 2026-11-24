"""Small Windows x64 UnRAR SDK adapter. Never extracts archive paths to disk.

The bundled, pinned DLL is from RARLAB; ctypes declarations follow its official
packed unrar.h ABI. RAR_TEST streams only the selected member into a bounded
buffer. Passwords, split volumes, links and oversized dictionaries are refused.
"""
from __future__ import annotations

import ctypes as C
import hashlib
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from .parsers import BookParseError

DLL_PATH = Path(__file__).resolve().parent.parent / "vendor" / "unrar" / "UnRAR64.dll"
DLL_SHA256 = "a074b4a27425d1f7636c54a1fe9062e50cbd2b45955bd4d3057bdda1bed82cd5"
MAX_FILES = 30_000
MAX_EXPANDED = 2 * 1024**3
MAX_MEMBER = 1024**3
MAX_DICTIONARY_KIB = 128 * 1024
MAX_SECONDS = 60
RAR_SKIP, RAR_TEST = 0, 1
_dll = None
_lock = threading.RLock()
# WinDLL/WINFUNCTYPE are absent on other platforms; importing the module there
# still works and use produces a clear message rather than an import failure.
_Callback = getattr(C, "WINFUNCTYPE", C.CFUNCTYPE)(C.c_int, C.c_uint, C.c_ssize_t, C.c_ssize_t, C.c_ssize_t)


class _OpenData(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("ArcName", C.c_char_p), ("ArcNameW", C.c_wchar_p),
        ("OpenMode", C.c_uint), ("OpenResult", C.c_uint),
        ("CmtBuf", C.c_void_p), ("CmtBufSize", C.c_uint), ("CmtSize", C.c_uint), ("CmtState", C.c_uint),
        ("Flags", C.c_uint), ("Callback", _Callback), ("UserData", C.c_ssize_t),
        ("OpFlags", C.c_uint), ("CmtBufW", C.c_void_p), ("MarkOfTheWeb", C.c_void_p),
        ("Reserved", C.c_uint * 23),
    ]


class _Header(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("ArcName", C.c_char * 1024), ("ArcNameW", C.c_wchar * 1024),
        ("FileName", C.c_char * 1024), ("FileNameW", C.c_wchar * 1024),
        *[(name, C.c_uint) for name in ("Flags", "PackSize", "PackSizeHigh", "UnpSize", "UnpSizeHigh", "HostOS", "FileCRC", "FileTime", "UnpVer", "Method", "FileAttr")],
        ("CmtBuf", C.c_void_p),
        *[(name, C.c_uint) for name in ("CmtBufSize", "CmtSize", "CmtState", "DictSize", "HashType")],
        ("Hash", C.c_char * 32), ("RedirType", C.c_uint), ("RedirName", C.c_void_p),
        *[(name, C.c_uint) for name in ("RedirNameSize", "DirTarget", "MtimeLow", "MtimeHigh", "CtimeLow", "CtimeHigh", "AtimeLow", "AtimeHigh")],
        ("ArcNameEx", C.c_void_p), ("ArcNameExSize", C.c_uint),
        ("FileNameEx", C.c_void_p), ("FileNameExSize", C.c_uint), ("Reserved", C.c_uint * 982),
    ]


def _library():
    global _dll
    if _dll is not None:
        return _dll
    if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
        raise BookParseError("CBR пока поддерживается только в версии Переплёта для Windows x64")
    if not DLL_PATH.is_file() or hashlib.sha256(DLL_PATH.read_bytes()).hexdigest() != DLL_SHA256:
        raise BookParseError("Библиотека UnRAR отсутствует или повреждена; восстановите vendor/unrar из поставки Переплёта")
    try:
        dll = C.WinDLL(str(DLL_PATH.resolve()), winmode=0x1100)
        dll.RAROpenArchiveEx.argtypes = [C.POINTER(_OpenData)]
        dll.RAROpenArchiveEx.restype = C.c_void_p
        dll.RARReadHeaderEx.argtypes = [C.c_void_p, C.POINTER(_Header)]
        dll.RARReadHeaderEx.restype = C.c_int
        dll.RARProcessFileW.argtypes = [C.c_void_p, C.c_int, C.c_wchar_p, C.c_wchar_p]
        dll.RARProcessFileW.restype = C.c_int
        dll.RARCloseArchive.argtypes = [C.c_void_p]
        dll.RARCloseArchive.restype = C.c_int
        dll.RARGetDllVersion.argtypes = []
        dll.RARGetDllVersion.restype = C.c_int
        if dll.RARGetDllVersion() != 9:
            raise BookParseError("Версия UnRAR несовместима с Переплётом")
    except OSError as exc:
        raise BookParseError("Не удалось загрузить встроенную библиотеку UnRAR") from exc
    _dll = dll
    return dll


def safe_name(value: str) -> str:
    # Backslashes are normal RAR directory separators, unlike ZIP's canonical '/'.
    # UnRAR may already replace illegal Windows characters (e.g. ':' -> '_').
    # These names are identifiers only: no native extraction operation is used.
    name = value.replace("\\", "/")
    if not name or len(name) > 1024 or "\x00" in name or name.startswith("/"):
        raise BookParseError("Небезопасный или слишком длинный путь внутри CBR")
    parts = PurePosixPath(name).parts
    if not parts or any(part == ".." or ":" in part for part in parts):
        raise BookParseError("Небезопасный путь внутри CBR")
    return str(PurePosixPath(name))


class _State:
    def __init__(self, maximum=0):
        self.maximum = maximum
        self.collecting = False
        self.buffer = bytearray()
        self.processed = 0
        self.error = ""
        self.deadline = time.monotonic() + MAX_SECONDS

    def callback(self, message, _user, pointer, length):
        # Exceptions must not unwind through the native callback boundary.
        try:
            if time.monotonic() > self.deadline:
                self.error = "Чтение CBR заняло слишком много времени"
                return -1
            if message in {0, 3}:
                self.error = "Многотомные CBR пока не поддерживаются"
                return -1
            if message in {2, 4}:
                self.error = "CBR защищён паролем; такие архивы пока не поддерживаются"
                return -1
            if message == 5:
                if pointer > MAX_DICTIONARY_KIB:
                    self.error = "Словарь сжатия CBR превышает лимит 128 МБ"
                    return -1
                return 1
            if message == 1:
                if length < 0 or length > MAX_MEMBER or (length and not pointer):
                    self.error = "Повреждён поток данных CBR"
                    return -1
                self.processed += length
                if self.processed > MAX_EXPANDED:
                    self.error = "Распакованные данные CBR превышают лимит 2 ГБ"
                    return -1
                if self.collecting:
                    if len(self.buffer) + length > self.maximum:
                        self.error = "Страница CBR превышает разрешённый размер"
                        return -1
                    self.buffer.extend(C.string_at(pointer, length))
                return 1
            return 0
        except Exception:
            self.error = "Не удалось обработать поток данных CBR"
            return -1


def _check(code: int, state: _State) -> None:
    if state.error:
        raise BookParseError(state.error)
    if code in {22, 24}:
        raise BookParseError("CBR защищён паролем; такие архивы пока не поддерживаются")
    if code == 25:
        raise BookParseError("Словарь сжатия CBR превышает лимит 128 МБ")
    if code:
        raise BookParseError(f"Не удалось прочитать CBR: повреждённый или неподдерживаемый RAR (код {code})")


@contextmanager
def _archive(source: Path, extract: bool, state: _State):
    # One native operation at a time also bounds dictionary allocations.
    with _lock:
        dll = _library()
        callback = _Callback(state.callback)
        data = _OpenData()
        data.ArcNameW = str(Path(source).resolve())
        data.OpenMode = 1 if extract else 0
        data.Callback = callback
        handle = dll.RAROpenArchiveEx(C.byref(data))
        try:
            _check(data.OpenResult, state)
            if not handle:
                raise BookParseError("Не удалось открыть CBR")
            if data.Flags & 0x0001:
                raise BookParseError("Многотомные CBR пока не поддерживаются")
            if data.Flags & 0x0080:
                raise BookParseError("CBR защищён паролем; такие архивы пока не поддерживаются")
            yield dll, handle
        finally:
            if handle:
                dll.RARCloseArchive(handle)


def _headers(dll, handle, state):
    names, total = set(), 0
    for _ in range(MAX_FILES + 1):
        header = _Header()
        # SDK 7 allows long names; read them fully before enforcing our limit.
        name_buffer = C.create_unicode_buffer(65536)
        header.FileNameEx = C.addressof(name_buffer)
        header.FileNameExSize = len(name_buffer)
        code = dll.RARReadHeaderEx(handle, C.byref(header))
        if code == 10:
            return
        _check(code, state)
        if len(names) >= MAX_FILES:
            raise BookParseError("В CBR слишком много файлов")
        name = safe_name(name_buffer.value or header.FileNameW)
        folded = name.casefold()
        if folded in names:
            raise BookParseError("В CBR есть повторяющиеся имена файлов")
        names.add(folded)
        size = header.UnpSize | (header.UnpSizeHigh << 32)
        total += size
        if size > MAX_MEMBER or total > MAX_EXPANDED:
            raise BookParseError("CBR превышает лимит распаковки: 1 ГБ на файл / 2 ГБ на архив")
        if header.Flags & 0x04:
            raise BookParseError("CBR защищён паролем; такие архивы пока не поддерживаются")
        if header.Flags & 0x03:
            raise BookParseError("Многотомные CBR пока не поддерживаются")
        if header.RedirType:
            raise BookParseError("Ссылки и перенаправления внутри CBR не поддерживаются")
        if header.DictSize > MAX_DICTIONARY_KIB:
            raise BookParseError("Словарь сжатия CBR превышает лимит 128 МБ")
        yield {"name": name, "size": size, "directory": bool(header.Flags & 0x20)}
        if time.monotonic() > state.deadline:
            raise BookParseError("Чтение CBR заняло слишком много времени")


def members(source: Path) -> list[dict]:
    """List and validate headers without decompressing the archive contents."""
    state, result = _State(), []
    with _archive(source, False, state) as (dll, handle):
        for item in _headers(dll, handle, state):
            result.append(item)
            _check(dll.RARProcessFileW(handle, RAR_SKIP, None, None), state)
    return result


def read_member(source: Path, name: str, maximum: int) -> bytes:
    """Read a single regular member using RAR_TEST, with no extraction target.

    Solid archives must decode earlier entries. They are discarded; only the
    requested member is buffered. The paged renderer caches its resulting PNG.
    """
    if not 0 < maximum <= MAX_MEMBER:
        raise ValueError("Некорректный лимит чтения CBR")
    wanted = safe_name(name)
    state = _State(maximum)
    with _archive(source, True, state) as (dll, handle):
        for item in _headers(dll, handle, state):
            selected = item["name"] == wanted
            if selected and (item["directory"] or item["size"] > maximum):
                raise BookParseError("Некорректная или слишком большая страница CBR")
            state.collecting = selected
            _check(dll.RARProcessFileW(handle, RAR_TEST if selected else RAR_SKIP, None, None), state)
            if selected:
                if len(state.buffer) != item["size"]:
                    raise BookParseError("Размер страницы CBR не совпадает с заголовком")
                return bytes(state.buffer)
    raise BookParseError("Страница отсутствует в исходном CBR")
