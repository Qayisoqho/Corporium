"""Windows PCM input. No microphone is opened by enumeration or import.

The worker owns the handle and buffers; the UI never processes audio callbacks.
WAVE_FORMAT_DIRECT prevents ACM from silently converting unsupported formats.
"""
import ctypes as C
import sys
import time


class Format(C.Structure):
    _pack_ = 1
    _fields_ = [('tag', C.c_uint16), ('channels', C.c_uint16), ('rate', C.c_uint32),
                ('byte_rate', C.c_uint32), ('align', C.c_uint16), ('bits', C.c_uint16), ('extra', C.c_uint16)]


class Header(C.Structure):
    _fields_ = [('data', C.c_void_p), ('length', C.c_uint32), ('recorded', C.c_uint32),
                ('user', C.c_size_t), ('flags', C.c_uint32), ('loops', C.c_uint32),
                ('next', C.c_void_p), ('reserved', C.c_size_t)]


class Caps(C.Structure):
    _fields_ = [('manufacturer', C.c_uint16), ('product', C.c_uint16), ('version', C.c_uint32),
                ('name', C.c_wchar * 32), ('formats', C.c_uint32), ('channels', C.c_uint16), ('reserved', C.c_uint16)]


def pcm_format(rate, bits, channels):
    align = channels * (bits // 8)
    return Format(1, channels, rate, rate * align, align, bits, 0)


def library():
    if sys.platform != 'win32':
        raise ValueError('现场录音目前需要 Windows 桌面环境')
    dll = C.WinDLL('winmm')
    dll.waveInGetNumDevs.restype = C.c_uint32
    dll.waveInGetDevCapsW.argtypes = [C.c_size_t, C.POINTER(Caps), C.c_uint32]
    dll.waveInOpen.argtypes = [C.POINTER(C.c_void_p), C.c_uint32, C.POINTER(Format), C.c_size_t, C.c_size_t, C.c_uint32]
    for name in ('waveInPrepareHeader', 'waveInUnprepareHeader', 'waveInAddBuffer'):
        getattr(dll, name).argtypes = [C.c_void_p, C.POINTER(Header), C.c_uint32]
    for name in ('waveInStart', 'waveInReset', 'waveInClose'):
        getattr(dll, name).argtypes = [C.c_void_p]
    return dll


def check(code):
    if code:
        raise ValueError({2: '录音设备已不存在，请重新选择', 4: '录音设备正被占用',
                          5: '没有可用的录音设备', 32: '设备不支持此录音规格，请选择其他规格'}.get(
                              code, '无法使用录音设备，请检查麦克风权限与连接'))


def devices():
    dll = library()
    result = []
    for device in range(dll.waveInGetNumDevs()):
        cap = Caps()
        if dll.waveInGetDevCapsW(device, C.byref(cap), C.sizeof(cap)):
            continue
        supported = []
        for rate in (44100, 48000, 96000):
            for bits in (16, 24):
                for channels in (1, 2):
                    fmt = pcm_format(rate, bits, channels)
                    if not dll.waveInOpen(None, device, C.byref(fmt), 0, 0, 1 | 8):
                        supported.append(dict(rate=rate, bits=bits, channels=channels))
        result.append(dict(id=device, name=cap.name, formats=supported))
    return result


class Input:
    def __init__(self, config):
        self.config = config
        self.dll = library()
        self.handle = C.c_void_p()
        self.buffers = []
        self.next = 0
        self.started = False

    def __enter__(self):
        c = self.config
        cap=Caps()
        check(self.dll.waveInGetDevCapsW(c['device'],C.byref(cap),C.sizeof(cap)))
        c['device_name']=cap.name
        fmt = pcm_format(c['rate'], c['bits'], c['channels'])
        check(self.dll.waveInOpen(C.byref(self.handle), c['device'], C.byref(fmt), 0, 0, 8))
        try:
            for _ in range(12):
                data = C.create_string_buffer((c['rate'] // 10) * fmt.align)
                header = Header(data=C.addressof(data), length=C.sizeof(data))
                check(self.dll.waveInPrepareHeader(self.handle, C.byref(header), C.sizeof(header)))
                self.buffers.append((header, data))
                check(self.dll.waveInAddBuffer(self.handle, C.byref(header), C.sizeof(header)))
            check(self.dll.waveInStart(self.handle))
            self.started = True
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def read(self, stop):
        header, data = self.buffers[self.next]
        deadline = time.monotonic() + 4
        while not header.flags & 1:
            if stop.wait(.01):
                return b'', False
            if time.monotonic() > deadline:
                raise ValueError('录音设备没有返回声音，已停止并保留已录部分')
        starved = all(h.flags & 1 for h, _ in self.buffers)
        chunk = data.raw[:header.recorded]
        header.recorded = 0
        check(self.dll.waveInAddBuffer(self.handle, C.byref(header), C.sizeof(header)))
        self.next = (self.next + 1) % len(self.buffers)
        return chunk, starved

    def drain(self):
        # Reset returns the partial buffer as well as all still queued buffers.
        check(self.dll.waveInReset(self.handle))
        for i in range(len(self.buffers)):
            header, data = self.buffers[(self.next + i) % len(self.buffers)]
            if header.flags & 1 and header.recorded:
                yield data.raw[:header.recorded]
                header.recorded = 0

    def __exit__(self, *args):
        if self.handle:
            self.dll.waveInReset(self.handle)
            for header, data in self.buffers:
                self.dll.waveInUnprepareHeader(self.handle, C.byref(header), C.sizeof(header))
            self.dll.waveInClose(self.handle)
            self.handle = C.c_void_p()

