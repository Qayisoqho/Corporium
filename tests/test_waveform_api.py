import test_server
import waveform_cache
import unittest


class WaveformAPITests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    def test_waveform_settings_api_is_project_wide_persistent_and_origin_guarded(self):
        import server
        code,result=self.call('/api/timeline-wave-settings')
        self.assertEqual(code,200,result)
        self.assertEqual((result['memory_mb'],result['disk_mb']),(128,2048))
        code,result=self.call('/api/timeline-wave-settings',dict(memory_mb=64,disk_mb=512))
        self.assertEqual(code,200,result)
        self.assertEqual(result['browser_bytes'],16*waveform_cache.MIB)
        self.assertEqual(self.call('/api/timeline-wave-settings?language=all')[1]['memory_mb'],64)
        self.assertEqual(self.call('/api/timeline-wave-settings',dict(memory_mb=16,disk_mb=64),origin='https://invalid.example')[0],403)
        self.assertEqual(self.call('/api/timeline-wave-settings',dict(memory_mb=0,disk_mb=64))[0],400)
        self.assertEqual(self.call('/api/timeline-wave-settings')[1]['memory_mb'],64)
