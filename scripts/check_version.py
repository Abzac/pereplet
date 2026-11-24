import json, os, re, tomllib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
tag = os.environ['RELEASE_TAG']
if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', tag):
    raise SystemExit('Expected tag vX.Y.Z or vX.Y.Z-prerelease')
version = tag[1:]
versions = [tomllib.loads((root/'src-tauri/Cargo.toml').read_text())['package']['version']]
for path in ('src-tauri/tauri.conf.json', 'frontend/package.json'):
    versions.append(json.loads((root/path).read_text())['version'])
if any(v != version for v in versions):
    raise SystemExit(f'Tag version must match Cargo.toml, tauri.conf.json and frontend/package.json: {versions}')
print('Release version verified:', version)
