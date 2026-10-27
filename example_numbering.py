"""Permanent language-local display numbers; references continue to use UUIDs.

Reservations outlive sentence deletion and undo, so another sentence cannot take
an old number. They are included in backups, but deliberately not in undo_steps.
"""
TABLES = ('example_number_counters', 'example_numbers')


def needed(db):
    return any(not db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (t,)).fetchone() for t in TABLES)


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS example_number_counters(
      id TEXT PRIMARY KEY,next_number INTEGER NOT NULL CHECK(next_number>0));
    CREATE TABLE IF NOT EXISTS example_numbers(
      ordering INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL,language_id TEXT NOT NULL,
      number INTEGER NOT NULL CHECK(number>0),UNIQUE(language_id,id),UNIQUE(language_id,number));''')
    reconcile(db)


def assign(db, lid, eid):
    old = db.execute('SELECT number FROM example_numbers WHERE language_id=? AND id=?', (lid, eid)).fetchone()
    if old: return old[0]
    # All normal writes already hold the server's write transaction; direct
    # imports/migrations also acquire it before reading the allocation counter.
    if not db.in_transaction: db.execute('BEGIN IMMEDIATE')
    old = db.execute('SELECT number FROM example_numbers WHERE language_id=? AND id=?', (lid, eid)).fetchone()
    if old: return old[0]
    db.execute('INSERT OR IGNORE INTO example_number_counters VALUES(?,1)', (lid,))
    number = db.execute('SELECT next_number FROM example_number_counters WHERE id=?', (lid,)).fetchone()[0]
    db.execute('INSERT INTO example_numbers(id,language_id,number) VALUES(?,?,?)', (eid, lid, number))
    db.execute('UPDATE example_number_counters SET next_number=next_number+1 WHERE id=?', (lid,))
    return number


def assign_missing(db):
    rows = db.execute('''SELECT d.id,d.language_id FROM dictionary_examples d
      LEFT JOIN example_numbers n ON n.id=d.id AND n.language_id=d.language_id
      WHERE n.id IS NULL ORDER BY d.rowid''').fetchall()
    for row in rows: assign(db, row['language_id'], row['id'])


def reconcile(db):
    # Old backups have no registry; current backups may have reserved numbers
    # beyond the last live sentence. Never lower their high-water marks.
    for row in db.execute('SELECT language_id,MAX(number)+1 next_number FROM example_numbers GROUP BY language_id').fetchall():
        advance(db, row['language_id'], row['next_number'])
    assign_missing(db)


def advance(db, lid, next_number):
    db.execute('''INSERT INTO example_number_counters VALUES(?,?) ON CONFLICT(id)
      DO UPDATE SET next_number=MAX(next_number,excluded.next_number)''', (lid, next_number))


def number(db, lid, eid):
    row = db.execute('SELECT number FROM example_numbers WHERE language_id=? AND id=?', (lid, eid)).fetchone()
    return row[0] if row else None


def export_next(db, lid):
    row = db.execute('SELECT next_number FROM example_number_counters WHERE id=?', (lid,)).fetchone()
    return row[0] if row else 1


def import_examples(bundle):
    rows = list(bundle.get('dictionary_examples', []))
    numbered = [r for r in rows if 'library_number' in r]
    if numbered and len(numbered) != len(rows): raise ValueError('独立例句编号资料不完整')
    seen = set()
    for row in numbered:
        n = row['library_number']
        if type(n) is not int or not 0 < n < 2147483647: raise ValueError('独立例句编号须为有效正整数')
        key = (row['language_id'], n)
        if key in seen: raise ValueError('同一语言的独立例句编号重复')
        seen.add(key)
    nxt = bundle.get('example_number_next')
    if nxt is not None and (type(nxt) is not int or not 0 < nxt <= 2147483647 or any(n >= nxt for _, n in seen)):
        raise ValueError('独立例句后续编号无效')
    return sorted(rows, key=lambda r: r['library_number']) if numbered else rows


def prepare_import(db, lid, number):
    current = export_next(db, lid)
    if number < current: raise ValueError('导入的独立例句编号与当前语言已有编号冲突')
    advance(db, lid, number)
