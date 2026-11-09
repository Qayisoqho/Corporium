"""The dictionary reading controls load as static assets without a project."""
import unittest
from unittest.mock import patch

import server


class DictionaryEvidenceAssetTests(unittest.TestCase):
    def check_asset(self, filename, mime):
        expected=(server.ROOT/'web'/filename).read_bytes()
        self.assertTrue(expected)
        for suffix in ('', '?v=asset-regression'):
            with self.subTest(path='/'+filename+suffix):
                handler=object.__new__(server.Handler)
                handler.path='/'+filename+suffix
                handler.headers={}
                responses=[]
                handler.send=lambda data,code=200,mime=None:responses.append((code,data,mime))
                with patch.object(server,'connect',side_effect=AssertionError('Static evidence assets must not open a project')) as connect:
                    handler.do_GET()
                connect.assert_not_called()
                self.assertEqual(len(responses),1)
                code,data,content_type=responses[0]
                self.assertEqual(code,200)
                self.assertEqual(content_type,mime)
                self.assertEqual(data,expected)

    def test_javascript_is_served_with_correct_content_and_mime_without_database(self):
        self.check_asset('dictionary-evidence.js','text/javascript; charset=utf-8')

    def test_stylesheet_is_served_with_correct_content_and_mime_without_database(self):
        self.check_asset('dictionary-evidence.css','text/css; charset=utf-8')


if __name__=='__main__':unittest.main()
