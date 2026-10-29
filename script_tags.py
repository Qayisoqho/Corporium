"""Recover flattened legacy tag names only from unambiguous source notation."""
import json
import re
import undo_codec
from collections import defaultdict

MARKER='script-tag-source-recovery-v1'
SCRIPT=re.compile(r'[A-Za-z0-9_]+(?:#(?:sub|sup|super)\[[A-Za-z0-9]+\])+')

def needed(db):
    return not db.execute("SELECT 1 FROM sqlite_master WHERE name='editorial_migrations'").fetchone() or not db.execute('SELECT 1 FROM editorial_migrations WHERE id=?',(MARKER,)).fetchone()

def recover(db,force=False):
    if not force and not needed(db):return
    import grammar
    spellings=defaultdict(set)
    for sql in ('SELECT e.body,t.language_id FROM entries e JOIN texts t ON t.id=e.text_id',
                'SELECT body,language_id FROM dictionary_examples'):
        for r in db.execute(sql):
            body=json.loads(r['body']);lid=body.get('language_id') or r['language_id']
            for word in body.get('words',[]):
                for symbol in grammar.tokens(word.get('gloss',''),lid,{},lower=True,candidates=True):
                    if not SCRIPT.fullmatch(symbol):continue
                    flat=re.sub(r'#(?:sub|sup|super)\[([^]]*)\]',r'\1',symbol)
                    spellings[lid,flat.casefold()].add(symbol)
    rows=grammar.listing(db);occupied=grammar.index(rows);changed=set();renamed={}
    for r in rows:
        candidates=spellings[r['language_id'],r['symbol'].casefold()]
        if len(candidates)!=1 or '#' in r['symbol']:continue
        symbol=next(iter(candidates));other=occupied.get((r['language_id'],symbol.casefold()))
        if other and other['id']!=r['id']:continue
        aliases=list(dict.fromkeys([*r['aliases'],r['symbol']]))
        aliases=[a for a in aliases if a.casefold()!=symbol.casefold()]
        db.execute('UPDATE grammar_tags SET symbol=?,aliases=?,revision=revision+1 WHERE id=?',(symbol,json.dumps(aliases,ensure_ascii=False),r['id']))
        occupied[r['language_id'],symbol.casefold()]=r;changed.add(r['language_id'])
        renamed[r['id']]=(r['symbol'],symbol)
    # Undo must not reintroduce the very same flattened spelling.
    if renamed and db.execute("SELECT 1 FROM sqlite_master WHERE name='undo_steps'").fetchone():
        for step in db.execute('SELECT id,changes FROM undo_steps').fetchall():
            changes=undo_codec.decode(step['changes']);dirty=False
            for change in changes:
                for side in ('before','after'):
                    row=change[side]
                    if not row:continue
                    if change['table']=='grammar_tags' and row['id'] in renamed:
                        old,new=renamed[row['id']]
                        if row['symbol']==old:
                            row['symbol']=new
                            row['aliases']=json.dumps(list(dict.fromkeys([*json.loads(row['aliases']),old])),ensure_ascii=False)
                            dirty=True
                    elif change['table']=='languages' and row['id'] in changed:
                        meta=json.loads(row['metadata']);glossary=meta.get('glossary',{})
                        for tag in rows:
                            if tag['language_id']==row['id'] and tag['id'] in renamed:
                                old,new=renamed[tag['id']]
                                if old in glossary:glossary[new]=glossary[old];dirty=True
                        row['metadata']=json.dumps(meta,ensure_ascii=False)
            if dirty:db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(undo_codec.encode(changes),step['id']))
    for lid in changed:grammar.publish(db,lid)
    db.execute('CREATE TABLE IF NOT EXISTS editorial_migrations(id TEXT PRIMARY KEY)')
    db.execute('INSERT OR IGNORE INTO editorial_migrations VALUES(?)',(MARKER,))
