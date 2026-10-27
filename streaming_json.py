"""Disk-backed JSON arrays and cursor-backed export sequences.

Wire format stays ordinary JSON. Arrays spill to a private SQLite file on read;
large exports are written incrementally instead of building a second JSON copy.
"""
import json
import sqlite3
import tempfile
import shutil
import weakref
from pathlib import Path


class Rows(list):
    def __init__(self, db, sql, args=(), transform=None):
        self.db, self.sql, self.args, self.transform = db, sql, args, transform
    def __iter__(self):
        for row in self.db.execute(self.sql, self.args):
            value = dict(row)
            yield self.transform(value) if self.transform else value
    def __len__(self):
        return self.db.execute('SELECT COUNT(*) FROM ('+self.sql+')', self.args).fetchone()[0]
    def __getitem__(self, index):
        if isinstance(index, slice):return list(self)[index]
        if index < 0:index += len(self)
        row=self.db.execute('SELECT * FROM ('+self.sql+') LIMIT 1 OFFSET ?', (*self.args,index)).fetchone()
        if row is None:raise IndexError(index)
        value=dict(row)
        return self.transform(value) if self.transform else value


class TableRows(Rows):
    """Same row objects, with an export path that encodes scalar SQL rows in C.

    SQLite's JSON real-number rendering can round doubles. Those rows use the
    original Python encoder, preserving backup values exactly.
    """
    def __init__(self,db,table):
        quote=lambda name:'"'+name.replace('"','""')+'"'
        name=quote(table)
        super().__init__(db,'SELECT rowid AS rowid,* FROM '+name)
        columns=['rowid',*[r['name'] for r in db.execute('PRAGMA table_info('+name+')')]]
        self.column_names=columns
        arguments=','.join('?, '+quote(c) for c in columns)
        special=' OR '.join("typeof("+quote(c)+") IN ('real','blob')" for c in columns)
        self.encoded_sql='SELECT CASE WHEN '+special+' THEN NULL ELSE json_object('+arguments+') END,rowid FROM '+name

    def encoded(self,encoder):
        for row in self.db.execute(self.encoded_sql,self.column_names):
            if row[0] is not None:yield row[0]
            else:
                original=self.db.execute(self.sql+' WHERE rowid=?',(row[1],)).fetchone()
                yield encoder.encode(dict(original))


class UnitMap:
    """Export-only, disk-backed unit scope; no changes to application tables."""
    def __init__(self,db,lid):
        self.db=db
        db.execute('DROP TABLE IF EXISTS temp.exchange_units')
        db.execute('CREATE TEMP TABLE exchange_units AS SELECT u.* FROM corpus_units u JOIN entries e ON e.id=u.entry_id JOIN texts t ON t.id=e.text_id WHERE t.language_id=?',(lid,))
        db.execute('CREATE UNIQUE INDEX exchange_units_id ON exchange_units(id)')
    def __contains__(self,key):return bool(self.db.execute('SELECT 1 FROM exchange_units WHERE id=?',(key,)).fetchone())
    def __setitem__(self,key,value):
        cols=list(value)
        self.db.execute('INSERT INTO exchange_units ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+') ON CONFLICT(id) DO UPDATE SET '+','.join(c+'=excluded.'+c for c in cols if c!='id'),[value[c] for c in cols])
    def values(self):
        import gloss_inheritance
        return Rows(self.db,'SELECT * FROM exchange_units ORDER BY rowid',transform=lambda r:gloss_inheritance.export_unit(self.db,r))


def write(value, stream, update=lambda *a:None):
    # Stream containers, but let the C encoder encode each ordinary row at
    # once. iterencode over every column/token dominated dense JSON backups.
    encoder=json.JSONEncoder(ensure_ascii=False)
    def has_cursor(v):
        if isinstance(v,(Rows,Array)):return True
        if isinstance(v,dict):return any(has_cursor(x) for x in v.values())
        if isinstance(v,(list,tuple)):return any(has_cursor(x) for x in v)
        return False
    def encode(v,row=False):
        if isinstance(v,TableRows):
            yield '['
            for i,encoded in enumerate(v.encoded(encoder)):
                if i:yield ', '
                yield encoded
            yield ']';return
        if row and isinstance(v,dict) and not has_cursor(v):
            yield encoder.encode(v);return
        if isinstance(v,dict):
            yield '{'
            for i,(key,item) in enumerate(v.items()):
                if not isinstance(key,(str,int,float,bool,type(None))):raise TypeError('JSON object keys must be strings or numbers')
                if i:yield ', '
                yield encoder.encode(key if isinstance(key,str) else encoder.encode(key));yield ': '
                yield from encode(item)
            yield '}'
        elif isinstance(v,(list,tuple)):
            yield '['
            flat_rows=isinstance(v,Rows) and v.transform is None
            for i,item in enumerate(v):
                if i:yield ', '
                if flat_rows:yield encoder.encode(item)
                else:yield from encode(item,row=True)
            yield ']'
        else:yield encoder.encode(v)
    chunks=[];size=0;written=0
    for chunk in encode(value):
        chunks.append(chunk);size+=len(chunk)
        if size>=65536:
            data=''.join(chunks).encode('utf8');stream.write(data);written+=len(data)
            chunks=[];size=0;update(None,f'正在生成文件 · 已写入 {written/1048576:.1f} MB')
    if chunks:stream.write(''.join(chunks).encode('utf8'))


