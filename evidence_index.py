"""Disposable, bounded evidence index. Source rows and owners remain authoritative.

Intern searchable leaf values, rather than indexing the same sentence once per
lexical link. Match each unique value once using the existing NFC/case rules;
sentence owners then share those matches, for short and long queries alike.
"""
from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import json
import threading
import unicodedata

import long_tasks


class EvidenceIndex:
    def __init__(self,limit=64*1024**2):
        self.limit=limit;self.bytes=0;self.serial=0
        self.records=OrderedDict();self.ids={};self.values={};self.field_sets={}

    def discard(self,key):
        record=self.records.pop(key,None)
        if record is None:return
        _,ids,fields,cost=record;self.bytes-=cost
        shared=self.field_sets[fields];shared[1]-=1
        if not shared[1]:
            self.bytes-=shared[2];del self.field_sets[fields]
        for vid in ids:
            value=self.values[vid];value[2]-=1
            if value[2]:continue
            original,folded,_,cost=value
            del self.ids[original];del self.values[vid];self.bytes-=cost

    def matching(self,needle,case):
        folded=needle.casefold()
        return {vid for vid,v in self.values.items() if needle in v[0]} if case else {vid for vid,v in self.values.items() if folded in v[1]}


class Query:
    def __init__(self,index,needle,case):
        self.index=index;self.needle=needle;self.folded=needle.casefold();self.case=case;self.seen=set()
        self.matches=index.matching(needle,case)

    def has_record(self,key):
        # Existence only. Source and live-gloss stamps still need validation.
        return key in self.index.records

    def lookup(self,key,source):
        self.seen.add(key)
        fingerprint=hashlib.sha256(source.encode('utf-8')).digest()
        record=self.index.records.get(key)
        if record and record[0]==fingerprint:
            self.index.records.move_to_end(key)
            return fingerprint,(bool(self.matches.intersection(record[1])),self.index.field_sets[record[2]][0])
        self.index.discard(key)
        return fingerprint,None

    def remember(self,key,fingerprint,values,fields):
        index=self.index
        values=tuple(dict.fromkeys(unicodedata.normalize('NFC',v) for v in values if v.strip()))
        # Conservatively charge Python containers, strings and source references.
        # Oversize records use the exact scan above without entering the cache.
        ids=[];new_cost=0;hit=False
        for value in values:
            vid=index.ids.get(value)
            if vid is None:
                folded=value.casefold();cost=512+4*(len(value)+len(folded))
                new_cost+=cost
                matches=self.needle in value if self.case else self.folded in folded
            else:cost=0;folded=None;matches=vid in self.matches
            hit=hit or matches;ids.append((value,vid,cost,folded,matches))
        field_key=tuple(sorted(fields.items()));shared=index.field_sets.get(field_key)
        field_cost=shared[2] if shared is not None else 256+sum(256+4*(len(k)+len(v)) for k,v in field_key)
        record_cost=384+16*len(ids)+4*sum(len(str(k)) for k in key)
        if new_cost+record_cost+field_cost>index.limit:return hit
        if shared is None:
            shared=[dict(fields),0,field_cost,field_key];index.field_sets[field_key]=shared;index.bytes+=field_cost
        field_key=shared[3]
        shared[1]+=1
        result=[]
        for original,vid,cost,folded,matches in ids:
            if vid is None:
                index.serial+=1;vid=index.serial
                index.ids[original]=vid;index.values[vid]=[original,folded,0,cost];index.bytes+=cost
                if matches:self.matches.add(vid)
            index.values[vid][2]+=1;result.append(vid)
        index.records[key]=(fingerprint,tuple(result),field_key,record_cost);index.bytes+=record_cost
        while index.records and index.bytes>index.limit:index.discard(next(iter(index.records)))
        return hit

    def finish(self):
        for key in list(self.index.records):
            if key not in self.seen:self.index.discard(key)


_lock=threading.RLock()
_indexes=OrderedDict()


@contextmanager
def query(db,lid,catalog,needle,case):
    # No persistent business tables, migrations or cache files. Reopened and
    # restored projects are checked against actual source contents on every read.
    path=next((r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main'),'')
    identity=path or ('connection',id(db))
    signature=hashlib.sha256(json.dumps(catalog,ensure_ascii=False,sort_keys=True).encode('utf-8')).digest()
    key=(identity,lid,signature)
    while not _lock.acquire(timeout=.05):long_tasks.checkpoint()
    try:
        index=_indexes.get(key)
        if index is None:
            # Names resolve IDs into searchable values. A catalog edit cannot
            # reuse documents rendered with older names, symbols or aliases.
            for old in list(_indexes):
                if old[:2]==key[:2]:del _indexes[old]
            index=EvidenceIndex();_indexes[key]=index
        _indexes.move_to_end(key)
        while len(_indexes)>2:_indexes.popitem(last=False)
        view=Query(index,needle,case)
        yield view
        view.finish()
    finally:_lock.release()
