"""Immutable creation dates travel inside entry bodies; missing means unknown."""
from datetime import datetime, timezone
import json

ORDERS = ('@added-asc', '@added-desc')

def parse(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('添加时间格式无效')
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError()
        return date.astimezone(timezone.utc).isoformat(timespec='microseconds')
    except (ValueError, OverflowError):
        raise ValueError('添加时间须包含有效日期和时区') from None

def stamp(data, old=None):
    # Never accept a client-supplied date while creating/editing a normal entry.
    data.pop('created_at', None)
    if old is None:
        data['created_at'] = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    elif old.get('created_at') is not None:
        data['created_at'] = parse(old['created_at'])
    return data

def imported(db, table, xid, source):
    assert table in ('lexemes', 'morphemes')
    row = db.execute('SELECT body FROM '+table+' WHERE id=?', (xid,)).fetchone()
    data = json.loads(row['body'])
    data.pop('created_at', None)
    value = parse(source.get('created_at'))
    if value is not None:
        data['created_at'] = value
    db.execute('UPDATE '+table+' SET body=? WHERE id=?', (json.dumps(data, ensure_ascii=False), xid))

def sort_rows(rows, order):
    if order not in ORDERS:
        raise ValueError('排序方式无效')
    # Unknown dates always follow dated entries, including descending order.
    known, unknown = [], []
    for row in rows:
        value = parse(row['body'].get('created_at'))
        (known if value else unknown).append((value, row))
    known.sort(key=lambda x: x[1]['id'])
    known.sort(key=lambda x: x[0], reverse=order == '@added-desc')
    unknown.sort(key=lambda x: x[1]['id'])
    return [r for _, r in known+unknown]

def sql_order(order, alias):
    if order not in ORDERS:
        raise ValueError('排序方式无效')
    date = "json_extract("+alias+".body,'$.created_at')"
    direction = 'ASC' if order == '@added-asc' else 'DESC'
    return f'{date} IS NULL ASC,{date} {direction},{alias}.id ASC'
