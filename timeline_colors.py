"""Persisted track display colours; NULL on a child means inherit its parent."""
import re

PALETTE=('#78bce8','#e4ad73','#8ac6a1','#b5a0de','#d88f9f','#cabd75','#7ac7c4','#aab8d9')


def clean(value):
    if value is None:return None
    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):
        raise ValueError('轨道颜色须为 # 加六位十六进制数字，例如 #78bce8')
    return value.lower()


def fallback(identity):
    # Matches TimelineTree.fallbackColor for legacy rows without a saved colour.
    hashed=2166136261
    for char in str(identity):hashed=((hashed^ord(char))*16777619)&0xffffffff
    return PALETTE[hashed%len(PALETTE)]


def next_color(db,session_id):
    saved=[r[0] for r in db.execute('SELECT color FROM timeline_tracks WHERE session_id=? AND parent_id IS NULL AND color IS NOT NULL',(session_id,))]
    return next((c for c in PALETTE if c not in saved),PALETTE[len(saved)%len(PALETTE)])


def initialize(db):
    missing='color' not in {r['name'] for r in db.execute('PRAGMA table_info(timeline_tracks)')}
    if missing:db.execute('ALTER TABLE timeline_tracks ADD COLUMN color TEXT')
    # Freeze the old sequential palette once; never derive saved colours from order.
    for row in db.execute('SELECT id,session_id FROM timeline_tracks WHERE parent_id IS NULL AND color IS NULL ORDER BY session_id,position,id').fetchall():
        db.execute('UPDATE timeline_tracks SET color=? WHERE id=?',(next_color(db,row['session_id']),row['id']))
