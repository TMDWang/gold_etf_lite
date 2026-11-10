import csv

from django.http import HttpResponse

from core.models import Entry


def csv_download(filename, header, rows):
    response = HttpResponse('\ufeff', content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


def spreadsheet_text(value):
    text = str(value or '')
    if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text


def entry_rows(user):
    for entry in Entry.objects.filter(user=user).order_by('id').iterator():
        data = entry.payload
        yield (entry.pk, {'TRADE': '成交', 'CASH': '资金变动', 'CORRECTION': '纠错'}[entry.kind],
               entry.corrects_id or '', data.get('side', ''), data.get('occurred_at', ''),
               data.get('quantity', ''), data.get('price', ''), data.get('fee', ''),
               data.get('amount', ''), entry.created_at.isoformat(), spreadsheet_text(entry.reason))
