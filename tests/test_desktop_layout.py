import sys,types,unittest
from unittest.mock import patch
import desktop

class DesktopLayoutTests(unittest.TestCase):
    def test_half_work_area_uses_logical_pixels_and_keeps_expanded_limit(self):
        self.assertEqual(desktop.sidebar_minimum_size(False,1920),(1100,600))
        self.assertEqual(desktop.sidebar_minimum_size(True,1920),(960,600))
        self.assertEqual(desktop.sidebar_minimum_size(True,2880,1.5),(960,600))
        self.assertEqual(desktop.sidebar_minimum_size(True,1366),(683,600))
        self.assertEqual(desktop.sidebar_minimum_size(True,3840),(1100,600))
        self.assertEqual(desktop.sidebar_minimum_size(True,800),(480,600))

    def test_native_adapter_marshals_to_ui_thread_and_updates_on_monitor_change(self):
        # Fake the installed WinForms API; this test never creates a real window.
        system=types.ModuleType('System');system.Action=lambda f:f
        drawing=types.ModuleType('System.Drawing');drawing.Size=lambda w,h:types.SimpleNamespace(Width=w,Height=h)
        forms=types.ModuleType('System.Windows.Forms');area=types.SimpleNamespace(Width=2880)
        forms.Screen=types.SimpleNamespace(FromControl=lambda n:types.SimpleNamespace(WorkingArea=area))
        calls=[];native=types.SimpleNamespace(_scale=1.5,InvokeRequired=True,Invoke=lambda f:(calls.append('ui'),f())[1])
        bridge=desktop.Bridge(None);bridge._origin='http://127.0.0.1:1234';bridge._window=types.SimpleNamespace(native=native,get_current_url=lambda:bridge._origin+'/')
        with patch.dict(sys.modules,{'System':system,'System.Drawing':drawing,'System.Windows.Forms':forms}):
            self.assertEqual(bridge.set_sidebar_collapsed(True),dict(min_width=960,min_height=600))
            self.assertEqual((native.MinimumSize.Width,native.MinimumSize.Height),(1440,900))
            area.Width=1920;native._scale=1
            self.assertEqual(bridge._apply_window_minimum()['min_width'],960)
            area.Width=1366
            self.assertEqual(bridge._apply_window_minimum()['min_width'],683)
            self.assertEqual(bridge.set_sidebar_collapsed(False)['min_width'],1100)
            self.assertEqual(bridge._window.min_size,(1100,600));self.assertEqual(len(calls),4)

    def test_bridge_rejects_other_origins_and_non_boolean_states(self):
        b=desktop.Bridge(None);b._origin='http://127.0.0.1:1234';b._window=types.SimpleNamespace(get_current_url=lambda:'https://other.invalid/')
        with patch('desktop.logging.exception'):
            self.assertIn('error',b.set_sidebar_collapsed(True))
            b._window.get_current_url=lambda:b._origin+'/'
            self.assertIn('error',b.set_sidebar_collapsed(1))
