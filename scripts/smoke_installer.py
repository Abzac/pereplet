"""Check a real installer, upgrade and uninstall in a disposable user directory."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,tempfile,time,os
ROOT=Path(__file__).resolve().parents[1]
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--installer',type=Path,default=ROOT/'dist/Pereplet-Setup-Windows-x64.exe');args=parser.parse_args()
    installer=args.installer.resolve();(ROOT/'build').mkdir(exist_ok=True)
    # Distinct directory; no personal installation or data is discovered or modified.
    root=Path(tempfile.mkdtemp(prefix='pereplet-install-test-',dir=ROOT/'build'))/'app'
    env=os.environ.copy();env.pop('PEREPLET_QA',None)
    flags=['/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS','/TASKS=',f'/DIR={root}']
    subprocess.run([str(installer),*flags],check=True,timeout=300,env=env)
    subprocess.run([sys.executable,str(ROOT/'scripts/smoke_windows.py'),'--root',str(root)],check=True,timeout=180,env=env)
    data=root/'data';sentinel=data/'preservation-check.txt';sentinel.write_text('User content survives upgrade and uninstall',encoding='utf8')
    before={str(p.relative_to(data)):digest(p) for p in data.rglob('*') if p.is_file()}
    subprocess.run([str(installer),*flags],check=True,timeout=300,env=env)
    assert all((data/name).exists() and digest(data/name)==value for name,value in before.items()),'Upgrade changed user data'
    subprocess.run([str(root/'unins000.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],check=True,timeout=300,env=env)
    # Inno's original uninstaller starts a temporary copy; allow it to finish.
    for _ in range(100):
        if not (root/'Pereplet.exe').exists():break
        time.sleep(.1)
    assert not (root/'Pereplet.exe').exists(),'Program was not uninstalled'
    assert all((data/name).exists() and digest(data/name)==value for name,value in before.items()),'Uninstall removed user data'
    print('Installer smoke passed: complete payload, first launch, upgrade, uninstall, user data preserved')
if __name__=='__main__':main()
