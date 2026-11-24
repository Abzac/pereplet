"""Double-click launcher for the local reader; no global services or startup entries."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('PEREPLET_PORT', '18765'))
URL = f'http://127.0.0.1:{PORT}'


def request(path, body=None, token=''):
    headers = {'X-Pereplet': '1', 'X-Pereplet-Token': token, 'Content-Type': 'application/json'}
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with urllib.request.urlopen(req, timeout=2) as response:
        return json.load(response)


def running():
    try:
        return request('/api/health').get('app') == 'pereplet'
    except (OSError, ValueError, urllib.error.URLError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    if args.stop:
        if running():
            token = request('/api/session')['token']
            request('/api/shutdown', {}, token)
        return
    if not running():
        python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if not python.exists():
            raise RuntimeError('Сначала установите зависимости: см. README.md')
        data = ROOT / 'data'
        data.mkdir(exist_ok=True)
        logfile = data / 'server.log'
        if logfile.exists() and logfile.stat().st_size > 8 * 1024 * 1024:
            logfile.replace(data / 'server.previous.log')
        with logfile.open('ab') as log:
            subprocess.Popen([str(python), '-u', str(ROOT / 'runner.py')], cwd=ROOT, stdout=log, stderr=log,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                             start_new_session=os.name != 'nt')
        for _ in range(60):
            if running(): break
            time.sleep(.25)
        else:
            raise RuntimeError(f'Не удалось запустить приложение. Журнал: {logfile}')
    if not args.no_browser:
        webbrowser.open(URL)
    print(URL)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if os.name == 'nt' and '--no-browser' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(exc), 'Переплёт', 0x10)
        else:
            raise
