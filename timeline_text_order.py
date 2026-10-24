"""Opt-in, persistent sentence numbering from one timeline per text."""
import long_tasks

TABLES=('timeline_text_orders',)


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS timeline_text_orders(
        id TEXT PRIMARY KEY,session_id TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
        CREATE INDEX IF NOT EXISTS timeline_text_order_session ON timeline_text_orders(session_id);''')


def text(db,lid,tid):
    row=db.execute('SELECT id,title,language_id FROM texts WHERE id=?',(tid,)).fetchone()
    if not row or row['language_id']!=lid:raise ValueError('请选择当前语言的一篇文本；独立例句没有文本句序')
    return row


def state(db,lid,tid,sid):
    owner=text(db,lid,tid)
    row=db.execute('SELECT o.*,s.name session_name FROM timeline_text_orders o JOIN timeline_sessions s ON s.id=o.session_id WHERE o.id=?',(tid,)).fetchone()
    binding=dict(session_id=row['session_id'],revision=row['revision']) if row else None
    return dict(text_id=tid,title=owner['title'],binding=binding,enabled=bool(row and row['session_id']==sid),session_name=row['session_name'] if row else '')


def set_enabled(db,lid,sid,b):
    tid=b.get('text_id');current=state(db,lid,tid,sid)
    if not isinstance(b.get('enabled'),bool):raise ValueError('请指定是否按时间轴自动排序')
    if 'binding' not in b or b['binding']!=current['binding']:raise ValueError('文本的排序依据已变化，请重新选择文本后设置')
    if b['enabled']:
        if not current['enabled']:
            db.execute('INSERT INTO timeline_text_orders(id,session_id) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET session_id=excluded.session_id,revision=timeline_text_orders.revision+1',(tid,sid))
        changed=sync_text(db,tid,sid)
    else:
        if current['binding'] and not current['enabled']:raise ValueError('该文本正按另一条时间轴排序，请先切换排序依据')
        db.execute('DELETE FROM timeline_text_orders WHERE id=?',(tid,))
        changed=0
    return dict(**state(db,lid,tid,sid),renumbered=changed)


def sync_text(db,tid,sid):
    # One sentence has one number even if several intervals/tracks reference it.
    # Unaligned sentences follow aligned ones; equal starts retain the text order.
    long_tasks.checkpoint(None,'正在按时间轴更新文本句序…')
    rows=db.execute('''SELECT e.id,e.position,MIN(i.start_ms) start_ms FROM entries e
        LEFT JOIN timeline_intervals i ON i.entry_id=e.id AND i.session_id=?
          AND i.track_id IN (SELECT id FROM timeline_tracks WHERE session_id=? AND kind='sentence')
        WHERE e.text_id=? GROUP BY e.id
        ORDER BY MIN(i.start_ms) IS NULL,MIN(i.start_ms),e.position,e.id''',(sid,sid,tid)).fetchall()
    changed=0
    for position,row in long_tasks.steps(enumerate(rows,1)):
        if position==row['position']:continue
        db.execute('UPDATE entries SET position=? WHERE id=?',(position,row['id']))
        changed+=1
    return changed


def sync_session(db,sid):
    changed=0
    for row in long_tasks.steps(db.execute('SELECT id FROM timeline_text_orders WHERE session_id=? ORDER BY id',(sid,)).fetchall()):
        changed+=sync_text(db,row['id'],sid)
    return changed


def cleanup(db,changes):
    if any(t in ('texts','timeline_sessions') and before and not after for (t,_),(before,after) in changes.items()):
        db.execute('''DELETE FROM timeline_text_orders WHERE id NOT IN (SELECT id FROM texts)
            OR session_id NOT IN (SELECT id FROM timeline_sessions)''')


def validate(db):
    if db.execute('''SELECT 1 FROM timeline_text_orders o LEFT JOIN texts t ON t.id=o.id
        LEFT JOIN timeline_sessions s ON s.id=o.session_id
        WHERE t.id IS NULL OR s.id IS NULL OR t.language_id!=s.language_id LIMIT 1''').fetchone():
        raise ValueError('文本的自动排序依据无效或跨语言，操作未应用')
