"""Recoverable project-local PCM takes; association uses existing media tables.

Only explicit start opens input. Tokens are scoped to the captured project path.
Pending files are never deleted by undo, failed association, or a UI reload.
"""
import atexit
import ctypes
from contextlib import nullcontext
import io
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import threading
import time
import uuid

import audio_capture
import media_engine
import object_media
import timeline


def owner_alive(pid):
    if type(pid) is not int or pid<=0:return False
    if pid==os.getpid():return True
    if os.name!='nt':
        try:os.kill(pid,0);return True
        except ProcessLookupError:return False
        except PermissionError:return True
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x1000,0,pid)
    if not handle:return ctypes.get_last_error()!=87
    try:
        code=ctypes.c_uint32()
        return not kernel.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
    finally:kernel.CloseHandle(handle)


def recording_root(dbpath):
    base = Path(dbpath).resolve().parent
    project = base.parent if base.name == 'data' else base
    return project / 'media' / 'recordings'


def describe(db, lid, body):
    import languages
    languages.require(db, lid)
    kind, rid = body.get('kind'), body.get('record_id', '')
    if kind in ('lexeme', 'morpheme', 'independent'):
        row = object_media.owner(db, kind, rid)
        if row['language_id'] != lid:
            raise ValueError('请选择材料所属语言')
        target = body.get('target_id', '')
        if target and target not in {v['id'] for v in object_media.targets(row, kind)}:
            raise ValueError('对应词形已改变，请重新选择')
    elif kind == 'corpus':
        raise ValueError('文本句子不提供单独录音，请使用时间轴录音')
    elif kind == 'timeline':
        rid, target = '', ''
    else:
        raise ValueError('请选择录音要关联的词条、句子或新时间轴')
    speaker = body.get('speaker', '')
    if speaker and not db.execute('SELECT 1 FROM timeline_speakers WHERE id=?', (speaker,)).fetchone():
        raise ValueError('发言人已不存在，请重新选择')
    language_label=db.execute('SELECT name FROM languages WHERE id=?',(lid,)).fetchone()[0]
    return dict(language_id=lid, language_label=language_label, kind=kind, record_id=rid, target_id=target, speaker=speaker)


def target_context(db, kind, rid, lid):
    row=None
    if kind in ('lexeme','morpheme','independent'):
        row=object_media.owner(db,kind,rid);lid=row['language_id']
    return dict(context=describe(db,lid,dict(kind=kind,record_id=rid)),targets=object_media.targets(row,kind) if row else [])


def header(rate, bits, channels, size):
    align = channels * (bits // 8)
    return struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', 36 + size, b'WAVE', b'fmt ', 16,
                       1, channels, rate, rate * align, align, bits, b'data', size)


