"""Read the existing compressed JSON format without retaining every frozen card.

Decode one hit/card at a time with the standard JSON decoder. This keeps legacy
payloads, Unicode, validation and dictionary ordering intact; no data migration.
"""
import base64
import codecs
import json
import zlib
from collections import OrderedDict

import long_tasks


def text_chunks(payload,size=65536):
    compressed=base64.b64decode(payload);decoder=codecs.getincrementaldecoder('utf-8')();inflate=zlib.decompressobj()
    for start in range(0,len(compressed),size):
        pending=compressed[start:start+size]
        while pending:
            raw=inflate.decompress(pending,size);pending=inflate.unconsumed_tail
            if raw:yield decoder.decode(raw)
    if not inflate.eof:raise zlib.error('incomplete analysis payload')
    tail=decoder.decode(inflate.flush(),final=True)
    if tail:yield tail


class Reader:
    def __init__(self,chunks):
        self.chunks=iter(chunks);self.buffer='';self.position=0;self.eof=False;self.decoder=json.JSONDecoder()
    def more(self):
        if self.eof:return False
        long_tasks.checkpoint(None,'正在读取分析结果…')
        try:chunk=next(self.chunks)
        except StopIteration:self.eof=True;return False
        self.buffer=self.buffer[self.position:]+chunk;self.position=0;return True
    def peek(self):
        while True:
            while self.position<len(self.buffer) and self.buffer[self.position] in ' \t\r\n':self.position+=1
            if self.position<len(self.buffer):return self.buffer[self.position]
            if not self.more():return ''
    def take(self,char):
        if self.peek()!=char:raise ValueError('分析结果 JSON 结构无效')
        self.position+=1
    def value(self,*,raw=False):
        self.peek()
        while True:
            try:value,end=self.decoder.raw_decode(self.buffer,self.position)
            except json.JSONDecodeError:
                if self.more():continue
                raise
            # A numeric token can straddle an input chunk. Do not accept a
            # valid prefix before seeing its delimiter or the end of input.
            if end==len(self.buffer) and not self.eof:
                if self.more():continue
            elif end<len(self.buffer) and self.buffer[end] not in ' \t\r\n,:]}':
                if self.more():continue
                raise ValueError('分析结果 JSON 值无效')
            source=self.buffer[self.position:end] if raw else None
            self.position=end;return (value,source) if raw else value
    def entries(self,kind):
        opening,closing=('{','}') if kind=='object' else ('[',']');self.take(opening)
        if self.peek()==closing:self.take(closing);return
        while True:
            key=self.value() if kind=='object' else None
            if kind=='object':
                if not isinstance(key,str):raise ValueError('分析结果 JSON 对象键无效')
                self.take(':')
            yield key
            if self.peek()==closing:self.take(closing);return
            self.take(',')


class SelectedRecords(dict):
    total=0
    def __bool__(self):return bool(self.total)


class HitPool:
    """Request-local sharing of repeated immutable-in-use hit dimensions."""
    def __init__(self):self.dimensions=OrderedDict();self.entries=OrderedDict();self.bytes=0
    def apply(self,hit):
        entry=hit.get('entry_id')
        if isinstance(entry,str) and len(entry)<1024:
            hit['entry_id']=self.entries.setdefault(entry,entry);self.entries.move_to_end(entry)
            if len(self.entries)>4096:self.entries.popitem(last=False)
        dims=hit.get('dimensions')
        if not isinstance(dims,dict):return hit
        # The native encoder is faster than visiting every dimension/member in
        # Python, and preserves distinctions such as 1, 1.0, true and "1".
        key=json.dumps(dims,ensure_ascii=False,separators=(',',':'));saved=self.dimensions.get(key)
        if saved is not None:self.dimensions.move_to_end(key);hit['dimensions']=saved[0];return hit
        size=2048+12*len(key)
        if size<=4*1024**2:
            while self.dimensions and (len(self.dimensions)>=4096 or self.bytes+size>4*1024**2):self.bytes-=self.dimensions.popitem(last=False)[1][1]
            self.dimensions[key]=(dims,size);self.bytes+=size
        return hit


def read(payload,*,record_ids=(),forms=None,normalize=None,only=None,record_sink=None,hit_sink=None):
    """Select cards, optionally using the preceding hit/label metadata.

    Nonselected cards are decoded and immediately released. The standard
    decoder still validates them, including data outside the current page.
    """
    reader=Reader(text_chunks(payload));result={};pool=HitPool()
    for key in reader.entries('object'):
        wanted=only is None or key in only
        if key=='records' and reader.peek()=='{':
            ids=set(record_ids(result) if callable(record_ids) else record_ids);records=SelectedRecords()
            for rid in reader.entries('object'):
                if record_sink is None:record=reader.value()
                else:
                    record,raw=reader.value(raw=True);record_sink(rid,raw)
                records.total+=1
                if wanted and rid in ids:records[rid]=record
                if forms is not None:forms[rid]=tuple(normalize(w['form']) for w in record['body']['words'])
            if wanted:result[key]=records
        elif key=='hits' and reader.peek()=='[':
            hits=[]
            for position,_ in enumerate(reader.entries('array')):
                hit=reader.value()
                if hit_sink is not None:hit_sink(position,hit)
                if wanted:hits.append(pool.apply(hit))
            if wanted:result[key]=hits
        else:
            value=reader.value()
            if wanted:result[key]=value
    if reader.peek():raise ValueError('分析结果 JSON 尾部内容无效')
    return result


def occurrence(payload,index):
    chosen=[]
    def take(position,hit):
        if position==index:chosen.append(hit)
    def ids(partial):return {chosen[0]['entry_id']} if chosen else ()
    result=read(payload,only={'records'},record_ids=ids,hit_sink=take)
    if not chosen:raise ValueError('请选择有效例证')
    records=result.get('records')
    if records and chosen[0]['entry_id'] not in records:
        records=read(payload,only={'records'},record_ids={chosen[0]['entry_id']})['records']
    return chosen[0],records


def items(payload,section):
    """Stream one top-level array/object section, retaining just one item."""
    reader=Reader(text_chunks(payload))
    for key in reader.entries('object'):
        if key in ('records','hits'):
            kind='object' if key=='records' else 'array'
            for identity in reader.entries(kind):
                value=reader.value()
                if key==section:yield identity,value
            if key==section:return
        else:reader.value()


def sections(payload):
    """Yield top-level fields; consume each hit/card iterator before advancing."""
    reader=Reader(text_chunks(payload))
    for key in reader.entries('object'):
        if key in ('hits','records'):
            def values(kind='array' if key=='hits' else 'object'):
                for identity in reader.entries(kind):yield identity,reader.value()
            yield key,values()
        else:yield key,reader.value()
    if reader.peek():raise ValueError('分析结果 JSON 尾部内容无效')
