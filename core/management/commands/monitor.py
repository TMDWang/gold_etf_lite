from django.core.management.base import BaseCommand
from apscheduler.schedulers.blocking import BlockingScheduler
from core.monitor import tick

class Command(BaseCommand):
    help='运行共享行情、持久化计划监测及通知任务'
    def handle(self,**options):
        from core.backup import scheduled_backup
        scheduler=BlockingScheduler(timezone='Asia/Shanghai',job_defaults={'coalesce':True,'max_instances':1,'misfire_grace_time':60})
        scheduler.add_job(tick,'interval',seconds=60,id='market-monitor')
        scheduler.add_job(scheduled_backup,'cron',hour=3,minute=10,id='daily-backup')
        tick()
        try:scheduler.start()
        except (KeyboardInterrupt,SystemExit):pass
