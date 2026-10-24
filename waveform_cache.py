"""Rebuildable, bounded waveform pyramids and native-rate sample tiles.

Only this module's versioned waveform directory is evicted. Playback proxies,
source media, corpus data and undo history are never cache eviction candidates.
"""
import base64
from collections import OrderedDict
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import re
import shutil
import threading
import time
import uuid

MIB = 1024 ** 2
DEFAULTS = dict(memory_mb=128, disk_mb=2048)
VERSION = 3
BASE = 64
_managers = OrderedDict()
_guard = threading.RLock()
_prefetch_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='corporium-wave-prefetch')


def dependencies():
    import av
    import numpy as np
    return av, np


class Cache:
    def __init__(self, root):
        self.root = root
        self.lock = threading.RLock()
        self.decode_lock = threading.Lock()
        self.pins = {}
        self.reserved = 0
        self.memory = OrderedDict()
        self.memory_bytes = 0
        self.active = True
        self.units = {}
        self.pending = None
        self.prefetching = False
        self.generation = 0
        self.settings = dict(DEFAULTS)
        self.settings_revision = 0
        try:
            self.settings = validate(json.loads((root / 'settings.json').read_text('utf-8')))
            self.settings_revision = (root / 'settings.json').stat().st_mtime_ns // 1000
        except (OSError, ValueError, TypeError):
            pass
        # Index only our known layout; never follow a source media path.
        if root.exists():
            for directory in root.iterdir():
                if not re.fullmatch('[0-9a-f]{64}', directory.name) or directory.is_symlink():
                    continue
                overview = directory / 'overview'
                if (overview / 'manifest.json').is_file():
                    self.register(overview, 'overview')
                detail = directory / 'detail'
                if detail.is_dir():
                    for tile in detail.glob('*.npy'):
                        if not tile.is_symlink():
                            self.register(tile, 'detail')
        # Previous releases' fixed 10 ms envelopes share the waveform quota.
        if root.parent.exists():
            for legacy in root.parent.glob('*.npz'):
                if re.fullmatch('[0-9a-f]{64}\\.npz',legacy.name) and not legacy.is_symlink():
                    self.register(legacy, 'legacy')
        self.trim()

    @property
    def memory_limit(self):
        # The remaining quarter belongs to the browser's typed waveform arrays.
        return self.settings['memory_mb'] * MIB * 3 // 4

    @property
    def disk_limit(self):
        return self.settings['disk_mb'] * MIB

    def register(self, path, kind):
        files = list(path.glob('*')) if path.is_dir() else [path]
        size = sum(p.stat().st_size for p in files if p.is_file())
        stamp = (path / 'manifest.json').stat().st_mtime if path.is_dir() else path.stat().st_mtime
        self.units[str(path)] = dict(size=size, kind=kind, stamp=stamp, flushed=stamp)

    @contextmanager
    def pin(self, path):
        key = str(path)
        with self.lock:
            self.pins[key] = self.pins.get(key, 0) + 1
        try:
            yield
        finally:
            with self.lock:
                self.pins[key] -= 1
                if not self.pins[key]:
                    del self.pins[key]
                self.trim()

    def touch(self, path):
        key = str(path)
        if key not in self.units:
            return
        now = time.time()
        self.units[key]['stamp'] = now
        if now - self.units[key]['flushed'] > 20:
            try:
                path.touch() if path.is_file() else (path / 'manifest.json').touch()
                self.units[key]['flushed'] = now
            except OSError:
                pass

    def trim(self, reserve=0):
        """Caller holds lock after startup. Busy units survive until unpinned."""
        total = sum(item['size'] for item in self.units.values())
        if total + reserve + self.reserved <= self.disk_limit and self.memory_bytes <= self.memory_limit:
            return True
        candidates = sorted(self.units, key=lambda key: (
            {'detail':0,'legacy':1,'overview':2}[self.units[key]['kind']], self.units[key]['stamp']))
        for key in candidates:
            if total + reserve + self.reserved <= self.disk_limit:
                break
            if key in self.pins:
                continue
            path = Path(key)
            try:
                known_legacy = (self.units[key]['kind']=='legacy' and
                    path.parent.resolve()==self.root.parent.resolve() and
                    re.fullmatch('[0-9a-f]{64}\\.npz',path.name))
                if (not path.resolve().is_relative_to(self.root.resolve()) and not known_legacy) or path.is_symlink():
                    continue
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                continue
            total -= self.units.pop(key)['size']
            self.forget(key)
        while self.memory and self.memory_bytes > self.memory_limit:
            _, value = self.memory.popitem(last=False)
            self.memory_bytes -= value.nbytes
        return total + reserve + self.reserved <= self.disk_limit

    def forget(self, prefix):
        for key in list(self.memory):
            if key.startswith(prefix):
                self.memory_bytes -= self.memory.pop(key).nbytes

    def get(self, key):
        with self.lock:
            value = self.memory.get(key)
            if value is not None:
                self.memory.move_to_end(key)
            return value

    def put(self, key, value):
        with self.lock:
            if not self.active or value.nbytes > self.memory_limit:
                return value
            old = self.memory.pop(key, None)
            if old is not None:
                self.memory_bytes -= old.nbytes
            self.memory[key] = value
            self.memory_bytes += value.nbytes
            # Memory trimming must not perform disk IO on every cache hit.
            while self.memory and self.memory_bytes > self.memory_limit:
                _, old = self.memory.popitem(last=False)
                self.memory_bytes -= old.nbytes
        return value


