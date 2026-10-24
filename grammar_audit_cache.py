"""Optional audit reuse, proven against the reader's database snapshot.

An independent read-only observer detects commits even while the actual reader
is pinned to an older WAL snapshot. No handles survive the request. Raw API
calls still compute afresh unless they explicitly request reuse.
"""
from collections import OrderedDict
from contextvars import ContextVar
from pathlib import Path
import json
import sqlite3
import threading
import zlib

import long_tasks
import grammar_reference

CURRENT=ContextVar('grammar_audit_snapshot',default=None)
LOCK=threading.RLock()
LIMIT=32*1024**2
VALUES=OrderedDict()
size=0
FACTS=OrderedDict()
fact_size=0
FACT_LIMIT=16*1024**2


def signature(path):
    result=[]
    for file in (path,Path(str(path)+'-wal')):
        try:s=file.stat();result.append((s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns))
        except FileNotFoundError:result.append(None)
    return tuple(result)


class Snapshot:
    def __init__(self,db):
        self.db=db;self.observer=None
        name=next((r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main'),'')
        if not name:return
        self.path=Path(name).resolve()
        try:
            self.observer=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)
            self.epoch=self.observer.execute('PRAGMA data_version').fetchone()[0]
            self.signature=signature(self.path)
        except (sqlite3.Error,OSError):self.close()
    def stable(self):
        try:return self.observer is not None and not self.db.total_changes and self.observer.execute('PRAGMA data_version').fetchone()[0]==self.epoch and signature(self.path)==self.signature
        except (sqlite3.Error,OSError):return False
    def close(self):
        if self.observer is not None:self.observer.close();self.observer=None


def key(db,q):
    snapshot=CURRENT.get()
    if snapshot is None or snapshot.db is not db or not db.in_transaction or not snapshot.stable():return None
    try:version=db.execute('SELECT version FROM analysis_state WHERE id=1').fetchone()[0]
    except (sqlite3.Error,TypeError):return None
    # The first SELECT pins the reader. Also reject a commit between the first
    # observer check and that SELECT (external SQL need not increment version).
    if not snapshot.stable():return None
    return (grammar_reference.VERSION,str(snapshot.path),snapshot.signature,version,q.get('language','all'),q.get('source','all'),q.get('lower')=='true',q.get('tag',''))


def load(db,q):
    if q.get('reuse')!='1':return None
    k=key(db,q)
    if k is None:return None
    with LOCK:
        saved=VALUES.get(k)
        if saved is None:return None
        VALUES.move_to_end(k)
    long_tasks.checkpoint(None,'正在筛选已核对的标注结果…')
    return json.loads(saved)


def remember(db,q,value):
    global size
    k=key(db,q)
    if k is None:return
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(raw)>LIMIT:return
    long_tasks.checkpoint()
    if key(db,q)!=k:return
    with LOCK:
        previous=VALUES.pop(k,None)
        if previous is not None:size-=len(previous)
        while VALUES and (size+len(raw)>LIMIT or len(VALUES)>=4):
            _,old=VALUES.popitem(last=False);size-=len(old)
        VALUES[k]=raw;size+=len(raw)


def fact_key(db,q):
    k=key(db,q)
    return k[:6] if k else None


def load_facts(db,q):
    if q.get('reuse')!='1':return None
    k=fact_key(db,q)
    if k is None:return None
    with LOCK:
        raw=FACTS.get(k)
        if raw is None:return None
        FACTS.move_to_end(k)
    long_tasks.checkpoint(None,'正在按最新标签重新核对已读取的语料…')
    return json.loads(zlib.decompress(raw))


def remember_facts(db,q,value):
    k=fact_key(db,q)
    if k is None:return
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(raw)>32*1024**2:return
    raw=zlib.compress(raw,1)
    if len(raw)>FACT_LIMIT or fact_key(db,q)!=k:return
    put_facts(k,raw)


def put_facts(k,raw):
    global fact_size
    with LOCK:
        previous=FACTS.pop(k,None)
        if previous is not None:fact_size-=len(previous)
        while FACTS and (fact_size+len(raw)>FACT_LIMIT or len(FACTS)>=4):fact_size-=len(FACTS.popitem(last=False)[1])
        FACTS[k]=raw;fact_size+=len(raw)


def prepare_promotion(db):
    """Called with the writer lock held, before any business writes."""
    import journal
    paths=('/api/grammar-save','/api/grammar-delete','/api/grammar-register-batch','/api/grammar-ignore','/api/grammar-unignore')
    if journal.action.get() not in {journal.LABELS[p] for p in paths}:return None
    observer=Snapshot(db)
    try:
        if observer.observer is None:return None
        version=db.execute('SELECT version FROM analysis_state WHERE id=1').fetchone()[0]
        # This writer's own commit leaves data_version unchanged; an external
        # observer's increments are not commit counts (commits can coalesce).
        observer.writer_epoch=db.execute('PRAGMA data_version').fetchone()[0]
        observer.old_key=(grammar_reference.VERSION,str(observer.path),observer.signature,version)
        return observer
    except (sqlite3.Error,OSError,TypeError):observer.close();return None


def promote(db,observer,changes):
    """Only an audited tag-only commit may carry source facts into a new epoch.

    Our writer's data_version must remain unchanged by other connections.
    Its own commit cannot increment this counter. External SQL, a raced commit,
    dictionary/meaning/source edits and rollbacks never gain this shortcut.
    """
    try:
        changed=[(t,a,b) for (t,_),(a,b) in changes.items() if a!=b]
        if not changed:return
        for table,a,b in changed:
            if table=='grammar_tags':continue
            if table=='category_classes' and all(v is None or v.get('kind')=='grammar' for v in (a,b)):continue
            if table!='languages' or not a or not b:return
            def language(value):
                value={k:v for k,v in value.items() if k!='revision'};meta=json.loads(value['metadata'])
                for k in ('glossary','grammar_ignored_candidates'):meta.pop(k,None)
                value['metadata']=meta;return value
            if language(a)!=language(b):return
        if db.execute('PRAGMA data_version').fetchone()[0]!=observer.writer_epoch:return
        sig=signature(observer.path)
        version=db.execute('SELECT version FROM analysis_state WHERE id=1').fetchone()[0]
        if db.execute('PRAGMA data_version').fetchone()[0]!=observer.writer_epoch or signature(observer.path)!=sig:return
        with LOCK:eligible=[(k,raw) for k,raw in FACTS.items() if k[:4]==observer.old_key]
        for k,raw in eligible:put_facts((k[0],k[1],sig,version,*k[4:]),raw)
    except Exception:
        # Optional reuse must never report an already committed save as failed.
        return