def repair(path, config):
    align = config['channels'] * (config['bits'] // 8)
    size = max(0, path.stat().st_size - 44)
    size -= size % align
    with path.open('r+b') as stream:
        stream.truncate(size + 44)
        stream.seek(0)
        stream.write(header(config['rate'], config['bits'], config['channels'], size))
        stream.flush()
        os.fsync(stream.fileno())
    return size


class Recorder:
    def __init__(self, capture=audio_capture.Input):
        self.capture = capture
        self.lock = threading.RLock()
        self.takes = {}
        self.active = None

    def _persist(self, take):
        if take['trial']:return
        data = {k: v for k, v in take.items() if not k.startswith('_')}
        folder = take['_folder']
        partial = folder / 'recording.json.partial'
        with partial.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        name='linked.json' if take['state']=='linked' else 'discarded.json' if take['state']=='discarded' else 'trial.json' if take['trial'] and take['state']=='ready' else 'recording.json'
        partial.replace(folder / name)
        for old in ('recording.json','linked.json','discarded.json','trial.json'):
            if old!=name:(folder/old).unlink(missing_ok=True)

    def _find(self, dbpath, token, *, manifest=None):
        if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{32}', token):
            raise ValueError('录音已不存在，请重新打开录音面板')
        project = str(Path(dbpath).resolve())
        take = self.takes.get(token)
        if take and take['_project'] == project:
            return take
        matches = [manifest] if manifest is not None else [p for p in recording_root(dbpath).glob('*/*/' + token + '/*.json') if p.name in ('recording.json','linked.json','discarded.json','trial.json')]
        if not matches:
            raise ValueError('录音已不存在，请重新打开录音面板')
        take = json.loads(matches[0].read_text(encoding='utf-8'))
        if take.get('token') != token:
            raise ValueError('录音记录无效')
        take.update(_folder=matches[0].parent, _project=project)
        path = self.file(take)
        # Only interrupted captures need header recovery; never rewrite linked originals.
        if take['state'] in ('starting', 'recording', 'stopping'):
            if owner_alive(take.get('process_id')):
                raise ValueError('录音正在另一个程序窗口进行，请在原窗口停止')
            take['bytes'] = repair(path, take['config'])
            take['state'] = 'ready'
            take['recovered'] = True
            self._persist(take)
        self.takes[token] = take
        return take

    @staticmethod
    def file(take):
        name=take.get('filename','take.wav')
        if not isinstance(name,str) or Path(name).name!=name or any(c in name for c in '/\\:') or not name.endswith('.wav'):
            raise ValueError('录音记录无效')
        path = take['_folder'] / name
        if not path.is_file():
            raise ValueError('录音文件已移动或不存在')
        return path

    def view(self, take):
        config = take['config']
        return {**{k: v for k, v in take.items() if not k.startswith('_')},
                'duration_ms': round(take['bytes'] * 1000 / (config['rate'] * config['channels'] * config['bits'] // 8))}

    def status(self, dbpath, token):
        with self.lock:
            return self.view(self._find(dbpath, token))

    def playback(self, dbpath, token):
        with self.lock:
            take=self._find(dbpath,token)
            if take['state'] not in ('ready','linked') or not take['bytes']:
                raise ValueError('请先完成一段有效录音')
            source=take['_memory'].getvalue() if '_memory' in take else self.file(take)
            return source,take['filename']

    def release(self, dbpath, token):
        with self.lock:
            take=self._find(dbpath,token)
            if not take['trial'] or take['state'] not in ('ready','discarded'):
                raise ValueError('只能清除已结束的试音')
            if '_memory' in take:take['_memory'].close()
            self.takes.pop(token,None)
            if self.active is take:self.active=None
            return {'ok':True}

    def pending(self, dbpath, lid):
        items = []
        # Enumeration can take time on a large project. Do not hold the capture
        # lock over the directory scan or re-scan every date for each known file.
        for manifest in sorted(recording_root(dbpath).glob('*/*/*/recording.json'), reverse=True):
            try:
                with self.lock:
                    take = self._find(dbpath, manifest.parent.name, manifest=manifest)
                    if take['context']['language_id'] == lid and take['state'] not in ('linked', 'discarded') and not take['trial']:
                        items.append(self.view(take))
            except (ValueError, OSError, KeyError, json.JSONDecodeError):
                continue
        return sorted(items, key=lambda t: t['created'], reverse=True)

    def start(self, dbpath, context, body):
        with self.lock:
            if len(self.takes)>=256:
                for key,old in list(self.takes.items()):
                    if old['state'] not in ('starting','recording','stopping'):
                        del self.takes[key]
                    if len(self.takes)<128:break
            if self.active and self.active['state'] in ('starting', 'recording', 'stopping'):
                raise ValueError('已有录音进行中，请先停止')
            for key,old in list(self.takes.items()):
                if old.get('trial') and '_memory' in old and old['_project']==str(Path(dbpath).resolve()):
                    old['_memory'].close();del self.takes[key]
                    if self.active is old:self.active=None
            for manifest in recording_root(dbpath).glob('*/*/*/recording.json'):
                try:
                    other=json.loads(manifest.read_text(encoding='utf-8'))
                    if other.get('state') in ('starting','recording','stopping') and owner_alive(other.get('process_id')):
                        raise ValueError('录音正在另一个程序窗口进行，请在原窗口停止')
                except (OSError,json.JSONDecodeError):pass
            config = {key: body.get(key, default) for key, default in [('device', 0), ('rate', 48000), ('bits', 24), ('channels', 1)]}
            if any(type(v) is not int for v in config.values()) or config['device'] < 0 or config['rate'] not in (44100, 48000, 96000) or config['bits'] not in (16, 24) or config['channels'] not in (1, 2):
                raise ValueError('录音规格无效')
            token = uuid.uuid4().hex
            date = datetime.now().strftime('%Y-%m-%d')
            safe=lambda value:re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(value)).strip(' .')[:20]
            lang = safe(context.get('language_label',context['language_id']))+'-'+hashlib.sha256(context['language_id'].encode()).hexdigest()[:8]
            trial=body.get('trial') is True
            folder = None if trial else recording_root(dbpath) / lang / date / token
            if folder:
                folder.mkdir(parents=True, exist_ok=False)
                if shutil.disk_usage(folder).free<64*1024**2:raise ValueError('磁盘剩余空间不足，请先腾出空间再录音')
            take = dict(token=token, state='starting', context=context, config=config, trial=trial,
                        process_id=os.getpid(),
                        filename=datetime.now().strftime('%H%M%S')+'-'+(safe(body.get('name','')) or 'recording')+'-'+token[:8]+'.wav',
                        created=datetime.now(timezone.utc).isoformat(), bytes=0, peak_db=-96, rms_db=-96,
                        clipped=False, buffer_warning=False, error='', recovered=False,
                        _folder=folder, _project=str(Path(dbpath).resolve()), _stop=threading.Event())
            initial=header(config['rate'], config['bits'], config['channels'], 0)
            if trial:take['_memory']=io.BytesIO(initial)
            else:(folder / take['filename']).write_bytes(initial)
            self._persist(take)
            thread = threading.Thread(target=self._record, args=(take,), name='corporium-recorder', daemon=True)
            take['_thread'] = thread
            self.takes[token] = self.active = take
            thread.start()
            return self.view(take)

    def _record(self, take):
        config = take['config']
        align = config['channels'] * (config['bits'] // 8)
        limit = (10 if take['trial'] else 3 * 3600) * config['rate'] * align
        if take['context']['kind'] in ('lexeme', 'morpheme', 'independent'):
            limit = min(limit, 3600 * config['rate'] * align)
        limit = min(limit, 0xffff0000)
        checkpoint = time.monotonic()
        try:
            import numpy as np
            with self.capture(config) as capture, (nullcontext(take['_memory']) if take['trial'] else self.file(take).open('r+b')) as stream:
                with self.lock:
                    take['state'] = 'recording'
                    self._persist(take)
                stream.seek(44)
                def write(chunk, warning=False):
                    nonlocal checkpoint
                    if not chunk:
                        return
                    if len(chunk) % align:
                        raise ValueError('录音数据不完整，已保留已录部分')
                    if take['bytes'] + len(chunk) > limit:
                        chunk = chunk[:max(0, (limit - take['bytes']) // align * align)]
                    stream.write(chunk)
                    if config['bits'] == 16:
                        samples = np.frombuffer(chunk, dtype='<i2').astype(np.float64) / 32768
                    else:
                        values = np.frombuffer(chunk, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
                        values = values[:, 0] | values[:, 1] << 8 | values[:, 2] << 16
                        samples = ((values ^ 0x800000) - 0x800000).astype(np.float64) / 8388608
                    peak = float(np.max(np.abs(samples))) if len(samples) else 0
                    rms = float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0
                    with self.lock:
                        take['bytes'] += len(chunk)
                        take['peak_db'] = round(20 * math.log10(max(peak, .000016)), 1)
                        take['rms_db'] = round(20 * math.log10(max(rms, .000016)), 1)
                        take['clipped'] |= peak >= .999
                        take['buffer_warning'] |= warning
                    if time.monotonic() - checkpoint >= 1:
                        stream.seek(0)
                        stream.write(header(config['rate'], config['bits'], config['channels'], take['bytes']))
                        stream.seek(0, 2)
                        stream.flush()
                        if not take['trial']:os.fsync(stream.fileno())
                        with self.lock:
                            self._persist(take)
                        if not take['trial'] and shutil.disk_usage(take['_folder']).free<16*1024**2:
                            take['error']='磁盘剩余空间不足，已停止并保留已录部分'
                            take['_stop'].set()
                        checkpoint = time.monotonic()
                while not take['_stop'].is_set() and take['bytes'] < limit:
                    chunk, warning = capture.read(take['_stop'])
                    write(chunk, warning)
                for chunk in capture.drain():
                    write(chunk)
                if take['bytes'] >= limit and not take['trial']:
                    take['error'] = '已达到单次录音上限，已保存；请另起一段继续'
        except Exception as error:
            take['error'] = str(error)
        finally:
            with self.lock:
                try:
                    if take['trial']:
                        memory=take['_memory'];size=max(0,len(memory.getbuffer())-44);size-=size%align
                        memory.truncate(size+44);memory.seek(0);memory.write(header(config['rate'],config['bits'],config['channels'],size));take['bytes']=size
                    else:take['bytes'] = repair(self.file(take), config)
                except OSError:
                    take['error'] = '无法完整写入录音，请检查磁盘空间；已写部分保留在项目中'
                take['state'] = 'ready'
                try:
                    self._persist(take)
                except OSError:
                    pass  # The last checkpoint remains recoverable.

    def stop(self, dbpath, token):
        with self.lock:
            take = self._find(dbpath, token)
            if take['state'] in ('starting', 'recording', 'stopping'):
                take['state'] = 'stopping'
                take['_stop'].set()
            thread = take.get('_thread')
        if thread:
            thread.join(3)
        return self.status(dbpath, token)

    def busy(self):
        with self.lock:
            return bool(self.active and self.active['state'] in ('starting', 'recording', 'stopping'))

    def shutdown(self):
        with self.lock:
            take = self.active
        if take:
            self.stop(take['_project'], take['token'])
        with self.lock:
            for take in self.takes.values():
                if '_memory' in take:take['_memory'].close()

    def attach(self, db, dbpath, lid, body):
        """Called within the app's audited transaction, with lock held by route."""
        take = self._find(dbpath, body.get('token'))
        if take['context']['language_id'] != lid:
            raise ValueError('请选择材料所属语言')
        if take['state'] not in ('ready', 'linked') or take['trial'] or not take['bytes']:
            raise ValueError('请先完成一段有效录音')
        context = describe(db, lid, {**take['context'], 'speaker': body.get('speaker', take['context']['speaker']), 'target_id': body.get('target_id', take['context']['target_id'])})
        # Retrying a successful response must never create a second attachment.
        old = db.execute("SELECT id FROM timeline_media WHERE language_id=? AND json_extract(metadata,'$.recording_token')=?", (lid,take['token'])).fetchone()
        if old:
            session=db.execute('SELECT id FROM timeline_sessions WHERE media_id=?',(old[0],)).fetchone()
            return dict(ok=True, asset_id=old[0], id=session[0] if session else '',session_id=session[0] if session else '')
        path = self.file(take)
        meta = media_engine.probe(path)
        meta.update(kind='audio', recording_token=take['token'], recorded_at=take['created'], recording_format=take['config'],
                    recording_quality={k: take[k] for k in ('clipped', 'buffer_warning', 'recovered', 'error')})
        name = str(body.get('name', '')).strip()[:160] or '现场录音 ' + take['created'][:19].replace('T', ' ')
        asset = dict(name=name + '.wav', path=os.path.relpath(path, Path(dbpath).resolve().parent), storage='copy', metadata=meta)
        if context['kind'] in ('lexeme', 'morpheme', 'independent'):
            current = object_media.listing(db, context['kind'], context['record_id'])['items']
            result = object_media.mutate(db, lid, dict(kind=context['kind'], record_id=context['record_id'],
                snapshot=[[r['id'], r['revision']] for r in current], body=dict(caption=name, target_id=context['target_id'], speakers=[context['speaker']] if context['speaker'] else [])), asset)
        else:
            result = timeline.mutate(db, lid, 'create', dict(name=name), asset)
            sid = result['id']
            track = db.execute('SELECT id FROM timeline_tracks WHERE session_id=? ORDER BY position LIMIT 1', (sid,)).fetchone()[0]
            if body.get('track_name'):db.execute('UPDATE timeline_tracks SET name=? WHERE id=?',(str(body['track_name'])[:80],track))
            if context['speaker']:
                db.execute('UPDATE timeline_tracks SET speaker_id=? WHERE id=?', (context['speaker'], track))
            result['session_id'] = sid
        return dict(ok=True, **{k: v for k, v in result.items() if k != 'ok'})


SERVICE = Recorder()
atexit.register(SERVICE.shutdown)
