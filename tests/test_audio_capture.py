"""Exercise native buffer ownership/order with a simulated WinMM driver."""
import ctypes as C
import threading
import unittest
from unittest.mock import patch
import audio_capture as audio


class Driver:
    def __init__(self):self.headers=[];self.calls=[]
    def waveInGetDevCapsW(self,device,ptr,size):
        C.cast(ptr,C.POINTER(audio.Caps)).contents.name='Synthetic driver'
        return 0
    def waveInOpen(self,handle,device,fmt,callback,instance,flags):
        self.calls.append(('open',flags));C.cast(handle,C.POINTER(C.c_void_p))[0]=C.c_void_p(123)
        return 0
    def waveInPrepareHeader(self,handle,ptr,size):
        h=C.cast(ptr,C.POINTER(audio.Header)).contents;h.flags=2;self.headers.append(h);return 0
    def waveInAddBuffer(self,handle,ptr,size):
        h=C.cast(ptr,C.POINTER(audio.Header)).contents;h.flags=2|16;return 0
    def waveInStart(self,handle):
        h=self.headers[0];C.memmove(h.data,b'\x01\x02\x03\x04',4);h.recorded=4;h.flags=2|1;return 0
    def waveInReset(self,handle):
        self.calls.append(('reset',))
        h=self.headers[1];C.memmove(h.data,b'\x05\x06',2);h.recorded=2
        for h in self.headers:h.flags=2|1
        return 0
    def waveInUnprepareHeader(self,*args):self.calls.append(('unprepare',));return 0
    def waveInClose(self,*args):self.calls.append(('close',));return 0


class NativeCaptureTests(unittest.TestCase):
    def test_direct_pcm_order_partial_stop_and_buffer_lifetime(self):
        driver=Driver();config=dict(device=0,rate=48000,bits=24,channels=1)
        with patch.object(audio,'library',return_value=driver):
            with audio.Input(config) as capture:
                self.assertEqual(len(capture.buffers),12)
                self.assertEqual(capture.read(threading.Event()),(b'\x01\x02\x03\x04',False))
                self.assertEqual(list(capture.drain()),[b'\x05\x06'])
        self.assertEqual(config['device_name'],'Synthetic driver')
        self.assertEqual(driver.calls[0],('open',8))
        self.assertEqual(driver.calls[-1],('close',))
        self.assertEqual(driver.calls.count(('unprepare',)),12)

    def test_waiting_can_stop_without_requeue_or_access_after_close(self):
        driver=Driver();stop=threading.Event();stop.set()
        with patch.object(audio,'library',return_value=driver):
            with audio.Input(dict(device=0,rate=48000,bits=16,channels=2)) as capture:
                capture.read(threading.Event())
                self.assertEqual(capture.read(stop),(b'',False))
        self.assertFalse(capture.handle)
