"""Generate local secrets without printing them or contacting external services."""
import re
import secrets
from pathlib import Path

root=Path(__file__).resolve().parent.parent
target=root/'.env'
if target.exists():raise SystemExit('.env 已存在，未覆盖。修改域名请直接编辑原文件，切勿更换已有加密密钥。')
domain=input('已配置隧道的域名（例如 gold.example.com，不含 https://）: ').strip().lower()
if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',domain) or '.' not in domain:raise SystemExit('请输入有效域名')
import base64
values={'SECRET_KEY':secrets.token_urlsafe(50),'ENCRYPTION_KEY':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),'POSTGRES_PASSWORD':secrets.token_urlsafe(32),'POSTGRES_DB':'goldetf','POSTGRES_USER':'goldetf','ALLOWED_HOSTS':domain+',localhost,127.0.0.1','CSRF_TRUSTED_ORIGINS':'https://'+domain,'PUBLIC_URL':'https://'+domain,'APP_PORT':'8088','BIND_IP':'0.0.0.0','DEBUG':'0'}
with target.open('x',encoding='utf-8',newline='\n') as stream:
    stream.write('\n'.join(f'{k}={v}' for k,v in values.items())+'\n')
try:target.chmod(0o600)
except OSError:pass
print('已在当前项目生成 .env。请独立妥善保存此文件，恢复 PushPlus 密钥时需要原 ENCRYPTION_KEY。')
