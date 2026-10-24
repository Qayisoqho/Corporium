"""Local SFNT/WOFF font discovery without external dependencies."""
import hashlib
import re
import struct
import threading
import zlib
from pathlib import Path

ROOT=Path(__file__).resolve().parent/'font'
BUILTINS=('IPAPANNEW','Junicode','SimSun','KaiTi','Microsoft YaHei','serif','sans-serif')
_lock=threading.RLock()
_catalog=None
_files={}

def valid_font(value):
    return isinstance(value,str) and (value in BUILTINS or re.fullmatch(r'localfont-[0-9a-f]{24}',value) is not None)

def inspect_font(path):
    data=path.read_bytes()
    if len(data)>50_000_000: raise ValueError('字体超过 50 MB')
    tables={}
    if data[:4]==b'wOFF':
        count=struct.unpack_from('>H',data,12)[0]
        for i in range(count):
            tag,offset,size,original,_=struct.unpack_from('>4sIIII',data,44+20*i)
            if original>20_000_000: raise ValueError('字体表过大')
            block=data[offset:offset+size]
            if size<original:
                decoder=zlib.decompressobj();block=decoder.decompress(block,original+1)
                if len(block)!=original or not decoder.eof: raise ValueError('字体压缩表损坏')
            tables[tag]=block
    elif data[:4] in (b'\x00\x01\x00\x00',b'OTTO',b'true'):
        count=struct.unpack_from('>H',data,4)[0]
        for i in range(count):
            tag,_,offset,size=struct.unpack_from('>4sIII',data,12+16*i)
            tables[tag]=data[offset:offset+size]
    else: raise ValueError('不支持的字体格式（支持 TTF、OTF、WOFF）')
    name=tables[b'name'];_,count,start=struct.unpack_from('>HHH',name)
    names={}
    for i in range(count):
        platform,encoding,language,nid,length,offset=struct.unpack_from('>HHHHHH',name,6+12*i)
        if nid not in (1,2,16,17): continue
        try:
            value=name[start+offset:start+offset+length].decode('utf-16-be' if platform in (0,3) else 'mac_roman').strip('\x00 ')
        except UnicodeError: continue
        score=(platform==3)+(language==0x409)*2
        if value and (nid not in names or score>names[nid][0]): names[nid]=(score,value)
    family=(names.get(16) or names.get(1) or (0,path.stem))[1]
    style=(names.get(17) or names.get(2) or (0,'Regular'))[1]
    os2=tables.get(b'OS/2',b'');head=tables.get(b'head',b'')
    weight=struct.unpack_from('>H',os2,4)[0] if len(os2)>=6 else 400
    italic=bool(struct.unpack_from('>H',head,44)[0]&2) if len(head)>=46 else False
    italic=italic or 'italic' in style.lower() or 'oblique' in style.lower()
    weights=str(max(1,min(1000,weight)))
    fvar=tables.get(b'fvar')
    if fvar:
        offset,_,count,size=struct.unpack_from('>HHHH',fvar,4)
        for i in range(count):
            tag,low,default,high=struct.unpack_from('>4siii',fvar,offset+i*size)
            if tag==b'wght': weights=f'{max(1,int(low/65536))} {min(1000,int(high/65536))}'
    return family,style,weights,'italic' if italic else 'normal'

def scan(refresh=False):
    global _catalog,_files
    with _lock:
        if _catalog is not None and not refresh: return _catalog
        families={};files={};errors=[]
        for path in sorted(ROOT.rglob('*')):
            if not path.is_file() or path.suffix.lower() not in ('.ttf','.otf','.woff','.woff2','.ttc','.otc'): continue
            try:
                path.resolve().relative_to(ROOT.resolve())
                if path.stat().st_size>50_000_000: raise ValueError('字体超过 50 MB')
                family,style,weight,slant=inspect_font(path)
                fid='localfont-'+hashlib.sha256(family.encode()).hexdigest()[:24]
                file_id=hashlib.sha256(str(path.relative_to(ROOT)).encode()).hexdigest()
                files[file_id]=path
                group=families.setdefault(fid,dict(id=fid,name=family,faces=[]))
                group['faces'].append(dict(url='/api/font-file?id='+file_id,style=slant,weight=weight,label=style))
            except Exception as exc: errors.append(dict(file=str(path.relative_to(ROOT)),error=str(exc)))
        _files=files;_catalog=dict(families=sorted(families.values(),key=lambda x:x['name'].casefold()),file_count=len(files),errors=errors)
        return _catalog

def font_file(file_id):
    scan()
    with _lock:
        path=_files.get(file_id)
        if path is None: raise ValueError('字体不存在，请重新扫描')
        path.resolve().relative_to(ROOT.resolve())
        return path.read_bytes(),{'.ttf':'font/ttf','.otf':'font/otf','.woff':'font/woff'}[path.suffix.lower()]
