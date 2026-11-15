"""Early duplicate-instance handling must not open a second project or window."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock,patch

import desktop_startup


class StartupTests(unittest.TestCase):
    def test_duplicate_focuses_existing_progress_and_releases_its_handle(self):
        kernel,user=Mock(),Mock()
        kernel.CreateMutexW.return_value=11
        user.FindWindowW.return_value=22
        with tempfile.TemporaryDirectory() as folder,patch.object(desktop_startup,'settings_home',return_value=Path(folder)),\
             patch.object(desktop_startup.ctypes,'WinDLL',side_effect=lambda name,**kw:kernel if name=='kernel32' else user,create=True),\
             patch.object(desktop_startup.ctypes,'get_last_error',return_value=183,create=True),patch.object(desktop_startup.threading,'Thread') as thread:
            with self.assertRaises(SystemExit) as ended:desktop_startup.Startup([])
        self.assertEqual(ended.exception.code,0)
        thread.assert_not_called()
        user.FindWindowW.assert_called_once_with(None,'Corporium — 正在启动')
        user.ShowWindow.assert_called_once_with(22,9)
        user.SetForegroundWindow.assert_called_once_with(22)
        kernel.CloseHandle.assert_called_once_with(11)

    def test_finished_startup_ignores_late_progress_and_repeated_completion(self):
        startup=object.__new__(desktop_startup.Startup)
        startup.closed=False;startup.hwnd=22;startup.user=Mock();startup.events=[];startup.started=desktop_startup.time.perf_counter()
        startup.finish();startup.stage(7);startup.finish('failed')
        self.assertEqual([event['stage'] for event in startup.events],['ready'])
        startup.user.PostMessageW.assert_called_once_with(22,0x8002,0,0)


if __name__=='__main__':unittest.main()
