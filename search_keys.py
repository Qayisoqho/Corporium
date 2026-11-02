"""Shared literal SQLite keys for disposable search projections."""
from collections import OrderedDict
import sqlite3
import corpus


class Values:
    def __init__(self, db):
        self.db = db
        self.cache = OrderedDict()
        self.bytes = 0
        self.fts = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='projection_search_fts'").fetchone())

    @staticmethod
    def initialize(db):
        db.executescript('''
          CREATE TABLE IF NOT EXISTS projection_search_values(id INTEGER PRIMARY KEY,
            value TEXT NOT NULL UNIQUE,folded TEXT NOT NULL,reversed_value TEXT NOT NULL,reversed_folded TEXT NOT NULL,nonblank INTEGER NOT NULL DEFAULT 1);
          CREATE INDEX IF NOT EXISTS projection_search_folded ON projection_search_values(folded);
          CREATE INDEX IF NOT EXISTS projection_search_reverse ON projection_search_values(reversed_value);
          CREATE INDEX IF NOT EXISTS projection_search_reverse_folded ON projection_search_values(reversed_folded);
        ''')
        if 'nonblank' not in {r[1] for r in db.execute('PRAGMA table_info(projection_search_values)')}:
            db.execute('ALTER TABLE projection_search_values ADD COLUMN nonblank INTEGER NOT NULL DEFAULT 1')
            for row in db.execute('SELECT id,value FROM projection_search_values').fetchall():
                db.execute('UPDATE projection_search_values SET nonblank=? WHERE id=?',(int(bool(row['value'].strip())),row['id']))
        existing = db.execute("SELECT 1 FROM sqlite_master WHERE name='projection_search_fts'").fetchone()
        try:
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS projection_search_fts USING fts5(value,folded,content='projection_search_values',content_rowid='id',tokenize='trigram case_sensitive 1',detail=none)")
            if not existing:
                db.execute("INSERT INTO projection_search_fts(projection_search_fts) VALUES('rebuild')")
        except sqlite3.OperationalError as exc:
            if 'no such module' not in str(exc) and 'tokenizer' not in str(exc):
                raise

    def intern(self, text):
        text = corpus.normalize(text, True)
        if text in self.cache:
            self.cache.move_to_end(text)
            return self.cache[text]
        row = self.db.execute('SELECT id FROM projection_search_values WHERE value=?', (text,)).fetchone()
        if row:
            vid = row[0]
        else:
            folded = text.casefold()
            vid = self.db.execute('INSERT INTO projection_search_values(value,folded,reversed_value,reversed_folded,nonblank) VALUES(?,?,?,?,?)',
                                  (text, folded, text[::-1], folded[::-1],int(bool(text.strip())))).lastrowid
            if self.fts:
                self.db.execute('INSERT INTO projection_search_fts(rowid,value,folded) VALUES(?,?,?)', (vid, text, folded))
        cost = 128 + 4 * len(text)
        if cost <= 1024**2:
            self.cache[text] = vid
            self.bytes += cost
            while len(self.cache) > 2048 or self.bytes > 8 * 1024**2:
                old, _ = self.cache.popitem(last=False)
                self.bytes -= 128 + 4 * len(old)
        return vid

    def release(self, ids):
        # Both projections can own a value; never delete another reader's keys.
        refs = [name for name in ('gloss_search_keys', 'material_search_keys', 'material_search_custom')
                if self.db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (name,)).fetchone()]
        for vid in ids:
            if any(self.db.execute('SELECT 1 FROM '+name+' WHERE value_id=? LIMIT 1', (vid,)).fetchone() for name in refs):
                continue
            row = self.db.execute('SELECT value,folded FROM projection_search_values WHERE id=?', (vid,)).fetchone()
            if row:
                if self.cache.pop(row['value'], None) is not None:
                    self.bytes -= 128 + 4 * len(row['value'])
                if self.fts:
                    self.db.execute("INSERT INTO projection_search_fts(projection_search_fts,rowid,value,folded) VALUES('delete',?,?,?)", (vid, row['value'], row['folded']))
                self.db.execute('DELETE FROM projection_search_values WHERE id=?', (vid,))

    def query(self, text, case=False, mode='contains'):
        key = 'value' if case else 'folded'
        needle = corpus.normalize(text, case)
        if mode == 'present':
            return 'SELECT id FROM projection_search_values WHERE nonblank=1', []
        if mode == 'exact':
            return 'SELECT id FROM projection_search_values WHERE '+key+'=?', [needle]
        if mode in ('prefix', 'suffix'):
            if mode == 'suffix':
                key = 'reversed_' + key
                needle = needle[::-1]
            chars = list(needle)
            while chars and ord(chars[-1]) == 0x10ffff:
                chars.pop()
            code = ord(chars[-1]) + 1 if chars else None
            if code == 0xd800:
                code = 0xe000
            upper = ''.join(chars[:-1]) + chr(code) if chars else None
            return 'SELECT id FROM projection_search_values WHERE '+key+'>=?'+(' AND '+key+'<?' if upper else ''), [needle, upper] if upper else [needle]
        sql = 'SELECT id FROM projection_search_values WHERE '
        args = []
        if len(needle) >= 3 and '\0' not in needle and self.fts:
            sql += 'id IN (SELECT rowid FROM projection_search_fts WHERE projection_search_fts MATCH ?) AND '
            args.append('"'+needle[:3].replace('"', '""')+'"')
        return sql+'instr('+key+',?)>0', args+[needle]
