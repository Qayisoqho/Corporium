"""Read installed Windows font names through DirectWrite; never copy font files.

The reversible, bounded ID preserves a missing family's name across computers.
CSS uses an alias with local(full-name) faces, keeping system and bundled fonts
separate even when they have the same family name.
"""
from contextlib import contextmanager
import re
import sys
import threading
import time

_lock=threading.RLock()
_cached=None
_checked=0


def clean_name(value):
    return (isinstance(value,str) and 0<len(value)<=256 and value==value.strip()
            and not value.startswith('@') and not any(ord(c)<32 or 127<=ord(c)<=159 or 0xD800<=ord(c)<=0xDFFF for c in value))


def font_id(name):
    if not clean_name(name):raise ValueError('Invalid system font family')
    return 'systemfont-'+name.encode('utf-8').hex()


def font_name(value):
    if not isinstance(value,str) or not re.fullmatch(r'systemfont-(?:[0-9a-f]{2}){1,1024}',value):return None
    try:name=bytes.fromhex(value[11:]).decode('utf-8')
    except (ValueError,UnicodeError):return None
    return name if clean_name(name) else None


def _enumerate():
    # ctypes is imported lazily so validation also works on other platforms.
    import ctypes as c
    from ctypes import wintypes as w
    from uuid import UUID
    P=c.c_void_p;U=c.c_uint32;H=c.c_int32;B=c.c_int32
    def call(obj,index,result,*types):
        table=c.cast(obj,c.POINTER(c.POINTER(P))).contents
        return c.WINFUNCTYPE(result,P,*types)(table[index])
    def check(hr):
        if hr<0:raise OSError('DirectWrite failed: 0x%08X'%(hr&0xffffffff))
    @contextmanager
    def owned():
        obj=P()
        try:yield obj
        finally:
            if obj:call(obj,2,U)(obj)  # IUnknown::Release
    def strings(obj):
        if not obj:return []
        values=[]
        for i in range(min(call(obj,3,U)(obj),256)):
            def read(length_slot,string_slot):
                length=U();check(call(obj,length_slot,H,U,c.POINTER(U))(obj,i,c.byref(length)))
                if length.value>1024:return ''
                buf=c.create_unicode_buffer(length.value+1)
                check(call(obj,string_slot,H,U,w.LPWSTR,U)(obj,i,buf,len(buf)))
                return buf.value
            locale=read(5,6);name=read(7,8)
            if clean_name(name):values.append((locale,name))
        # A stable English ID, with all other localized names searchable.
        values.sort(key=lambda pair:(pair[0]!='en-us',pair[0]!='en-US',pair[0],pair[1]))
        return list(dict.fromkeys(name for _,name in values))
    dll=c.WinDLL('dwrite.dll')
    create=dll.DWriteCreateFactory;create.argtypes=[U,P,c.POINTER(P)];create.restype=H
    guid=c.create_string_buffer(UUID('b859ee5a-d838-4b5b-a2e8-1adc7d93db48').bytes_le)
    families=[]
    with owned() as factory,owned() as collection:
        check(create(0,guid,c.byref(factory)))
        check(call(factory,3,H,c.POINTER(P),B)(factory,c.byref(collection),True))
        for i in range(call(collection,3,U)(collection)):
            with owned() as family,owned() as names:
                check(call(collection,4,H,U,c.POINTER(P))(collection,i,c.byref(family)))
                check(call(family,6,H,c.POINTER(P))(family,c.byref(names)))
                aliases=strings(names)
                if not aliases:continue
                faces=[];seen=set()
                for j in range(call(family,4,U)(family)):
                    with owned() as font:
                        check(call(family,5,H,U,c.POINTER(P))(family,j,c.byref(font)))
                        locals_=[]
                        for kind in (16,17):  # FULL_NAME, POSTSCRIPT_NAME
                            with owned() as info:
                                exists=B()
                                check(call(font,9,H,U,c.POINTER(P),c.POINTER(B))(font,kind,c.byref(info),c.byref(exists)))
                                if exists.value:locals_+=strings(info)
                        if not locals_:continue
                        weight=str(max(1,min(1000,call(font,4,U)(font))))
                        style={0:'normal',1:'oblique',2:'italic'}.get(call(font,6,U)(font),'normal')
                        stretch=call(font,5,U)(font)
                        local=list(dict.fromkeys(locals_));key=(tuple(local),weight,style,stretch)
                        if key in seen:continue
                        seen.add(key);faces.append(dict(local=local,weight=weight,style=style,stretch=stretch))
                if faces:families.append(dict(id=font_id(aliases[0]),name=aliases[0],aliases=aliases,faces=faces))
    return sorted(families,key=lambda item:item['name'].casefold())


def catalog(refresh=False):
    global _cached,_checked
    with _lock:
        if _cached is not None and not refresh and time.monotonic()-_checked<30:return _cached
        if sys.platform!='win32':result=dict(families=[],status='unsupported',error='')
        else:
            try:result=dict(families=_enumerate(),status='ready',error='')
            except (OSError,ValueError) as exc:
                result=dict(families=(_cached or {}).get('families',[]),status='error',error=str(exc))
        _checked=time.monotonic();_cached=result
        return result
