from django.core.management.base import BaseCommand, CommandError
from core.backup import run_backup

class Command(BaseCommand):
    help='生成一致性 PostgreSQL 备份，校验后保留最近30份'
    def handle(self,**options):
        try:target=run_backup()
        except Exception as exc:raise CommandError('备份失败（'+type(exc).__name__+'），请检查 NAS 空间、权限和数据库连接')
        self.stdout.write('已保存并校验目录结构：'+target.name)