class Array(list):
    def __init__(self,store,key,count):self.store,self.key,self.count=store,key,count
    def __len__(self):return self.count
    def __iter__(self):
        for row in self.store.db.execute('SELECT value FROM items WHERE owner=? ORDER BY position',(self.key,)):
            yield self.store.unpack(json.loads(row[0]))
    def __getitem__(self,index):
        if isinstance(index,slice):return [self[i] for i in range(*index.indices(self.count))]
        if index<0:index+=self.count
        if not 0<=index<self.count:raise IndexError(index)
        row=self.store.db.execute('SELECT value FROM items WHERE owner=? AND position=?',(self.key,index)).fetchone()
        return self.store.unpack(json.loads(row[0]))
    def __add__(self,other):return list(self)+list(other)
    def __radd__(self,other):return list(other)+list(self)
    def __eq__(self,other):return list(self)==other
    def __deepcopy__(self,memo):
        import copy
        return [copy.deepcopy(x,memo) for x in self]


class Document(dict):
    def __init__(self,value,store):super().__init__(value);self.store=store
    def close(self):self.store.close()


class Store:
    def __init__(self):
        self.directory=tempfile.mkdtemp(prefix='corporium-json-')
        self.db=sqlite3.connect(Path(self.directory)/'arrays.sqlite3',check_same_thread=False)
        self.cleanup=weakref.finalize(self, self.release, self.db, self.directory)
        self.db.execute('PRAGMA journal_mode=OFF');self.db.execute('PRAGMA cache_size=-4096')
        self.db.execute('CREATE TABLE items(owner INTEGER,position INTEGER,value TEXT,PRIMARY KEY(owner,position)) WITHOUT ROWID')
        self.serial=0
    def pack(self,v):
        if isinstance(v,Array):return ['a',v.key,v.count]
        if isinstance(v,dict):return ['o',[[k,self.pack(x)] for k,x in v.items()]]
        if isinstance(v,list):return ['l',[self.pack(x) for x in v]]
        return ['v',v]
    def unpack(self,v):
        if v[0]=='a':return Array(self,v[1],v[2])
        if v[0]=='o':return {k:self.unpack(x) for k,x in v[1]}
        if v[0]=='l':return [self.unpack(x) for x in v[1]]
        return v[1]
    def close(self):
        self.cleanup()
    @staticmethod
    def release(db,directory):
        db.close()
        shutil.rmtree(directory)


def read(stream,update=lambda *a:None):
    """Read a text stream; memory is bounded by one scalar/object, not an array."""
    store=Store();buffer='';pos=0;decoder=json.JSONDecoder();parsed=0;read_chars=0
    def more():
        nonlocal buffer,pos,read_chars
        buffer=buffer[pos:];pos=0;chunk=stream.read(65536);buffer+=chunk
        read_chars+=len(chunk)
        update(None,f'正在读取数据 · 已读取 {read_chars/1048576:.1f} M 字符')
        return bool(chunk)
    def peek():
        nonlocal pos
        while True:
            while pos<len(buffer) and buffer[pos].isspace():pos+=1
            if pos<len(buffer):return buffer[pos]
            if not more():return ''
    def take(ch):
        nonlocal pos
        if peek()!=ch:raise ValueError('JSON 格式不正确')
        pos+=1
    def value(depth=0):
        nonlocal pos,parsed,buffer
        if depth>100:raise ValueError('JSON 嵌套层次过深')
        ch=peek()
        if ch=='{':
            take('{');result={}
            if peek()=='}':take('}');return result
            while True:
                if peek()!='"':raise ValueError('JSON 字段名无效')
                key=value(depth+1);take(':');result[key]=value(depth+1)
                if peek()=='}':take('}');return result
                take(',')
        if ch=='[':
            take('[');store.serial+=1;key=store.serial;count=0
            if peek()==']':take(']');return Array(store,key,count)
            while True:
                item=value(depth+1)
                store.db.execute('INSERT INTO items VALUES(?,?,?)',(key,count,json.dumps(store.pack(item),ensure_ascii=False)))
                count+=1;parsed+=1
                if parsed%1000==0:update(None,f'正在读取数据 · {parsed} 条记录')
                if peek()==']':take(']');return Array(store,key,count)
                take(',')
        while True:
            try:
                result,end=decoder.raw_decode(buffer,pos)
                # A numeric token may continue in the next input chunk.
                if end==len(buffer) or isinstance(result,(int,float)) and not isinstance(result,bool) and end<len(buffer) and buffer[end] in '.eE':
                    start=pos
                    if more():continue
                    end-=start
                pos=end;return result
            except json.JSONDecodeError:
                if not more():raise ValueError('JSON 内容不完整或格式不正确')
    try:
        result=value()
        if peek():raise ValueError('JSON 末尾含多余内容')
        if not isinstance(result,dict):raise ValueError('数据包顶层须为对象')
        store.db.commit();return Document(result,store)
    except BaseException:store.close();raise
