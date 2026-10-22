import os
import subprocess
from django.conf import settings
from django.utils import timezone
from core.models import SystemState

def run_backup():
    folder=settings.BACKUP_DIR
    folder.mkdir(parents=True,exist_ok=True)
    name='gold_'+timezone.now().strftime('%Y%m%d_%H%M%S_%f')+'.dump'
    target=folder/name;partial=folder/(name+'.partial')
    db=settings.DATABASES['default']
    env={**os.environ,'PGPASSWORD':str(db.get('PASSWORD','')),'PGCONNECT_TIMEOUT':'15'}
    cmd=['pg_dump','--host',str(db.get('HOST','db')),'--port',str(db.get('PORT','5432')),'--username',str(db.get('USER','goldetf')),'--dbname',str(db.get('NAME','goldetf')),'--format=custom','--no-owner','--file',str(partial)]
    try:
        subprocess.run(cmd,env=env,check=True,capture_output=True,timeout=900)
        subprocess.run(['pg_restore','--list',str(partial)],check=True,capture_output=True,timeout=60)
        if not partial.exists() or partial.stat().st_size==0:raise RuntimeError('备份文件为空')
        partial.replace(target)
        SystemState.objects.update_or_create(key='backup',defaults={'value':{'last_success':timezone.now().isoformat(),'file':target.name,'ok':True}})
        # Only validated successful artifacts participate in retention.
        for old in sorted(folder.glob('gold_*.dump'),key=lambda p:p.name,reverse=True)[30:]:old.unlink()
        return target
    except Exception:
        partial.unlink(missing_ok=True)
        old=SystemState.objects.filter(pk='backup').values_list('value',flat=True).first() or {}
        old.update({'ok':False,'last_failure':timezone.now().isoformat(),'message':'备份未成功，请在 NAS 检查空间、权限和数据库连接'})
        SystemState.objects.update_or_create(key='backup',defaults={'value':old})
        raise

def scheduled_backup():
    from core.monitor import monitor_lock
    from django.db import close_old_connections
    close_old_connections()
    try:
        with monitor_lock() as acquired:
            if acquired:run_backup()
    except Exception:
        import logging
        logging.getLogger(__name__).error('database backup failed; check NAS disk and PostgreSQL tools')
    finally:close_old_connections()
