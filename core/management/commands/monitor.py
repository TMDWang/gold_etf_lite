from django.core.management.base import BaseCommand
from apscheduler.schedulers.blocking import BlockingScheduler
from core.monitor import tick

class Command(BaseCommand):
    help='运行共享行情、持久化计划监测及通知任务'
    def handle(self,**options):
        from core.backup import scheduled_backup
        from core.reports import scheduled_reports
        from core.diagnostics import run_diagnostics
        from django.utils import timezone
        from datetime import timedelta
        scheduler=BlockingScheduler(timezone='Asia/Shanghai',job_defaults={'coalesce':True,'max_instances':1,'misfire_grace_time':60})
        scheduler.add_job(tick,'interval',seconds=60,id='market-monitor')
        scheduler.add_job(scheduled_backup,'cron',hour=3,minute=10,id='daily-backup')
        scheduler.add_job(scheduled_reports,'cron',hour=15,minute=10,id='closing-reports')
        scheduler.add_job(scheduled_reports,'date',run_date=timezone.now()+timedelta(seconds=5),id='report-catchup')
        scheduler.add_job(run_diagnostics,'interval',seconds=300,id='system-diagnostics')
        tick()
        try:scheduler.start()
        except (KeyboardInterrupt,SystemExit):pass
