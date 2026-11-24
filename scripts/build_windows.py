"""Build a clean portable package from this checkout, never from an installed app."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys, urllib.request, uuid, zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
OUT = BUILD / 'Pereplet-Tauri-Windows-x64'
SOURCE_DIRS = ('backend', 'frontend', 'tests', 'src-tauri', 'scripts', 'docs', 'licenses', 'vendor', 'build-assets', '.github', 'starter-books')
SOURCE_FILES = ('README.md', 'LICENSE', 'LICENSE-EXCEPTIONS.md', '.gitignore', '.gitattributes', 'rust-toolchain.toml', 'desktop_server.py', 'runner.py', 'launch.py', 'seed_demo.py', 'setup.ps1', 'setup-tts.ps1', 'Start Pereplet.cmd', 'Start Pereplet.vbs', 'Stop Pereplet.cmd', 'update_catalogs.py', 'app-icon.ico', 'model-manifest.json', 'catalog-defaults.json', 'requirements.txt', 'requirements-tts.txt', 'requirements-portable.txt', 'DEPENDENCIES.json', 'THIRD_PARTY_NOTICES.md')
IGNORE = shutil.ignore_patterns('node_modules', 'target', 'gen', 'dist', '__pycache__', '.pytest_cache', '.git', 'data', '*.pyc', '*.log')

def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()

def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True, **kwargs)

def download(spec):
    path = BUILD / 'downloads' / spec['name']
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temp = path.with_suffix(path.suffix + '.partial')
        with urllib.request.urlopen(spec['url'], timeout=120) as source, temp.open('wb') as target:
            shutil.copyfileobj(source, target)
        if sha256(temp) != spec['sha256']: raise RuntimeError(f"Download checksum mismatch: {spec['name']}")
        temp.replace(path)
    if sha256(path) != spec['sha256']: raise RuntimeError(f"Cached download checksum mismatch: {spec['name']}")
    return path

def copy_source(target):
    target.mkdir(parents=True)
    for name in SOURCE_DIRS: shutil.copytree(ROOT / name, target / name, ignore=IGNORE)
    for name in SOURCE_FILES: shutil.copy2(ROOT / name, target / name)

def rust_licenses():
    raw = subprocess.check_output(['cargo', 'metadata', '--locked', '--format-version', '1', '--filter-platform', 'x86_64-pc-windows-msvc', '--manifest-path', 'src-tauri/Cargo.toml'], cwd=ROOT)
    packages = json.loads(raw)['packages']
    inventory = []
    for p in packages:
        if not p.get('source'): continue
        inventory.append({k: p.get(k) for k in ('name', 'version', 'license', 'source')})
        directory = Path(p['manifest_path']).parent
        dest = OUT / 'licenses/rust' / f"{p['name']}-{p['version']}"
        for item in directory.iterdir():
            if item.name.lower().startswith(('license', 'licence', 'copying', 'notice', 'copyright')):
                dest.mkdir(parents=True, exist_ok=True)
                if item.is_file(): shutil.copy2(item, dest / item.name)
                elif item.is_dir(): shutil.copytree(item, dest / item.name)
        if not dest.exists():
            fallback = {'alloc-stdlib':'alloc-stdlib-0.3.0-LICENSE', 'selectors':'selectors-0.38.0-MPL-2.0.txt',
                        'webview2-com':'webview2-com-0.39.1-LICENSE', 'webview2-com-macros':'webview2-com-0.39.1-LICENSE', 'webview2-com-sys':'webview2-com-0.39.1-LICENSE'}.get(p['name'])
            if not fallback: raise RuntimeError('Missing Rust license text: ' + p['name'])
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / 'licenses/supplemental' / fallback, dest / 'LICENSE')
    (OUT / 'TAURI-DEPENDENCIES.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')

def npm_licenses():
    """Keep copyright/license notices for frontend dependencies in the binary package."""
    frontend = ROOT / 'frontend'
    pending = [(frontend, name) for name in json.loads((frontend / 'package.json').read_text(encoding='utf-8'))['dependencies']]
    inventory, seen = [], set()
    while pending:
        parent, name = pending.pop()
        while not (parent / 'node_modules' / name / 'package.json').is_file():
            if parent == frontend: raise RuntimeError('Missing frontend dependency: ' + name)
            parent = parent.parent
        directory = parent / 'node_modules' / name
        if directory in seen: continue
        seen.add(directory)
        spec = json.loads((directory / 'package.json').read_text(encoding='utf-8'))
        pending.extend((directory, child) for child in spec.get('dependencies', {}))
        inventory.append({'name':name, 'version':spec['version'], 'license':spec.get('license')})
        dest = OUT / 'licenses/npm' / (name.replace('/', '__') + '-' + spec['version'])
        notices = [item for item in directory.iterdir() if item.is_file() and item.name.lower().startswith(('license','licence','copying','notice','copyright','unlicense'))]
        dest.mkdir(parents=True, exist_ok=True)
        for item in notices: shutil.copy2(item, dest / item.name)
        if not notices:
            # These upstream packages declare MIT but ship no standalone license.
            if (name, spec['version'], spec.get('license')) not in {
                ('locate-character', '3.0.0', 'MIT'), ('is-reference', '3.0.3', 'MIT')
            }:
                raise RuntimeError('Missing frontend license text: ' + name)
            for filename in ('package.json', 'README.md'):
                shutil.copy2(directory / filename, dest / filename)
            shutil.copy2(ROOT / 'licenses/supplemental/MIT-declared-packages.txt', dest / 'NOTICE.txt')
    (OUT / 'NPM-DEPENDENCIES.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-tests', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt': raise RuntimeError('Build this Windows distribution on Windows x64')
    if OUT.exists():
        assert OUT.resolve().parent == BUILD.resolve() and not OUT.is_symlink()
        if (OUT / 'data').exists(): raise RuntimeError('Refusing to replace a package containing user data')
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    manifest = json.loads((ROOT / 'build-assets/downloads.json').read_text(encoding='utf-8'))
    assets = {key: download(value) for key, value in manifest.items()}
    runtime = OUT / 'runtime'; runtime.mkdir()
    with zipfile.ZipFile(assets['python']) as z: z.extractall(runtime)
    (runtime / 'python313._pth').write_text('python313.zip\n.\npackages\n..\nimport site\n', encoding='ascii')
    run(sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-compile', '--no-deps', '--require-hashes', '--only-binary=:all:', '--platform', 'win_amd64', '--python-version', '313', '--implementation', 'cp', '--abi', 'cp313', '--target', runtime / 'packages', '-r', ROOT / 'requirements-portable.txt')
    for dll in (ROOT / 'build-assets/vc-runtime').glob('*.dll'): shutil.copy2(dll, runtime / dll.name)
    for name in ('backend', 'vendor', 'licenses', 'starter-books'): shutil.copytree(ROOT / name, OUT / name, ignore=IGNORE)
    for name in ('desktop_server.py', 'catalog-defaults.json', 'model-manifest.json', 'LICENSE', 'LICENSE-EXCEPTIONS.md', 'app-icon.ico', 'DEPENDENCIES.json', 'THIRD_PARTY_NOTICES.md'): shutil.copy2(ROOT / name, OUT / name)
    voices = json.loads((ROOT / 'model-manifest.json').read_text(encoding='utf-8'))
    default_voice = next(v for v in voices['voices'] if v['id'] == voices['default_voice'])
    voice_dir = OUT / 'vendor/voices' / Path(default_voice['directory']).name
    voice_dir.mkdir(parents=True, exist_ok=True)
    for item in default_voice['files']:
        # Prefix cached names because MODEL_CARD is not unique among voices.
        spec = {**item, 'name': default_voice['id'] + '-' + item['name']}
        shutil.copy2(download(spec), voice_dir / item['name'])
    shutil.copytree(ROOT / 'frontend/dist', OUT / 'frontend/dist')
    shutil.copy2(ROOT / 'src-tauri/target/release/pereplet-desktop.exe', OUT / 'Pereplet.exe')
    shutil.copy2(ROOT / 'docs/PORTABLE.md', OUT / 'README.md')
    extract = BUILD / 'webview-extracted'
    if extract.exists():
        assert extract.resolve().parent == BUILD.resolve() and not extract.is_symlink()
        shutil.rmtree(extract)
    extract.mkdir()
    # expand.exe ships with Windows; the entire fixed runtime is retained.
    with (BUILD / 'webview-extract.log').open('w') as log: run('expand.exe', assets['webview2'], '-F:*', extract, stdout=log)
    engines = list(extract.rglob('msedgewebview2.exe'))
    if len(engines) != 1: raise RuntimeError('Unexpected WebView2 CAB layout')
    shutil.copytree(engines[0].parent, OUT / 'webview2')
    (OUT / 'third-party-source').mkdir()
    for key in [key for key in assets if key in ('piper_source', 'espeak_source') or key.startswith('mpl_')]: shutil.copy2(assets[key], OUT / 'third-party-source' / assets[key].name)
    rust_licenses()
    npm_licenses()
    copy_source(OUT / 'source')
    # Remove generated scripts containing builder interpreter paths; libraries remain.
    for name in ('bin', 'Scripts'):
        path = runtime / 'packages' / name
        if path.exists(): shutil.rmtree(path)
    for path in list(OUT.rglob('__pycache__')): shutil.rmtree(path)
    for pattern in ('*.pyc', 'direct_url.json'):
        for path in OUT.rglob(pattern): path.unlink()
    if not args.skip_tests:
        test_packages = BUILD / 'test-packages'
        run(sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-compile', '--upgrade', '--target', test_packages, 'pytest==9.1.1')
        test_temp = BUILD / ('pytest-' + uuid.uuid4().hex)
        code = f"import sys;sys.path[:0]=[{str(ROOT)!r},{str(test_packages)!r}];import pytest;sys.exit(pytest.main([{str(ROOT / 'tests')!r},'-q','--tb=short','--basetemp',{str(test_temp)!r}]))"
        run(runtime / 'python.exe', '-B', '-c', code)
    run(sys.executable, ROOT / 'scripts/verify_package.py', OUT)
    files = sorted(p for p in OUT.rglob('*') if p.is_file())
    hashes = {p.relative_to(OUT).as_posix(): sha256(p) for p in files}
    (OUT / 'SHA256SUMS.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    output = ROOT / 'dist'; output.mkdir(exist_ok=True)
    archive = output / 'Pereplet-Tauri-Windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, strict_timestamps=False) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file(): z.write(p, p.relative_to(OUT.parent))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None: raise RuntimeError('ZIP integrity check failed')
    (output / (archive.name + '.sha256')).write_text(f'{sha256(archive)}  {archive.name}\n', encoding='ascii')
    print(f'Built {archive.name}: {archive.stat().st_size:,} bytes; no user data')

if __name__ == '__main__': main()


