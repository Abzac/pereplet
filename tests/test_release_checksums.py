import hashlib

import pytest

from scripts.release_checksums import ASSETS, generate


def prepare(directory):
    for name in ASSETS:
        data = name.encode('ascii')
        (directory / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        (directory / (name + '.sha256')).write_text(f'{digest}  {name}\n', encoding='ascii')


def test_manifest_contains_both_exact_filenames_and_hashes(tmp_path):
    prepare(tmp_path)
    generate(tmp_path)
    manifest = (tmp_path / 'SHA256SUMS.txt').read_bytes()
    assert b'\r' not in manifest
    assert manifest == b''.join((tmp_path / (name + '.sha256')).read_bytes().replace(b'\r\n', b'\n') for name in ASSETS)


def test_modified_asset_prevents_manifest_creation(tmp_path):
    prepare(tmp_path)
    (tmp_path / ASSETS[1]).write_bytes(b'corrupted installer')
    with pytest.raises(ValueError, match='checksum mismatch'):
        generate(tmp_path)
    assert not (tmp_path / 'SHA256SUMS.txt').exists()
