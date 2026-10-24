"""Lossless, versioned TEXT storage for undo payloads; legacy JSON stays readable."""
import base64
import hashlib
import json
import zlib

FORMAT='corporium-undo-zlib-v1'
THRESHOLD=4096


def checkpoint():
    import long_tasks
    long_tasks.checkpoint(None,'正在整理撤销记录…')


def chunks(changes):
    yield b'['
    for i,change in enumerate(changes):
        if i%64==0:checkpoint()
        if i:yield b', '
        yield json.dumps(change,ensure_ascii=False).encode('utf-8')
    yield b']'


def pack(parts):
    compressor=zlib.compressobj(1);digest=hashlib.sha256();size=0
    small=bytearray();compressed=bytearray()
    for part in parts:
        for start in range(0,len(part),65536):
            piece=part[start:start+65536];before=size;size+=len(piece);digest.update(piece)
            if size//65536!=before//65536:checkpoint()
            if size<=THRESHOLD:small.extend(piece)
            else:small=None
            compressed.extend(compressor.compress(piece))
    compressed.extend(compressor.flush())
    if small is not None:return small.decode('utf-8')
    return json.dumps(dict(format=FORMAT,length=size,sha256=digest.hexdigest(),
                           data=base64.b64encode(compressed).decode('ascii')),separators=(',',':'))


def encode(changes):return pack(chunks(changes))


def compress_legacy(value):
    """Preserve the exact original UTF-8 JSON bytes during migration."""
    raw=value.encode('utf-8') if isinstance(value,str) else bytes(value)
    # Compressed envelopes are already encoded and validated by the reader.
    if raw.lstrip().startswith(b'{'):
        decode(value)
        return raw.decode('utf-8')
    if not isinstance(json.loads(raw),list):raise ValueError('撤销记录内容无效')
    if len(raw)<=THRESHOLD:return raw.decode('utf-8')
    return pack((raw,))


def decode(value):
    try:
        payload=json.loads(value)
        if isinstance(payload,list):return payload
        if not isinstance(payload,dict) or payload.get('format')!=FORMAT:raise ValueError('未知的撤销记录格式')
        length=payload['length']
        if type(length) is not int or length<0:raise ValueError('撤销记录长度无效')
        compressed=base64.b64decode(payload['data'],validate=True)
        decoder=zlib.decompressobj();raw=bytearray();digest=hashlib.sha256()
        for start in range(0,len(compressed),65536):
            pending=compressed[start:start+65536]
            while pending:
                checkpoint();piece=decoder.decompress(pending,min(65536,length-len(raw)+1));pending=decoder.unconsumed_tail
                raw.extend(piece);digest.update(piece)
                if len(raw)>length:raise ValueError('撤销记录长度不符')
        if not decoder.eof or decoder.unused_data or len(raw)!=length or digest.hexdigest()!=payload['sha256']:raise ValueError('撤销记录校验失败')
        changes=json.loads(raw)
        if not isinstance(changes,list):raise ValueError('撤销记录内容无效')
        return changes
    except (KeyError,TypeError,zlib.error,UnicodeError) as exc:
        raise ValueError('撤销记录损坏，未应用此操作') from exc
