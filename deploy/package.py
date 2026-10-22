"""Create a clean source ZIP without local accounts, secrets, or dependency directories."""
import hashlib
import json
import zipfile
from pathlib import Path

root=Path(__file__).resolve().parent.parent
destination=root.parent/'deliverables'
destination.mkdir(exist_ok=True)
archive=destination/'金笺_518880_启动优化版_2026-10-22.zip'
ignored={'.venv','node_modules','__pycache__','staticfiles','data','backups','.pytest_cache','.git'}
files=[]
def collect(folder):
    for path in sorted(folder.iterdir()):
        if path.name in ignored:continue
        if path.is_dir():collect(path)
        elif (not path.name.startswith('.env') or path.name=='.env.example') and '.sqlite3' not in path.name and path.suffix not in {'.pyc','.log','.zip'}:
            files.append(path)
collect(root)
manifest={str(path.relative_to(root)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as stream:
    for path in files:stream.write(path,'gold-etf-lite/'+path.relative_to(root).as_posix())
    stream.writestr('gold-etf-lite/SOURCE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
with zipfile.ZipFile(archive) as stream:
    assert stream.testzip() is None
    names=stream.namelist()
    assert not any(set(name.split('/'))&ignored for name in names)
    assert not any((Path(name).name.startswith('.env') and Path(name).name!='.env.example') or '.sqlite3' in name for name in names)
    assert {'gold-etf-lite/compose.yaml','gold-etf-lite/Dockerfile','gold-etf-lite/requirements.lock','gold-etf-lite/frontend/pnpm-lock.yaml','gold-etf-lite/frontend/dist/index.html','gold-etf-lite/core/migrations/0001_initial.py','gold-etf-lite/README.md'}<=set(names)
checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
(destination/(archive.name+'.sha256')).write_text(checksum+'  '+archive.name+'\n',encoding='utf-8')
print(json.dumps({'file':str(archive),'files':len(names),'bytes':archive.stat().st_size,'sha256':checksum},ensure_ascii=False))
