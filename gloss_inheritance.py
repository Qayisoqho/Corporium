"""Live, sense-bound glosses. Source text is a baseline, never a synced default.

Only association/occurrence edits change bindings. Meaning edits change a small
normalized row, not sentence JSON, token indexes, segmentation or undo snapshots.
All readers resolve through this module in their own database snapshot.
"""
import copy
import hashlib
import json
import uuid
from itertools import islice
from collections import OrderedDict,defaultdict
from contextvars import ContextVar

TABLES=('gloss_meanings','gloss_bindings')
CURRENT=ContextVar('gloss_inheritance_session',default=None)
CHANGES=ContextVar('gloss_inheritance_changes',default=None)
MARKER='sense-gloss-inheritance-v1'
NUMBER_JOIN='digit-final-gloss-v1'


def encoded(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
def meaning_id(target,usage,sense):return hashlib.sha256(encoded([target,usage,sense]).encode()).hexdigest()
def source_hash(word):
    key=(word.get('form'),word.get('gloss'),encoded(word['morph_groups']) if 'morph_groups' in word else None,encoded(word['infix_confirmation']) if 'infix_confirmation' in word else None,encoded(word['gloss_frozen']) if 'gloss_frozen' in word else None)
    s=CURRENT.get();saved=s.fingerprints.get(key) if s else None
    if saved is not None:s.fingerprints.move_to_end(key);return saved[0]
    source={k:word.get(k) for k in ('form','gloss','morph_groups','infix_confirmation')}
    if 'gloss_frozen' in word:source['gloss_frozen']=word['gloss_frozen']
    result=hashlib.sha256(encoded(source).encode()).hexdigest()
    size=256+sum(4*len(v) for v in key if isinstance(v,str))
    if s and size<=4*1024**2:
        while s.fingerprints and (len(s.fingerprints)>=4096 or s.fingerprint_bytes+size>4*1024**2):
            _,(_,old)=s.fingerprints.popitem(last=False);s.fingerprint_bytes-=old
        s.fingerprints[key]=(result,size);s.fingerprint_bytes+=size
    return result


class Session:
    def __init__(self,db):
        self.db=db;self.changed=db.total_changes;self.owners=OrderedDict();self.bytes=0
        self.rendered=OrderedDict();self.render_bytes=0
        self.export_cache=OrderedDict();self.export_bytes=0
        self.export_analysis=None
        self.labels=OrderedDict();self.label_bytes=0
        self.fingerprints=OrderedDict();self.fingerprint_bytes=0
        self.stamps={}
        self.enabled=bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='gloss_bindings'").fetchone())
    def check(self):
        if self.changed!=self.db.total_changes:
            self.owners.clear();self.bytes=0;self.rendered.clear();self.render_bytes=0
            self.export_cache.clear();self.export_bytes=0
            self.labels.clear();self.label_bytes=0
            self.fingerprints.clear();self.fingerprint_bytes=0
            self.stamps.clear()
            self.changed=self.db.total_changes
    def put(self,key,rows):
        # Upper-bound retained scalar rows without serializing the entire batch.
        size=sum(1024+sum(4*len(v) for v in row.values() if isinstance(v,str)) for row in rows)
        if size>16*1024**2:return
        if key in self.owners:self.bytes-=self.owners.pop(key)[1];self.stamps.pop(key,None)
        while self.owners and (len(self.owners)>=512 or self.bytes+size>16*1024**2):
            evicted,(_,old)=self.owners.popitem(last=False);self.bytes-=old;self.stamps.pop(evicted,None)
        self.owners[key]=(rows,size);self.bytes+=size


def session(db):
    value=CURRENT.get()
    if value is None or value.db is not db:value=Session(db);CURRENT.set(value)
    value.check();return value


def owner_key(kind,rid,changed_only=False):return (kind,rid,True) if changed_only else (kind,rid)


def prefetch(db,kind,ids,*,changed_only=False):
    s=session(db)
    if not s.enabled:return
    ids=list(dict.fromkeys(rid for rid in ids if owner_key(kind,rid,changed_only) not in s.owners))
    for start in range(0,len(ids),200):
        batch=ids[start:start+200];found={rid:[] for rid in batch}
        words={}
        if kind=='corpus' and not changed_only:
            # Fetch contiguous entry slots once. A PK join for every binding
            # causes many random unit lookups when every word is linked.
            words={r['id']:r['position'] for r in db.execute("SELECT id,position FROM corpus_units WHERE active=1 AND kind='word' AND entry_id IN ("+','.join('?' for _ in batch)+')',batch)}
        marks=','.join('?' for _ in batch)
        if changed_only:
            query='''WITH changed AS (
                SELECT DISTINCT b.owner_kind,b.owner_id,b.word_id FROM gloss_bindings b
                JOIN gloss_meanings m ON m.id=b.meaning_id WHERE b.owner_kind=? AND b.owner_id IN ('''+marks+''')
                AND (b.source_binding_revision IS NULL OR b.source_binding_revision<>b.revision
                     OR (b.mode='inherit' AND (b.source_meaning_revision IS NULL OR b.source_meaning_revision<>m.revision))))
                SELECT b.*,m.gloss meaning_gloss,m.revision meaning_revision FROM changed c
                JOIN gloss_bindings b ON b.owner_kind=c.owner_kind AND b.owner_id=c.owner_id AND b.word_id=c.word_id
                JOIN gloss_meanings m ON m.id=b.meaning_id'''
        else:query='''SELECT b.*,m.gloss meaning_gloss,m.revision meaning_revision FROM gloss_bindings b
            JOIN gloss_meanings m ON m.id=b.meaning_id WHERE b.owner_kind=? AND b.owner_id IN ('''+marks+')'
        loaded=[dict(r) for r in db.execute(query,[kind,*batch])]
        if kind=='corpus' and changed_only:
            word_ids=list({r['word_id'] for r in loaded})
            for wi in range(0,len(word_ids),400):
                chosen=word_ids[wi:wi+400]
                words.update((r['id'],r['position']) for r in db.execute("SELECT id,position FROM corpus_units WHERE active=1 AND kind='word' AND id IN ("+','.join('?' for _ in chosen)+')',chosen))
        for r in loaded:
            row=dict(r);row['word_position']=words.get(r['word_id']);row['word_active']=int(r['word_id'] in words) if kind=='corpus' else None
            found[r['owner_id']].append(row)
        for rid,rows in found.items():
            rows.sort(key=lambda row:(row['unit_key'],row['id']));s.put(owner_key(kind,rid,changed_only),rows)


def bindings(db,kind,rid,*,changed_only=False):
    prefetch(db,kind,[rid],changed_only=changed_only);s=session(db);key=owner_key(kind,rid,changed_only)
    saved=s.owners.get(key)
    if saved:s.owners.move_to_end(key);return saved[0]
    if not s.enabled:return []
    # A single unusually large sentence is deliberately not cached.
    return [dict(r) for r in db.execute('''SELECT b.*,m.gloss meaning_gloss,m.revision meaning_revision,
        w.position word_position,w.active word_active FROM gloss_bindings b JOIN gloss_meanings m ON m.id=b.meaning_id
        LEFT JOIN corpus_units w ON b.owner_kind='corpus' AND w.id=b.word_id
        WHERE b.owner_kind=? AND b.owner_id=? ORDER BY b.id''',(kind,rid))]


def revision(db,kind,rid,rows=None):
    s=session(db);key=(kind,rid)
    saved=s.stamps.get(key)
    if saved is not None:return saved
    rows=bindings(db,kind,rid) if rows is None else rows
    if not rows:return None
    stamp=hashlib.sha256(encoded(sorted((r['id'],r['revision'],r['meaning_revision']) for r in rows)).encode()).hexdigest()
    if key in s.owners:s.stamps[key]=stamp
    return stamp


def revisions(db,kind,ids):
    """Batch the same content stamps without loading render data or word slots.

    The mapping is returned to the caller, not retained in the connection cache:
    a warm evidence scan must not grow a cache of every sentence's bindings.
    """
    ids=list(dict.fromkeys(ids));result=dict.fromkeys(ids)
    if not ids or not session(db).enabled:return result
    for start in range(0,len(ids),200):
        batch=ids[start:start+200]
        # Aggregate the same ordered triples in SQLite. Returning one compact
        # value per sentence avoids allocating a Python row/tuple per binding.
        for row in db.execute('''SELECT owner_id,json_group_array(json_array(id,revision,meaning_revision)) versions
            FROM (SELECT b.owner_id,b.id,b.revision,m.revision meaning_revision
            FROM gloss_bindings b JOIN gloss_meanings m ON m.id=b.meaning_id
            WHERE b.owner_kind=? AND b.owner_id IN ('''+','.join('?' for _ in batch)+''')
            ORDER BY b.owner_id,b.id,b.revision,m.revision) GROUP BY owner_id''',[kind,*batch]):
            result[row['owner_id']]=hashlib.sha256(row['versions'].encode()).hexdigest()
    return result


def pattern(value,label):
    from dictionary_gloss_sync import replace_short
    token='\ue000corporium-meaning\ue001'
    result=replace_short(value,label,token)
    pieces=result.split(token)
    out=[]
    for i,piece in enumerate(pieces):
        if i:out.append(None)
        if piece:out.append(piece)
    return encoded(out)


def value(binding):
    if binding['mode']=='override':return binding['override_text'] or ''
    return ''.join(binding['meaning_gloss'] if p is None else p for p in json.loads(binding['pattern']))


def at_word(body,row):
    if row['owner_kind']=='corpus':
        i=row.get('word_position')
        return i if row.get('word_active') and isinstance(i,int) and 0<=i<len(body['words']) else None
    return next((i for i,w in enumerate(body['words']) if w.get('annotation_id')==row['word_id']),None)


def render_word(word,rows):
    import corpus
    from dictionary_gloss_sync import transform
    current=corpus.analyze(dict(ipa='',translation='',words=[copy.deepcopy(word)]))['words'][0]
    whole=next((r for r in rows if r['unit_key']=='@word'),None)
    ordered=([whole] if whole else [])+[r for r in rows if r['unit_key']!='@word']
    for row in ordered:
        key=row['unit_key']
        # Pre-reduplication links refer to the old unsplit ~ span. Resolve their
        # gloss on that exact segmentation, never on the new reduplicant key.
        legacy='~' in current['form'] and key not in ('@word',) and not key.startswith(('r:','group:'))
        if legacy:
            current['_legacy_tilde']=True
            corpus.analyze(dict(ipa='',translation='',words=[current]))
        unit=current if key=='@word' else next((m for m in current['morphemes'] if m['key']==key),None)
        if unit is None:
            if legacy:
                current.pop('_legacy_tilde',None);corpus.analyze(dict(ipa='',translation='',words=[current]))
            continue
        label=value(row)
        # A whole-word provider may have changed the raw member spans while a
        # grouped semantic label still equals its own provider. Reapply the
        # group's value so the two physical pieces and the shared label agree.
        if unit['gloss']!=label or unit.get('group_id'):
            current=transform(current,{key:(unit['gloss'],label)})
        if legacy:
            current.pop('_legacy_tilde',None);corpus.analyze(dict(ipa='',translation='',words=[current]))
        if key=='@word' and row['mode']=='override':break
    if not whole or whole['mode']!='override':
        for frozen in word.get('gloss_frozen',[]):
            unit=_unit(current,frozen['key'])
            if unit and unit['form']==frozen['form']:current=transform(current,{frozen['key']:(unit['gloss'],frozen['gloss'])})
    return current


def resolve(db,kind,rid,body,*,metadata=True,lightweight=False,changed_only=False):
    """Resolve a mutable source copy. No persistent writes, no cached mutable body."""
    rows=bindings(db,kind,rid,changed_only=lightweight or changed_only)
    if not rows:return body
    grouped=defaultdict(list)
    stamp=None if lightweight or changed_only else revision(db,kind,rid,rows)
    for row in rows:
        i=at_word(body,row)
        already=body.get('gloss_revision')==stamp and '_gloss_active_bindings' in body
        valid=row['id'] in body['_gloss_active_bindings'] if already else i is not None and source_hash(body['words'][i])==row['source_hash']
        if i is not None and valid:grouped[i].append(row)
    s=session(db);versions=[]
    for i,items in grouped.items():
        word=body['words'][i]
        clean=all(r['source_binding_revision']==r['revision'] and (r['mode']=='override' or r['source_meaning_revision']==r['meaning_revision']) for r in items)
        if clean:
            if metadata:word['gloss_sources']=[dict(id=r['id'],key=r['unit_key'],mode=r['mode'],meaning=r['meaning_gloss'],revision=r['revision'],meaning_revision=r['meaning_revision']) for r in items]
            continue
        if lightweight:
            key=(source_hash(word),tuple((r['unit_key'],r['mode'],r['override_text'],r['pattern'],r['meaning_gloss']) for r in items))
            label=s.labels.get(key)
            if label is None:
                label=render_word(word,items)['gloss'];size=len(encoded(key).encode())+len(label.encode())
                if size<=4*1024**2:
                    while s.labels and (len(s.labels)>=4096 or s.label_bytes+size>4*1024**2):
                        old,(text,cost)=s.labels.popitem(last=False);s.label_bytes-=cost
                    s.labels[key]=(label,size);s.label_bytes+=size
            else:s.labels.move_to_end(key);label=label[0]
            if label!=word['gloss']:body['edited']=True
            word['gloss']=label
            continue
        # Derived annotations and presentation metadata are not part of the pure input.
        identity=('annotation_id','extra_layers','unit_id','linked_lexeme')
        derived={'gloss_sources','unit_type','boundary_count','gloss_relations','segments','group_reviews','infix_ambiguous','analysis_form','morphemes'}
        source={k:v for k,v in word.items() if k not in derived and k not in identity}
        key=encoded([source,[(r['unit_key'],r['mode'],r['override_text'],r['pattern'],r['meaning_gloss']) for r in items]])
        saved=s.rendered.get(key)
        if saved is None:
            rendered=render_word(source,items);saved=encoded(rendered)
            size=len(key.encode())+len(saved.encode())
            if size<=4*1024**2:
                while s.rendered and (len(s.rendered)>=256 or s.render_bytes+size>4*1024**2):
                    old,val=s.rendered.popitem(last=False);s.render_bytes-=len(old.encode())+len(val.encode())
                s.rendered[key]=saved;s.render_bytes+=size
        else:s.rendered.move_to_end(key)
        fresh=json.loads(saved)
        if fresh['gloss']!=word['gloss']:body['edited']=True
        # Consumers may already have attached layers/identity to this word.
        for k in identity:
            if k in word:fresh[k]=word[k]
        if metadata:fresh['gloss_sources']=[dict(id=r['id'],key=r['unit_key'],mode=r['mode'],meaning=r['meaning_gloss'],revision=r['revision'],meaning_revision=r['meaning_revision']) for r in items]
        body['words'][i]=fresh
        versions.extend((r['id'],r['revision'],r['meaning_revision']) for r in items)
    if metadata and not lightweight:
        body['gloss_revision']=stamp
        body['_gloss_active_bindings']=[r['id'] for items in grouped.values() for r in items]
    # Independent references compare structure/identity against the raw baseline,
    # then carry the effective label for consumers; label edits are not detachment.
    if kind=='independent' and not lightweight:
        import segmentation
        active={r['id'] for items in grouped.values() for r in items}
        for target in body.get('targets',[]):
            ref=target.get('segmentation_ref');bid=target.get('gloss_binding_id')
            row=next((r for r in rows if r['id']==bid and r['id'] in active),None)
            if not ref or not row or ref.get('detached'):continue
            i=at_word(body,row)
            if i is None:continue
            word=body['words'][i];unit=word if row['unit_key']=='@word' else next((m for m in word.get('morphemes',[]) if m['key']==row['unit_key']),None)
            if unit is not None:
                target['segmentation_ref']=segmentation.reference(word,i,dict(unit,key=row['unit_key'],fragments=[] if row['unit_key']=='@word' else unit.get('fragments',[])))
                target['gloss_mode']=row['mode']
    return body


def load(db,kind,rid,raw,**kwargs):
    body=json.loads(raw) if isinstance(raw,str) else raw
    if kind=='corpus':
        import grammaticality
        grammaticality.strip_corpus(body)
    return resolve(db,kind,rid,body,**kwargs)


def check_revision(db,kind,rid,request):
    token=request.get('gloss_revision',request.get('body',{}).get('gloss_revision'))
    if token is None:return  # Legacy callers carry no live dictionary snapshot.
    rows=bindings(db,kind,rid)
    current=revision(db,kind,rid,rows)
    if token!=current:raise ValueError('关联的词典释义或标注方式已变化，请重新打开例句后编辑；当前草稿尚未保存')


def export_body(db,kind,row):
    row=dict(row);row['body']=json.dumps(load(db,kind,row['id'],row['body'],metadata=False),ensure_ascii=False);return row


def export_word_map(db,eid):
    import corpus
    s=session(db);saved=s.export_cache.get(eid)
    # Export consumers only read this private map. Decoding the complete map
    # again for every unit/segment multiplied work by the words per sentence.
    if saved is not None:s.export_cache.move_to_end(eid);return saved[0]
    row=db.execute('SELECT body FROM entries WHERE id=?',(eid,)).fetchone()
    result={}
    if row:
        if s.export_analysis is None:s.export_analysis=corpus.WordAnalysisCache()
        body=corpus.analyze(load(db,'corpus',eid,row['body'],metadata=False),cache=s.export_analysis)
        units=[dict(r) for r in db.execute('SELECT * FROM corpus_units WHERE entry_id=? AND active=1',(eid,))]
        positions={u['id']:u['position'] for u in units if u['kind']=='word'}
        for u in units:
            i=u['position'] if u['kind']=='word' else positions.get(u['parent_id'],-1)
            if not 0<=i<len(body['words']):continue
            w=body['words'][i];m=w if u['kind']=='word' else w['morphemes'][u['position']] if 0<=u['position']<len(w['morphemes']) else None
            if m:result[u['id']]=dict(gloss=m['gloss'],segment={**m,'snapshot':{k:w[k] for k in ('form','gloss')}} if u['kind']!='word' else None)
    # Include Python object overhead, rather than counting serialized bytes only.
    size=1024+8*len(encoded(result).encode())
    if size<=4*1024**2:
        while s.export_cache and (len(s.export_cache)>=64 or s.export_bytes+size>4*1024**2):
            _,(_,old_size)=s.export_cache.popitem(last=False);s.export_bytes-=old_size
        s.export_cache[eid]=(result,size);s.export_bytes+=size
    return result


def export_unit(db,row):
    row=dict(row)
    if row['active']:
        live=export_word_map(db,row['entry_id']).get(row['id'])
        if live:row['gloss']=live['gloss']
    return row


def export_segment(db,row):
    row=dict(row);u=db.execute('SELECT entry_id,active FROM corpus_units WHERE id=?',(row['id'],)).fetchone()
    if u and u['active']:
        live=export_word_map(db,u['entry_id']).get(row['id'])
        if live and live['segment']:row['body']=json.dumps(live['segment'],ensure_ascii=False)
    return row


def export_overrides(db,lid):
    return [dict(r) for r in db.execute('''SELECT b.* FROM gloss_bindings b
        LEFT JOIN entries e ON b.owner_kind='corpus' AND e.id=b.owner_id
        LEFT JOIN texts t ON t.id=e.text_id
        LEFT JOIN dictionary_examples d ON b.owner_kind='independent' AND d.id=b.owner_id
        WHERE b.mode='override' AND COALESCE(t.language_id,d.language_id)=?''',(lid,))]


def import_overrides(db,bundle,entry_map,example_map,unit_map,independent_map,link_map):
    """Ordinary associations rebuild inheritance; explicit overrides travel too."""
    if not bundle.get('gloss_overrides'):return
    sync_meanings(db,CHANGES.get())
    owners=set()
    for old in bundle['gloss_overrides']:
        kind=old['owner_kind'];rid=(entry_map if kind=='corpus' else example_map).get(old['owner_id'])
        if rid:owners.add((kind,rid))
    for kind,rid in owners:reconcile_owner(db,kind,rid)
    for old in bundle['gloss_overrides']:
        if old['mode']!='override':continue
        kind=old['owner_kind'];rid=(entry_map if kind=='corpus' else example_map).get(old['owner_id'])
        wid=(unit_map if kind=='corpus' else independent_map).get(old['word_id'])
        if not rid or not wid:raise ValueError('本句覆盖标注缺少所属词格')
        row=db.execute('SELECT id FROM gloss_bindings WHERE owner_kind=? AND owner_id=? AND word_id=? AND unit_key=?',(kind,rid,wid,old['unit_key'])).fetchone()
        if not row:raise ValueError('本句覆盖标注缺少对应义项关联')
        db.execute("UPDATE gloss_bindings SET mode='override',override_text=?,pattern=?,revision=revision+1 WHERE id=?",(old['override_text'],old['pattern'],row['id']))


def copy_binding(db,old_id,new_id,kind,rid,word_id,key):
    old=db.execute('SELECT * FROM gloss_bindings WHERE id=?',(old_id,)).fetchone()
    if not old:return
    columns=[r['name'] for r in db.execute('PRAGMA table_info(gloss_bindings)')]
    # The copied sentence may still contain its stored, pre-override gloss.
    # Revision 1 on a new binding must not accidentally match a source stamp
    # from before the source's override was edited.
    new=dict(old,id=new_id,owner_kind=kind,owner_id=rid,word_id=word_id,unit_key=key,revision=1,
             source_binding_revision=None,source_meaning_revision=None)
    table='entries' if kind=='corpus' else 'dictionary_examples'
    body=json.loads(db.execute('SELECT body FROM '+table+' WHERE id=?',(rid,)).fetchone()[0])
    if kind=='corpus':i=db.execute('SELECT position FROM corpus_units WHERE id=?',(word_id,)).fetchone()[0]
    else:i=next(i for i,w in enumerate(body['words']) if w.get('annotation_id')==word_id)
    new['source_hash']=source_hash(body['words'][i])
    db.execute('INSERT INTO gloss_bindings ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',[new[c] for c in columns])


def iter_rows(db,rows,kind=None,*,lightweight=False):
    """Bounded read-ahead for searches/analysis; never one query per token."""
    iterator=iter(rows)
    while batch:=list(islice(iterator,100)):
        groups=defaultdict(list)
        for row in batch:groups[kind or row['kind']].append(row['id'])
        for source,ids in groups.items():prefetch(db,source,ids,changed_only=lightweight)
        yield from batch


def initialize(db):
    schema='''CREATE TABLE IF NOT EXISTS gloss_meanings(
        id TEXT PRIMARY KEY,target_id TEXT NOT NULL,usage_id TEXT NOT NULL,sense_id TEXT NOT NULL,
        gloss TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,UNIQUE(target_id,usage_id,sense_id));
        CREATE TABLE IF NOT EXISTS gloss_bindings(
        id TEXT PRIMARY KEY,owner_kind TEXT NOT NULL CHECK(owner_kind IN ('corpus','independent')),
        owner_id TEXT NOT NULL,word_id TEXT NOT NULL,unit_key TEXT NOT NULL,
        meaning_id TEXT NOT NULL REFERENCES gloss_meanings(id) DEFERRABLE INITIALLY DEFERRED,
        mode TEXT NOT NULL CHECK(mode IN ('inherit','override')),override_text TEXT,
        pattern TEXT NOT NULL,source_hash TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
        source_meaning_revision INTEGER,source_binding_revision INTEGER);
        CREATE INDEX IF NOT EXISTS gloss_binding_owner ON gloss_bindings(owner_kind,owner_id);
        CREATE INDEX IF NOT EXISTS gloss_binding_meaning ON gloss_bindings(meaning_id);
        CREATE INDEX IF NOT EXISTS gloss_binding_word ON gloss_bindings(owner_kind,owner_id,word_id);
        CREATE TABLE IF NOT EXISTS gloss_migrations(id TEXT PRIMARY KEY,body TEXT NOT NULL);'''
    # Do not implicitly commit an existing migration/write transaction.
    for statement in schema.split(';'):
        if statement.strip():db.execute(statement)
    columns={r['name'] for r in db.execute('PRAGMA table_info(gloss_bindings)')}
    for name in ('source_meaning_revision','source_binding_revision'):
        if name not in columns:db.execute('ALTER TABLE gloss_bindings ADD COLUMN '+name+' INTEGER')
    CURRENT.set(None)


def sync_meanings(db,changes=None):
    from dictionary_gloss_sync import meanings
    if changes is None:
        targets=[(table,dict(r)) for table in ('lexemes','morphemes') for r in db.execute('SELECT * FROM '+table)]
    else:targets=[(table,after) for (table,_),(before,after) in list(changes.items()) if table in ('lexemes','morphemes') and before!=after]
    deltas=[]
    for table,target in targets:
        if target is None:continue  # removed targets are checked after binding cleanup
        desired={meaning_id(target['id'],u,s):(u,s,label) for (u,s),label in meanings(target,table).items()}
        old={r['id']:dict(r) for r in db.execute('SELECT * FROM gloss_meanings WHERE target_id=?',(target['id'],))}
        for mid,(usage,sense,label) in desired.items():
            previous=old.pop(mid,None)
            if previous is None:db.execute('INSERT INTO gloss_meanings VALUES(?,?,?,?,?,1)',(mid,target['id'],usage,sense,label))
            elif previous['gloss']!=label:
                deltas.append((mid,previous['gloss'],label))
                db.execute('UPDATE gloss_meanings SET gloss=?,revision=revision+1 WHERE id=?',(label,mid))
        for mid in old:
            if db.execute('SELECT 1 FROM gloss_bindings WHERE meaning_id=? LIMIT 1',(mid,)).fetchone():raise ValueError('义项仍被例句标注直接引用，请先解除或调整关联再删除义项；重新编号不会自动转移关联。')
            db.execute('DELETE FROM gloss_meanings WHERE id=?',(mid,))
    return deltas


def _unit(word,key):
    return dict(word,key='@word',fragments=[]) if key=='@word' else next((m for m in word.get('morphemes',[]) if m['key']==key),None)


def association_rows(db,kind,rid,body,*,force=False):
    if kind=='corpus':
        return [dict(r) for r in db.execute('''SELECT l.id,w.id word_id,u.id unit_id,u.kind,u.position,
            w.position word_position,u.form,m.id meaning_id,m.gloss meaning_gloss
            FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id
            JOIN corpus_units w ON w.id=COALESCE(u.parent_id,u.id)
            JOIN gloss_meanings m ON m.target_id=l.lexeme_id AND m.usage_id=l.usage_id AND m.sense_id=l.sense_id
            JOIN entries e ON e.id=u.entry_id JOIN texts t ON t.id=e.text_id
            JOIN (SELECT id,language_id FROM lexemes UNION ALL SELECT id,language_id FROM morphemes) x ON x.id=l.lexeme_id
            WHERE u.entry_id=? AND u.active=1 AND w.active=1
            AND COALESCE(NULLIF(json_extract(e.body,'$.language_id'),''),t.language_id)=x.language_id''',(rid,))]
    import segmentation,corpus
    corpus.analyze(body);rows=[]
    for target in body.get('targets',[]):
        ref=target.get('segmentation_ref')
        if not ref or ref.get('detached') or (target.get('segmentation_review') and not force):continue
        i=ref.get('word',-1)
        if not isinstance(i,int) or not 0<=i<len(body['words']):continue
        word=body['words'][i];u=_unit(word,ref['key'])
        if not u or not word.get('annotation_id'):continue
        # A stale external reference must not be rebound merely by position.
        if ref.get('form')!=word['form'] or ref.get('unit_form')!=u['form']:continue
        mid=meaning_id(target['lexeme_id'],target.get('usage_id'),target.get('sense_id'))
        m=db.execute('SELECT gloss FROM gloss_meanings WHERE id=?',(mid,)).fetchone()
        if m is None:continue
        bid=target.setdefault('gloss_binding_id',str(uuid.uuid4()))
        existing=db.execute('SELECT owner_kind,owner_id FROM gloss_bindings WHERE id=?',(bid,)).fetchone()
        if existing and (existing['owner_kind'],existing['owner_id'])!=(kind,rid):bid=target['gloss_binding_id']=str(uuid.uuid4())
        rows.append(dict(id=bid,word_id=word['annotation_id'],word_position=i,key=ref['key'],form=u['form'],meaning_id=mid,meaning_gloss=m['gloss'],requested_mode=target.get('gloss_mode','inherit')))
    return rows


def clear_metadata(body):
    """A changed source must not retain a previous rendering's validity stamp."""
    body.pop('gloss_revision',None);body.pop('_gloss_active_bindings',None)
    for word in body['words']:word.pop('gloss_sources',None)
    return body


def _write_body(db,kind,rid,body,*,bump=True):
    import lexicon
    table='entries' if kind=='corpus' else 'dictionary_examples'
    clean=clear_metadata(copy.deepcopy(body))
    old=db.execute('SELECT body FROM '+table+' WHERE id=?',(rid,)).fetchone()
    if old is not None:
        original=json.loads(old['body'])
        derived={'unit_type','boundary_count','gloss_relations','segments','group_reviews','infix_ambiguous','analysis_form','morphemes','punctuation'}
        for i,word in enumerate(clean['words']):
            if i>=len(original['words']):break
            prior=original['words'][i]
            without=lambda value:{k:v for k,v in value.items() if k not in derived}
            if without(word)==without(prior) and bool(word.get('punctuation'))==bool(prior.get('punctuation')):clean['words'][i]=prior
    raw=json.dumps(clean,ensure_ascii=False)
    if old is None or old['body']==raw:return
    db.execute('UPDATE '+table+' SET body=?'+(',revision=revision+1' if bump else '')+' WHERE id=?',(raw,rid))
    if kind=='corpus':lexicon.sync_entry(db,rid,preserve_complex=True,analyzed_body=body,preserve_slots=True,stored_body=raw)
    refresh_source_hashes(db,kind,rid,clean)


def refresh_source_hashes(db,kind,rid,body):
    for row in bindings(db,kind,rid):
        i=at_word(body,row)
        if i is None:continue
        signature=source_hash(body['words'][i])
        if signature!=row['source_hash']:db.execute('UPDATE gloss_bindings SET source_hash=?,revision=revision+1 WHERE id=?',(signature,row['id']))


def previous_units(db,eid,units):
    """Identity matching compares live labels, not stale baseline index copies."""
    import corpus
    changes=CHANGES.get() or {}
    before=next((a for (table,_),(a,b) in changes.items() if table=='entries' and a and a['id']==eid),None)
    if before is None:return units
    body=corpus.analyze(load(db,'corpus',eid,before['body']))
    parents={r['id']:r['position'] for r in units if r['kind']=='word'}
    for row in units:
        i=row['position'] if row['kind']=='word' else parents.get(row['parent_id'],-1)
        if not 0<=i<len(body['words']):continue
        word=body['words'][i]
        unit=word if row['kind']=='word' else word['morphemes'][row['position']] if row['position']<len(word['morphemes']) else None
        if unit is not None and row['form']==unit['form']:row['gloss']=unit['gloss']
    return units


def reconcile_owner(db,kind,rid,before=None,*,force=False,already_changed=False):
    import corpus
    from dictionary_gloss_sync import transform
    table='entries' if kind=='corpus' else 'dictionary_examples'
    row=db.execute('SELECT body FROM '+table+' WHERE id=?',(rid,)).fetchone()
    previous=bindings(db,kind,rid)
    if row is None:
        db.execute('DELETE FROM gloss_bindings WHERE owner_kind=? AND owner_id=?',(kind,rid));return
    raw=json.loads(row['body']);body=corpus.analyze(copy.deepcopy(raw))
    old_effective=load(db,kind,rid,before or row['body']) if previous else None
    if kind=='independent' and before and old_effective:
        from text_replace import preserve_independent_refs
        changed=[]
        for i,word in enumerate(body['words']):
            if i>=len(old_effective['words']):break
            prior=old_effective['words'][i]
            if word.get('annotation_id')==prior.get('annotation_id') and word['form']==prior['form'] and [(m['key'],m['kind'],m['form']) for m in word['morphemes']]==[(m['key'],m['kind'],m['form']) for m in prior.get('morphemes',[])]:changed.append(i)
        preserve_independent_refs(old_effective,body,changed,set(),analyzed=True)
    expected=association_rows(db,kind,rid,body,force=force)
    if kind=='corpus':
        for item in expected:
            i=item['word_position'];u=_unit(body['words'][i],'@word') if item['kind']=='word' else body['words'][i]['morphemes'][item['position']] if 0<=item['position']<len(body['words'][i]['morphemes']) else None
            item['key']=u['key'] if u and u['form']==item['form'] and body['words'][i].get('unit_type')=='word' else None
        expected=[r for r in expected if r['key'] is not None]
    wanted={r['id']:r for r in expected};old={r['id']:r for r in previous}
    if not expected and not previous:return
    frozen=False
    for bid,prior in old.items():
        following=wanted.get(bid)
        if following and (following['meaning_id'],following['word_id'],following['key'])==(prior['meaning_id'],prior['word_id'],prior['unit_key']):continue
        i=at_word(body,prior)
        if i is not None and old_effective and i<len(old_effective['words']):
            current=body['words'][i];unit=_unit(current,prior['unit_key']);was=_unit(old_effective['words'][i],prior['unit_key'])
            typed=before and i<len(json.loads(before)['words']) and raw['words'][i]['gloss'] not in (json.loads(before)['words'][i]['gloss'],old_effective['words'][i]['gloss'])
            if unit and was and not typed:
                body['words'][i]=transform(current,{prior['unit_key']:(unit['gloss'],was['gloss'])});frozen=True
                if prior['unit_key']!='@word' and any(r['word_id']==prior['word_id'] and r['key']=='@word' for r in wanted.values()):
                    literals=body['words'][i].setdefault('gloss_frozen',[])
                    literals[:]=[v for v in literals if v['key']!=prior['unit_key']]
                    literals.append(dict(key=prior['unit_key'],form=was['form'],gloss=was['gloss']))
        db.execute('DELETE FROM gloss_bindings WHERE id=?',(bid,))
    for item in expected:
        prior=old.get(item['id']);i=item['word_position'];word=body['words'][i];u=_unit(word,item['key'])
        same=prior and (prior['meaning_id'],prior['word_id'],prior['unit_key'])==(item['meaning_id'],item['word_id'],item['key'])
        if same and not force:
            # Normal saves send effective values. Only a real annotation edit
            # establishes a local override; metadata saves preserve inheritance.
            if before and old_effective and i<len(old_effective['words']):
                old_raw=json.loads(before)['words'];old_unit=_unit(old_effective['words'][i],item['key'])
                if i<len(old_raw) and raw['words'][i]['gloss'] not in (old_raw[i]['gloss'],old_effective['words'][i]['gloss']) and old_unit and u['gloss']!=old_unit['gloss']:
                    db.execute("UPDATE gloss_bindings SET mode='override',override_text=?,revision=revision+1 WHERE id=?",(u['gloss'],item['id']))
            continue
        if u is None:continue
        if word.get('gloss_frozen'):
            word['gloss_frozen']=[v for v in word['gloss_frozen'] if v['key']!=item['key']]
            if not word['gloss_frozen']:word.pop('gloss_frozen')
        template_unit=_unit(old_effective['words'][i],item['key']) if old_effective and i<len(old_effective['words']) else u
        if template_unit is None:template_unit=u
        db.execute('''INSERT INTO gloss_bindings(id,owner_kind,owner_id,word_id,unit_key,meaning_id,mode,override_text,pattern,source_hash,revision)
            VALUES(?,?,?,?,?,?,'inherit',NULL,?,?,1)
            ON CONFLICT(id) DO UPDATE SET word_id=excluded.word_id,unit_key=excluded.unit_key,
            meaning_id=excluded.meaning_id,mode='inherit',override_text=NULL,pattern=excluded.pattern,
            source_hash=excluded.source_hash,revision=gloss_bindings.revision+1''',
            (item['id'],kind,rid,item['word_id'],item['key'],item['meaning_id'],pattern(template_unit['gloss'],item['meaning_gloss']),source_hash(raw['words'][i])))
        if not force and item.get('requested_mode')=='override':db.execute("UPDATE gloss_bindings SET mode='override',override_text=? WHERE id=?",(u['gloss'],item['id']))
    # Freeze on unlink, preserve independent target identities, and materialize
    # current values ONLY once during the explicitly authorized old-data migration.
    if force:body=resolve(db,kind,rid,body)
    if kind=='independent' or frozen or force or previous or expected:
        _write_body(db,kind,rid,body,bump=not already_changed)
        stored=db.execute('SELECT body FROM '+table+' WHERE id=?',(rid,)).fetchone()
        if stored:
            saved=json.loads(stored['body']);refresh_source_hashes(db,kind,rid,saved)
            capture_canonical(db,kind,rid,saved)


def capture_canonical(db,kind,rid,source):
    """Record cache versions only when an explicit source save is already done."""
    rows=bindings(db,kind,rid)
    if not rows:return
    effective=resolve(db,kind,rid,copy.deepcopy(source),metadata=False)
    ready=[]
    for row in rows:
        i=at_word(source,row)
        if i is None or source_hash(source['words'][i])!=source_hash(effective['words'][i]):continue
        if row['source_binding_revision']!=row['revision'] or row['source_meaning_revision']!=row['meaning_revision']:ready.append(row['id'])
    if ready:db.execute('''UPDATE gloss_bindings SET source_binding_revision=revision,
        source_meaning_revision=(SELECT revision FROM gloss_meanings WHERE id=gloss_bindings.meaning_id)
        WHERE id IN ('''+','.join('?' for _ in ready)+')',ready)


def synchronize(db,changes):
    owners={};changed_entries=set()
    for (table,_),(before,after) in list(changes.items()):
        if before==after:continue
        if table in ('entries','dictionary_examples'):
            row=after or before;kind='corpus' if table=='entries' else 'independent'
            owners[(kind,row['id'])]=before['body'] if before else None;changed_entries.add((kind,row['id']))
        elif table=='lexical_links':
            for row in (before,after):
                if row:
                    u=db.execute('SELECT entry_id FROM corpus_units WHERE id=?',(row['unit_id'],)).fetchone()
                    if u:owners.setdefault(('corpus',u['entry_id']),None)
    for (kind,rid),before in owners.items():reconcile_owner(db,kind,rid,before,already_changed=(kind,rid) in changed_entries)
    for (table,_),(before,after) in list(changes.items()):
        if table in ('lexemes','morphemes') and before and not after:
            exists=db.execute('SELECT 1 FROM lexemes WHERE id=? UNION ALL SELECT 1 FROM morphemes WHERE id=?',(before['id'],before['id'])).fetchone()
            if not exists:db.execute('DELETE FROM gloss_meanings WHERE target_id=?',(before['id'],))


def validate_meaning_changes(db,deltas):
    # Ordinary labels cannot alter existing morpheme boundaries. Empty labels or
    # boundary syntax need the full existing structural check, with no writeback.
    unsafe={mid for mid,old,new in deltas if not old.strip() or not new.strip() or any(c in old+new for c in '-=+<>')}
    owners=set()
    for mid in unsafe:owners.update((r['owner_kind'],r['owner_id']) for r in db.execute('SELECT DISTINCT owner_kind,owner_id FROM gloss_bindings WHERE meaning_id=?',(mid,)))
    for kind,rid in owners:
        table='entries' if kind=='corpus' else 'dictionary_examples';row=db.execute('SELECT body FROM '+table+' WHERE id=?',(rid,)).fetchone()
        if row:load(db,kind,rid,row['body'])


def set_mode(db,request,lid):
    import annotations
    kind=request.get('kind');rid=request.get('id');d=annotations.get(db,kind,rid)
    if d['owner_language']!=lid or d['revision']!=request.get('revision'):raise ValueError('例句已修改，请重新打开标注设置')
    row=next((r for r in bindings(db,kind,rid) if r['id']==request.get('binding_id')),None)
    if row is None or row['revision']!=request.get('binding_revision'):raise ValueError('标注来源已变化，请重新打开')
    mode=request.get('mode')
    if mode not in ('inherit','override'):raise ValueError('请选择跟随词典或本句单独标注')
    text=request.get('value','')
    if not isinstance(text,str):raise ValueError('本句标注必须是文本')
    if request.get('gloss_revision')!=d['body'].get('gloss_revision'):raise ValueError('词典释义已变化，请重新打开标注设置')
    db.execute('UPDATE gloss_bindings SET mode=?,override_text=?,revision=revision+1 WHERE id=?',(mode,text if mode=='override' else None,row['id']))
    # A source-mode edit has its own concurrency/undo identity, and still checks
    # the same boundary-preserving rendering as a dictionary meaning change.
    body=annotations.owner(db,kind,rid)[0]
    return dict(ok=True,gloss_revision=body.get('gloss_revision'))


def refresh_number_join(db):
    """Refresh computed labels once; preserve baselines, overrides and link IDs."""
    if db.execute('SELECT 1 FROM gloss_migrations WHERE id=?',(NUMBER_JOIN,)).fetchone():return
    from dictionary_gloss_sync import meanings
    count=0
    for table in ('lexemes','morphemes'):
        for row in db.execute('SELECT * FROM '+table).fetchall():
            target=dict(row)
            for (usage,sense),label in meanings(target,table).items():
                count+=db.execute('UPDATE gloss_meanings SET gloss=?,revision=revision+1 WHERE id=? AND gloss<>?',(label,meaning_id(target['id'],usage,sense),label)).rowcount
    if count:
        import analysis_workspace
        analysis_workspace.invalidate(db)
    db.execute('INSERT INTO gloss_migrations VALUES(?,?)',(NUMBER_JOIN,encoded(dict(meanings=count))))


def migrate(db):
    """One-time default inheritance, explicitly covering existing linked glosses."""
    saved=db.execute('SELECT body FROM gloss_migrations WHERE id=?',(MARKER,)).fetchone()
    if saved:
        refresh_number_join(db)
        return json.loads(saved['body'])
    sync_meanings(db);result=dict(corpus=0,independent=0,bindings=0)
    owners=[('corpus',r[0]) for r in db.execute('SELECT DISTINCT u.entry_id FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE u.active=1 AND l.sense_id IS NOT NULL')]
    owners += [('independent',r[0]) for r in db.execute("SELECT id FROM dictionary_examples WHERE json_array_length(json_extract(body,'$.targets'))>0")]
    import long_tasks
    for kind,rid in long_tasks.steps(owners):
        reconcile_owner(db,kind,rid,force=True);result[kind]+=1
    result['bindings']=db.execute('SELECT count(*) FROM gloss_bindings').fetchone()[0]
    db.execute('INSERT INTO gloss_migrations VALUES(?,?)',(MARKER,encoded(result)))
    refresh_number_join(db)
    return result


def after_legacy_undo(db,changes,preimages,redo):
    """Old journals predate bindings; reconcile their restored associations once."""
    if any(c['table'] in TABLES for c in changes):return
    restored={}
    for i,c in enumerate(changes):
        table=c['table'];row=c['before'] or c['after'];key='text_id' if table=='text_info' else 'id'
        if table not in ('lexemes','morphemes','lexical_links','entries','dictionary_examples'):continue
        current=db.execute('SELECT rowid,* FROM '+table+' WHERE '+key+'=?',(row[key],)).fetchone()
        restored[(table,i)]=(preimages.get((table,row[key])),dict(current) if current else None)
    sync_meanings(db,restored)
    synchronize(db,restored)
