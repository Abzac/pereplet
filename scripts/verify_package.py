"""Fail a release if generated state or local build paths escaped the allowlist."""
from pathlib import Path
import sys

def verify(root):
    assert not (root / 'data').exists(), 'User data must never be packaged'
    forbidden = {'node_modules', '__pycache__', '.git', '.venv', 'personal', 'target'}
    checkout = str(Path(__file__).resolve().parents[1])
    patterns = [checkout.encode(), checkout.replace('\\', '/').encode(), checkout.encode('utf-16le')]
    count = 0
    for p in root.rglob('*'):
        if not p.is_file(): continue
        rel = p.relative_to(root)
        assert not forbidden.intersection(rel.parts), f'Generated directory in package: {rel}'
        assert p.suffix.lower() not in {'.sqlite', '.sqlite3', '.db', '.log', '.lnk'}, f'Unexpected state file: {rel}'
        if p.suffix.lower() in {'.exe', '.dll', '.json', '.js', '.py', '.md', '.toml', '.ps1', '.yml'}:
            content = p.read_bytes()
            assert not any(pattern in content for pattern in patterns), f'Local checkout path in {rel}'
        count += 1
    assert (root / 'Pereplet.exe').exists() and (root / 'webview2/msedgewebview2.exe').exists()
    print(f'Package hygiene passed: {count} files')

if __name__ == '__main__': verify(Path(sys.argv[1]).resolve())