def validate(body):
    if not isinstance(body,dict):
        raise ValueError('无效的波形缓存设置')
    result = {}
    for name, low, high in [('memory_mb', 16, 4096), ('disk_mb', 64, 65536)]:
        value = body.get(name, DEFAULTS[name])
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError('波形内存预算须为 16–4096 MB，磁盘上限须为 64–65536 MB 的整数')
        result[name] = value
    return result


def cache(dbpath):
    root = Path(dbpath).resolve().parent / 'media-cache' / 'wave-v3'
    with _guard:
        key = str(root)
        if key not in _managers:
            _managers[key] = Cache(root)
        for other_key, other in _managers.items():
            if other_key != key:
                with other.lock:
                    other.active = False
                    other.memory.clear()
                    other.memory_bytes = 0
                    other.pending = None
                    other.generation += 1
        _managers[key].active = True
        _managers.move_to_end(key)
        # Released projects retain no waveform sample arrays.
        while len(_managers) > 8:
            old_key, old = next(iter(_managers.items()))
            if old.pins or old.reserved:
                break
            del _managers[old_key]
        return _managers[key]


def settings(dbpath, body=None):
    manager = cache(dbpath)
    with manager.lock:
        if body is not None:
            value = validate(body)
            manager.root.mkdir(parents=True, exist_ok=True)
            temp = manager.root / ('.settings-' + uuid.uuid4().hex)
            try:
                temp.write_text(json.dumps(value), 'utf-8')
                temp.replace(manager.root / 'settings.json')
            finally:
                temp.unlink(missing_ok=True)
            manager.settings = value
            manager.settings_revision = max(manager.settings_revision+1,time.time_ns()//1000)
            manager.trim()
        return dict(**manager.settings, memory_bytes=manager.memory_bytes,
                    disk_bytes=sum(v['size'] for v in manager.units.values()),
                    browser_bytes=manager.settings['memory_mb'] * MIB // 4,
                    settings_revision=manager.settings_revision,version=VERSION)


def overview_path(dbpath, key):
    return cache(dbpath).root / key / 'overview'


def retire_legacy(dbpath,key):
    manager=cache(dbpath)
    path=manager.root.parent/(key+'.npz')
    with manager.lock:
        path.unlink(missing_ok=True)
        manager.units.pop(str(path),None)


class Writer:
    """A small mapping window keeps pyramid generation's resident memory bounded."""
    def __init__(self, path, shape):
        _, np = dependencies()
        self.path, self.shape = path, shape
        initial = np.lib.format.open_memmap(path, mode='w+', dtype='<i2', shape=shape)
        self.offset = initial.offset
        initial._mmap.close()
        self.window = None
        self.first = -1
        self.rows = max(64, 1024 * 1024 // (shape[1] * 4))

    def close(self):
        if self.window is not None:
            self.window.flush()
            self.window._mmap.close()
            self.window = None

    def write(self, start, values, merge=False):
        _, np = dependencies()
        end = start + len(values)
        while start < end:
            first = start // self.rows * self.rows
            if self.first != first or self.window is None:
                self.close()
                self.first = first
                self.window = np.memmap(self.path, dtype='<i2', mode='r+',
                    offset=self.offset + first * self.shape[1] * 4,
                    shape=(min(self.rows, self.shape[0] - first), self.shape[1], 2))
            count = min(end - start, self.first + len(self.window) - start)
            target = self.window[start - self.first:start - self.first + count]
            part = values[:count]
            if merge:
                target[:, :, 0] = np.minimum(target[:, :, 0], part[:, :, 0])
                target[:, :, 1] = np.maximum(target[:, :, 1], part[:, :, 1])
            else:
                target[:] = part
            start += count
            values = values[count:]


def mapped_slice(path, start, end):
    _, np = dependencies()
    array = np.load(path, mmap_mode='r', allow_pickle=False)
    try:
        return array[start:end].copy()
    finally:
        array._mmap.close()


def build(dbpath, key, source, meta, update):
    av, np = dependencies()
    manager = cache(dbpath)
    target = overview_path(dbpath, key)
    with manager.pin(target):
        if (target / 'manifest.json').is_file():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.parent / ('.building-' + uuid.uuid4().hex)
        temp.mkdir()
        reserved = 0
        try:
            with av.open(str(source)) as container:
                stream = next((s for s in container.streams if s.type == 'audio'), None)
                rate = stream.codec_context.sample_rate if stream else 0
                channels = len(stream.codec_context.layout.channels) if stream else 0
                if channels > 32 or (stream and not 0 < rate <= 768000):
                    raise ValueError('该媒体的声道数或采样率暂不支持生成波形，仍可播放和对齐')
                frames = max(1, math.ceil(meta['duration_ms'] * rate / 1000))
                base = BASE
                def estimate(block):
                    n = math.ceil(frames / block)
                    total = 0
                    while n:
                        total += n * channels * 4 + 256
                        if n == 1:
                            break
                        n = (n + 1) // 2
                    return total + 4096
                # Extremely long material still gets a complete coarse overview.
                while estimate(base) > manager.disk_limit * .75:
                    base *= 2
                estimate_bytes = estimate(base)
                with manager.lock:
                    if not manager.trim(estimate_bytes):
                        raise ValueError('波形缓存空间正在使用，请稍后重试或提高磁盘缓存上限')
                    reserved = estimate_bytes
                    manager.reserved += reserved
                bins = math.ceil(frames / base)
                writer = Writer(temp / '0.npy', (bins, channels, 2)) if channels else None
                last = -1
                origin = meta['start_us'] / av.time_base
                next_sample = 0
                try:
                    if stream:
                        resampler = av.AudioResampler(format='fltp', rate=rate, layout=stream.codec_context.layout)
                        def peaks(samples,start):
                            nonlocal last
                            a, z = max(0, start), min(frames, start+samples.shape[1])
                            if z <= a:
                                return
                            samples = np.nan_to_num(samples[:, a-start:z-start], copy=True)
                            cuts = np.r_[0, np.arange(base - a % base, z-a, base)]
                            low = np.minimum.reduceat(samples, cuts, axis=1)
                            high = np.maximum.reduceat(samples, cuts, axis=1)
                            values = np.rint(np.clip(np.stack([low, high], axis=2), -1, 1) * 32767).astype('<i2').transpose(1, 0, 2)
                            first = a // base
                            overlap = min(len(values), max(0, last - first + 1))
                            if overlap:
                                writer.write(first, values[:overlap], merge=True)
                            if overlap < len(values):
                                writer.write(first + overlap, values[overlap:])
                            last = max(last, first + len(values) - 1)
                            update(min(92, z / frames * 92), '生成原采样率分声道波形')
                        # Amortize small AAC/MP3 frames without joining discontinuities.
                        # The batch is bounded by about 1 MiB, independent of duration.
                        parts=[]
                        batch_start=batch_count=0
                        batch_limit=min(32768,max(1024,MIB//(channels*4)))
                        def flush():
                            nonlocal batch_count
                            if parts:
                                peaks(np.concatenate(parts,axis=1),batch_start)
                                parts.clear()
                                batch_count=0
                        def consume(frame):
                            nonlocal batch_start,batch_count,next_sample
                            samples=frame.to_ndarray()
                            position=round((frame.time-origin)*rate) if frame.time is not None else next_sample
                            if parts and position!=batch_start+batch_count:
                                flush()
                            if not parts:
                                batch_start=position
                            parts.append(samples)
                            batch_count+=samples.shape[1]
                            next_sample=position+samples.shape[1]
                            if batch_count>=batch_limit:
                                flush()
                        for frame in container.decode(stream):
                            for converted in resampler.resample(frame):
                                consume(converted)
                        for converted in resampler.resample(None):
                            consume(converted)
                        flush()
                finally:
                    if writer:
                        writer.close()
            levels = []
            n = bins
            if channels:
                levels.append(n)
                while n > 1:
                    level = len(levels)
                    parent = Writer(temp / f'{level}.npy', ((n+1)//2, channels, 2))
                    try:
                        for start in range(0, n, 32768):
                            child = mapped_slice(temp / f'{level-1}.npy', start, min(n, start+32768))
                            if len(child) % 2:
                                child = np.concatenate([child, child[-1:]])
                            pairs = child.reshape(-1, 2, channels, 2)
                            values = np.stack([pairs[:, :, :, 0].min(axis=1), pairs[:, :, :, 1].max(axis=1)], axis=2)
                            parent.write(start//2, values)
                            update(95, '整理多级波形缓存')
                    finally:
                        parent.close()
                    n = (n+1)//2
                    levels.append(n)
            manifest = dict(version=VERSION, sample_rate=rate, channel_count=channels,
                frames=frames, base=base, levels=levels, origin=meta['start_us'])
            (temp / 'manifest.json').write_text(json.dumps(manifest), 'utf-8')
            update(99, '保存波形缓存')
            with manager.lock:
                if target.exists():
                    shutil.rmtree(temp)
                else:
                    temp.replace(target)
                manager.register(target, 'overview')
        finally:
            if temp.exists():
                shutil.rmtree(temp)
            with manager.lock:
                manager.reserved = max(0, manager.reserved - reserved)
                manager.trim()


def decode_tile(source, meta, manifest, start, count):
    """Seek in the original media timebase, then trim by decoded timestamps."""
    av, np = dependencies()
    rate, channels = manifest['sample_rate'], manifest['channel_count']
    result = np.zeros((count, channels), dtype='<f4')
    origin = meta['start_us'] / av.time_base
    with av.open(str(source)) as container:
        stream = next(s for s in container.streams if s.type == 'audio')
        # A short preroll lets compressed decoders settle before the requested tile.
        if start > 0:
            container.seek(max(0, int((origin + max(0, start/rate-1)) * av.time_base)), backward=True)
        resampler = av.AudioResampler(format='fltp', rate=rate, layout=stream.codec_context.layout)
        end = start + count
        def consume(frame):
            if frame.time is None:
                raise ValueError('媒体片段缺少时间戳，无法准确显示精细波形')
            position = round((frame.time - origin) * rate)
            samples = frame.to_ndarray()
            a, z = max(start, position), min(end, position + samples.shape[1])
            if z > a:
                result[a-start:z-start] = samples[:, a-position:z-position].T
            return position >= end
        for frame in container.decode(stream):
            if any(consume(converted) for converted in resampler.resample(frame)):
                break
        else:
            for converted in resampler.resample(None):
                consume(converted)
    np.nan_to_num(result, copy=False)
    return result


def tile(manager, directory, source, meta, manifest, index, tile_frames):
    _, np = dependencies()
    path = directory / 'detail' / f'{tile_frames}-{index}.npy'
    key = str(path)
    with manager.pin(path):
        value = manager.get(key)
        if value is not None:
            with manager.lock:
                manager.touch(path)
            return value
        with manager.decode_lock:
            value = manager.get(key)
            if value is not None:
                return value
            if path.is_file():
                value = np.load(path, allow_pickle=False)
                with manager.lock:
                    manager.touch(path)
            else:
                start = index * tile_frames
                value = decode_tile(source, meta, manifest, start, min(tile_frames, manifest['frames']-start))
                size = value.nbytes + 256
                with manager.lock:
                    if manager.trim(size):
                        path.parent.mkdir(parents=True, exist_ok=True)
                        temp = path.with_suffix('.' + uuid.uuid4().hex + '.partial')
                        try:
                            with temp.open('wb') as output:
                                np.save(output, value, allow_pickle=False)
                            temp.replace(path)
                            manager.register(path, 'detail')
                        finally:
                            temp.unlink(missing_ok=True)
            return manager.put(key, value)


def prefetch(manager, directory, source, meta, manifest, indices, tile_frames):
    """Only the latest neighbour hint survives; no queue grows while scrubbing."""
    with manager.lock:
        manager.generation += 1
        manager.pending = (directory, source, meta, manifest, indices, tile_frames, manager.generation)
        if manager.prefetching:
            return
        manager.prefetching = True
    def run():
        while True:
            # Give the just-issued foreground request a chance to supersede us.
            time.sleep(.02)
            with manager.lock:
                pending, manager.pending = manager.pending, None
                if pending is None:
                    manager.prefetching = False
                    return
            directory, source, meta, manifest, indices, tile_frames, generation = pending
            for index in indices:
                with manager.lock:
                    if generation != manager.generation:
                        break
                if index < 0 or index*tile_frames >= manifest['frames']:
                    continue
                try:
                    tile(manager, directory, source, meta, manifest, index, tile_frames)
                except Exception:
                    pass  # Optional prefetch never suppresses a foreground error.
    _prefetch_pool.submit(run)


def data(dbpath, key, source, meta, start, end, pixels=1200, compact=False):
    _, np = dependencies()
    manager = cache(dbpath)
    overview = overview_path(dbpath, key)
    pixels = max(100, min(8192, int(pixels)))
    with manager.pin(overview):
        try:
            manifest = json.loads((overview / 'manifest.json').read_text('utf-8'))
        except FileNotFoundError:
            return {'ready': False, 'channels': []}
        rate, channels = manifest['sample_rate'], manifest['channel_count']
        with manager.lock:
            manager.touch(overview)
        response = dict(ready=True, mode='peaks', sample_rate=rate, channel_count=channels,
                        start_ms=0, step_ms=0, count=0)
        if not channels:
            return {**response, 'channels': []}
        a = max(0, min(manifest['frames'], math.floor(start * rate / 1000)))
        z = max(a, min(manifest['frames'], math.ceil(end * rate / 1000)))
        if z == a:
            return {**response, 'channels': []}
        per_pixel = max(1, (z-a)/pixels)
        if per_pixel < manifest['base']:
            # At most a few MiB per tile, including high-rate multichannel media.
            tile_frames = max(64, min(rate*2, 4*MIB//(channels*4), manager.memory_limit//(channels*32)))
            step = max(1, math.ceil((z-a)/pixels))
            if step == 1:
                values = np.empty((z-a, channels), dtype='<f4')
            else:
                aggregated = np.empty((math.ceil((z-a)/step),channels,2),dtype='<f4')
                aggregated[:,:,0] = np.inf
                aggregated[:,:,1] = -np.inf
            for index in range(a//tile_frames, (z-1)//tile_frames+1):
                value = tile(manager, overview.parent, source, meta, manifest, index, tile_frames)
                first = max(a,index*tile_frames)
                part = value[first-index*tile_frames:min(len(value),z-index*tile_frames)]
                if step == 1:
                    values[first-a:first-a+len(part)] = part
                else:
                    offset = first-a
                    cuts = np.r_[0,np.arange(step-offset%step,len(part),step)]
                    ids = (offset+cuts)//step
                    aggregated[ids,:,0] = np.minimum(aggregated[ids,:,0],np.minimum.reduceat(part,cuts,axis=0))
                    aggregated[ids,:,1] = np.maximum(aggregated[ids,:,1],np.maximum.reduceat(part,cuts,axis=0))
            if step == 1:
                response['mode'] = 'samples'
                payload = values.T.astype('<f4', copy=True)
            else:
                payload = aggregated.transpose(1,0,2)
                payload = np.rint(np.clip(payload,-1,1)*32767).astype('<i2')
            response.update(start_ms=a*1000/rate, step_ms=step*1000/rate)
            prefetch(manager, overview.parent, source, meta, manifest,
                     [(z-1)//tile_frames+1, a//tile_frames-1], tile_frames)
        else:
            level = min(len(manifest['levels'])-1, max(0,int(math.log2(per_pixel/manifest['base']))))
            block = manifest['base'] * 2**level
            first, last = a//block, min(manifest['levels'][level],math.ceil(z/block))
            values = mapped_slice(overview / f'{level}.npy', first, last)
            stride = max(1, math.ceil(len(values)/pixels))
            cuts = np.arange(0,len(values),stride)
            payload = np.stack([np.minimum.reduceat(values[:,:,0],cuts,axis=0),
                                np.maximum.reduceat(values[:,:,1],cuts,axis=0)],axis=2).transpose(1,0,2).astype('<i2')
            response.update(start_ms=first*block*1000/rate,step_ms=stride*block*1000/rate)
        response['count'] = payload.shape[1]
        if compact:
            response.update(encoding='f32' if response['mode']=='samples' else 'i16',
                            values=base64.b64encode(payload.tobytes(order='C')).decode('ascii'))
        else:
            response['channels'] = (payload if response['mode']=='samples' else payload.astype(np.float32)/32767).tolist()
        with manager.lock:
            response['browser_bytes'] = manager.settings['memory_mb'] * MIB // 4
            response['settings_revision'] = manager.settings_revision
        return response
