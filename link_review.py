"""Concrete edit warnings, independent of the retired editorial status flags."""
TABLES=('lexical_reviews',)

def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS lexical_reviews(id TEXT PRIMARY KEY,reason TEXT NOT NULL)')

def mark(db,where,args,reason):
    for r in db.execute('SELECT id FROM lexical_links WHERE '+where,args).fetchall():
        db.execute('INSERT INTO lexical_reviews VALUES(?,?) ON CONFLICT(id) DO UPDATE SET reason=excluded.reason',(r['id'],reason))
        db.execute('UPDATE lexical_links SET revision=revision+1 WHERE id=?',(r['id'],))

def reason(db,identity):
    row=db.execute('SELECT reason FROM lexical_reviews WHERE id=?',(identity,)).fetchone()
    return row[0] if row else ''

def copy(db,source,target):
    message=reason(db,source)
    if message:db.execute('INSERT OR REPLACE INTO lexical_reviews VALUES(?,?)',(target,message))
