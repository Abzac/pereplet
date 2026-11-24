"""Exercise the actual unpacked EXE with a fresh profile; never use real library data."""
from pathlib import Path
import argparse, ctypes, hashlib, json, os, socket, subprocess, time, urllib.request, zipfile

ROOT = Path(__file__).resolve().parents[1]

def request(path):
    with urllib.request.urlopen('http://127.0.0.1:18769'+path, timeout=2) as response:
        return json.load(response)

def ready(process):
    for _ in range(150):
        assert process.poll() is None, 'Desktop exited before becoming ready'
        try: return request('/api/health')
        except OSError: time.sleep(.2)
    raise AssertionError('Desktop server did not start')

def stopped():
    for _ in range(50):
        with socket.socket() as s:
            s.settimeout(.2)
            if s.connect_ex(('127.0.0.1',18769)) != 0: return
        time.sleep(.2)
    raise AssertionError('Backend survived desktop shutdown')

def main():
    with socket.socket() as s:
        assert s.connect_ex(('127.0.0.1',18769)) != 0, 'Close your desktop instance before running this isolated test'
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, help="Test an already installed fresh package")
    args = parser.parse_args()
    if args.root:
        root = args.root.resolve()
    else:
        import tempfile
        (ROOT/"build").mkdir(exist_ok=True)
        dest = Path(tempfile.mkdtemp(prefix="pereplet-smoke-", dir=ROOT/"build"))
        archive = ROOT/"dist/Pereplet-Tauri-Windows-x64.zip"
        with zipfile.ZipFile(archive) as z: z.extractall(dest)
        root = dest/"Pereplet-Tauri-Windows-x64"
    for name, expected in json.loads((root/'SHA256SUMS.json').read_text()).items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == expected, name
    assert not (root/'data').exists()
    env=os.environ.copy()
    env.pop('PEREPLET_QA',None)
    env['PATH']=str(Path(env['WINDIR'])/'System32')+';'+env['WINDIR']
    env['PYTHONHOME']='Z:\\missing-python'; env['PYTHONPATH']='Z:\\missing-python'
    process=subprocess.Popen([str(root/'Pereplet.exe')],cwd=root,env=env)
    try:
        initial=ready(process)
        speech = request('/api/tts/status')
        assert speech['ready'] and any(v['id'] == 'ru_RU-dmitri-medium' for v in speech['voices']), 'Bundled voice unavailable offline'
        books = request('/api/books')
        manifest = json.loads((root/'starter-books/manifest.json').read_text(encoding='utf-8'))
        assert {b['title'] for b in books} == {b['title'] for b in manifest['books']}
        assert len(books) == len(manifest['books']) and all(b['cover_url'] and b['progress'] == 0 for b in books)
        for book in books:
            with urllib.request.urlopen('http://127.0.0.1:18769'+book['cover_url'], timeout=3) as response:
                assert response.headers['Content-Type'].startswith('image/')
                assert len(response.read()) > 1000
        subprocess.run([str(root/'Pereplet.exe')],cwd=root,env=env,timeout=15,check=True)
        assert request('/api/health')['instance'] == initial['instance'], 'Second launch started another server'
        time.sleep(2)
        user32=ctypes.windll.user32
        user32.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
        callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
        def close(hwnd,_):
            pid=ctypes.c_ulong()
            user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd),ctypes.byref(pid))
            title=ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(ctypes.c_void_p(hwnd),title,256)
            if pid.value==process.pid and title.value=='Переплёт': user32.PostMessageW(hwnd,0x10,0,0)
            return True
        user32.EnumWindows(callback(close),0)
        process.wait(timeout=15)
        assert process.returncode==0
        stopped()
        process=subprocess.Popen([str(root/'Pereplet.exe')],cwd=root,env=env)
        ready(process)
        assert len(request('/api/books')) == len(manifest['books']), 'Restart duplicated the starter books'
        process.kill();process.wait(timeout=5);stopped()
        print('Portable smoke passed: checksums, illustrated classics and reader guide, isolated runtime, single instance, normal/crash shutdown')
    finally:
        if process.poll() is None:process.kill();process.wait()

if __name__=='__main__':main()
