"""Non-secret code fingerprint for the running backend, independent of Git."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from django.conf import settings

def fingerprint_entries(entries):
    digest=sha256()
    for name,content in sorted(entries,key=lambda item:item[0]):
        encoded=name.encode('utf-8')
        digest.update(len(encoded).to_bytes(8,'big'));digest.update(encoded)
        digest.update(len(content).to_bytes(8,'big'));digest.update(content)
    return digest.hexdigest()[:10]

@lru_cache(maxsize=1)
def backend_version():
    root=Path(settings.BASE_DIR)
    files=[]
    for directory in ('config','core','deploy'):
        for path in (root/directory).rglob('*'):
            if path.is_file() and path.suffix in ('.py','.sh','.conf') and 'tests' not in path.parts and '__pycache__' not in path.parts:
                files.append(path)
    files.extend(root/name for name in ('requirements.lock','Dockerfile','compose.yaml') if (root/name).is_file())
    try:return fingerprint_entries([(p.relative_to(root).as_posix(),p.read_bytes()) for p in files]) if files else '不可用'
    except OSError:return '不可用'
