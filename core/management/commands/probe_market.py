from django.core.management.base import BaseCommand
from django.utils import timezone
from core.market import fetch_eastmoney, fetch_sina, validate_quote, quote_fresh, is_trading, trading_calendar

class Command(BaseCommand):
    help='仅检测两个免费报价来源，不发送消息、不改账目'
    def handle(self,**options):
        now=timezone.now()
        self.stdout.write('交易时段：'+str(is_trading(now)))
        try:self.stdout.write('交易日历有效截至：'+str(trading_calendar().last_session.date()))
        except Exception as exc:self.stdout.write('交易日历不可用：'+type(exc).__name__)
        for name,fetch in [('eastmoney',fetch_eastmoney),('sina',fetch_sina)]:
            try:
                data=validate_quote(fetch(),now)
                self.stdout.write(f"{name}: OK price={data['price']} source_at={data['source_at'].isoformat()} fresh={quote_fresh(data,now)}")
            except Exception as exc:
                self.stdout.write(name+': FAILED '+type(exc).__name__+'（检查 NAS 外网或上游服务）')
