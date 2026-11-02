"""Completed evidence results must be tied to the reader's actual snapshot."""
import json
import sqlite3
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from contextlib import closing
import dictionary_search
import evidence_index
import lexicon
import long_tasks
import server
import test_text_tools


class EvidenceSnapshotTests(unittest.TestCase):
    for name in ('tearDown','call','seed','entries','word','link'):
        locals()[name]=getattr(test_text_tools.TextToolsTests,name)

    def setUp(self):
        test_text_tools.TextToolsTests.setUp(self)
        with evidence_index._lock:evidence_index._results.clear();evidence_index.result_bytes=0

    def fixture(self):
        e=self.seed('#pass([IPA], (([home],[house]),), [evidence-only Straße])');x=self.word();self.link(e['words'][0]['unit_id'],x)
        return e,x

    def search(self,query='evidence-only'):
        code,result=self.call('/api/lexemes?'+urlencode(dict(language='ordos',q=query)))
        self.assertEqual(code,200,result);return result

    def change(self,e,value):
        with server.connect(audit=False) as db:
            body=json.loads(db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0]);body['translation']=value;body['raw']='';body['edited']=True
            db.execute('UPDATE entries SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),e['id']))

    def test_repeated_filter_reuses_complete_evidence_and_returns_independent_values(self):
        self.fixture();first=self.search();self.assertEqual(first['total'],1)
        with patch.object(dictionary_search,'example_rows',side_effect=AssertionError('repeated evidence scan')):
            self.assertEqual(self.search(),first)
        first['items'].clear()
        self.assertEqual(self.search()['total'],1)
        self.assertEqual(self.search('STRASSE')['total'],1)
        self.assertEqual(self.search('absent')['total'],0)

    def test_external_sql_without_version_bump_invalidates_cached_match(self):
        e,_=self.fixture();self.assertEqual(self.search()['total'],1)
        with server.connect(audit=False) as db:version=db.execute('SELECT version FROM analysis_state').fetchone()[0]
        self.change(e,'changed externally')
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT version FROM analysis_state').fetchone()[0],version)
        with patch.object(dictionary_search,'example_rows',wraps=dictionary_search.example_rows) as scan:
            self.assertEqual(self.search()['total'],0);self.assertFalse(scan.called)

    def test_pinned_wal_reader_cannot_use_a_newer_completed_result(self):
        with closing(sqlite3.connect(server.DB)) as setup:setup.execute('PRAGMA journal_mode=WAL')
        e,_=self.fixture();self.assertEqual(self.search()['total'],1)
        with server.connect(audit=False,observe_snapshot=True) as old:
            old.execute('BEGIN');old.execute('SELECT body FROM entries').fetchone()
            self.change(e,'new committed value');self.assertEqual(self.search()['total'],0)
            result=lexicon.list_lexemes(old,'ordos','evidence-only')
            self.assertEqual(result['total'],1)
        self.assertEqual(self.search()['total'],0)

    def test_uncommitted_writes_and_missing_observer_use_live_sources(self):
        e,_=self.fixture();self.assertEqual(self.search()['total'],1)
        with server.connect(audit=False,observe_snapshot=True) as db:
            db.execute('BEGIN IMMEDIATE');body=json.loads(db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0]);body['translation']='uncommitted';body['raw']='';body['edited']=True
            db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(body),e['id']))
            self.assertEqual(lexicon.list_lexemes(db,'ordos','evidence-only')['total'],0)
        with server.connect(audit=False) as db,patch.object(dictionary_search,'example_rows',wraps=dictionary_search.example_rows) as scan:
            self.assertEqual(lexicon.list_lexemes(db,'ordos','evidence-only')['total'],0);self.assertFalse(scan.called)

    @patch('sentence_search_index.available',new=lambda db:False)
    def test_cancelled_scan_does_not_publish_partial_results(self):
        self.fixture();original=dictionary_search.example_rows
        def interrupted(*a,**kw):
            for row in original(*a,**kw):
                yield row
                raise long_tasks.Cancelled('audit cancellation')
        with server.connect(audit=False,observe_snapshot=True) as db:
            db.execute('BEGIN')
            with patch.object(dictionary_search,'example_rows',interrupted),self.assertRaises(long_tasks.Cancelled):lexicon.list_lexemes(db,'ordos','evidence-only')
        self.assertFalse(evidence_index._results);self.assertEqual(self.search()['total'],1)

    @patch('sentence_search_index.available',new=lambda db:False)
    def test_oversize_completed_result_falls_back_without_changing_matches(self):
        self.fixture()
        with patch.object(evidence_index,'RESULT_LIMIT',1):
            first=self.search();self.assertEqual(first['total'],1);self.assertFalse(evidence_index._results)
            self.assertEqual(self.search(),first)

    def test_edit_undo_and_redo_each_use_their_current_sources(self):
        self.fixture();e=self.entries()[0];e['notes']='cache-undo-note'
        self.assertEqual(self.call('/api/save',e)[0],200);self.assertEqual(self.search('cache-undo-note')['total'],1)
        e=self.entries()[0];e['notes']=''
        code,result=self.call('/api/save',e);self.assertEqual(code,200,result);self.assertEqual(self.search('cache-undo-note')['total'],0)
        for action,total in [('undo',1),('redo',0)]:
            state=self.call('/api/undo-state?language=ordos')[1]
            code,result=self.call('/api/'+action,dict(generation=state['generation'],_language='ordos'))
            self.assertEqual(code,200,result);self.assertEqual(self.search('cache-undo-note')['total'],total)
