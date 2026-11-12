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


def entry_rows(user, params=None):
    from core.entry_queries import selected_entries
    rows, replacements, _ = selected_entries(user, params or {})
    for entry in reversed(rows):
        data = entry.payload
        effective = replacements.get(entry.pk, data)
        yield (entry.pk, {'TRADE': '成交', 'CASH': '资金变动', 'CORRECTION': '纠错'}[entry.kind],
               entry.corrects_id or '', data.get('side', ''), data.get('occurred_at', ''),
               data.get('quantity', ''), data.get('price', ''), data.get('fee', ''),
               data.get('amount', ''), entry.created_at.isoformat(), spreadsheet_text(entry.reason),
               effective.get('quantity', ''), effective.get('price', ''), effective.get('fee', ''),
               data.get('category', 'UNCLASSIFIED') if entry.kind == 'CASH' else '',
               effective.get('side', ''), effective.get('occurred_at', ''), '是' if entry.pk in replacements else '否')
