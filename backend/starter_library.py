"""Install the bundled public-domain shelf once, only for a new library."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import library

BUNDLE = Path(__file__).resolve().parent.parent / 'starter-books'
MARKER = 'starter-library-v1.json'


def _write_marker(path: Path, value: dict):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def seed_starter_library() -> int:
    """Resume interrupted first-run import, but never refill a user's empty shelf."""
    marker = library.DATA_DIR / MARKER
    with library._lock:
        state = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else None
        if state and state.get('phase') in {'complete', 'existing-library'}:
            return 0
        existed = (library.DATA_DIR / 'library.sqlite').exists()
        if state is None and existed:
            library.init()
            _write_marker(marker, {'phase': 'existing-library'})
            return 0
        if not (BUNDLE / 'manifest.json').is_file():
            raise RuntimeError('Не найдена стартовая подборка: распакуйте дистрибутив целиком.')
        manifest = json.loads((BUNDLE / 'manifest.json').read_text(encoding='utf-8'))
        entries = manifest['books']
        # Validate all assets before modifying the new library.
        for entry in entries:
            path = (BUNDLE / entry['file']).resolve()
            if path.parent != BUNDLE.resolve() or path.suffix != '.fb2':
                raise ValueError('Некорректный путь стартовой книги')
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError('Повреждена стартовая книга: ' + entry['title'])
        state = state or {'phase': 'pending', 'completed': []}
        library.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _write_marker(marker, state)
        library.init()
        added = 0
        for entry in entries:
            if entry['id'] in state['completed']:
                continue
            result = library.import_path(BUNDLE / entry['file'])
            added += not result['duplicate']
            state['completed'].append(entry['id'])
            _write_marker(marker, state)
        state['phase'] = 'complete'
        _write_marker(marker, state)
        return added


def reader_guide():
    """Open the existing guide, importing only this bundled book when absent."""
    with library._lock:
        for book in library.list_books():
            if book.get('is_reader_guide'):
                return library.get_book(book['id'])
        manifest_path = BUNDLE / 'manifest.json'
        if not manifest_path.is_file():
            raise ValueError('Руководство не найдено. Распакуйте дистрибутив целиком.')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        entry = next((item for item in manifest['books'] if item['id'] == 'reader-guide'), None)
        path = BUNDLE / 'reader-guide.fb2'
        if not entry or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Файл руководства отсутствует или повреждён. Распакуйте дистрибутив целиком.')
        return library.import_path(path)['book']
