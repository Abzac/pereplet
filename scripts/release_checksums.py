"""Create one SHA-256 manifest for the two Windows release assets."""
from pathlib import Path
import hashlib
import sys

ASSETS = ('Pereplet-Tauri-Windows-x64.zip', 'Pereplet-Setup-Windows-x64.exe')


def generate(directory):
    lines = []
    for name in ASSETS:
        with (directory / name).open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        # Match the checksum produced by each build, before attaching anything.
        expected = (directory / (name + '.sha256')).read_text(encoding='ascii').split()
        if expected != [digest, name]:
            raise ValueError('Build checksum mismatch: ' + name)
        lines.append(f'{digest}  {name}\n')
    (directory / 'SHA256SUMS.txt').write_bytes(''.join(lines).encode('ascii'))
    print('Verified both release files; wrote SHA256SUMS.txt')


if __name__ == '__main__':
    generate(Path(sys.argv[1] if len(sys.argv) > 1 else 'dist'))
