import json
import unittest
from unittest.mock import patch

import dictionary_search
import evidence_index
import server
import test_lexicon


class EvidenceValueIndexTests(unittest.TestCase):
    def test_unique_values_short_queries_and_case_match_original_substrings(self):
        index=evidence_index.EvidenceIndex()
        values=['Straße','e\u0301cole','漢字𐀀','abc---bcd','ABC','a\x00b', 'İstanbul']
        query=evidence_index.Query(index,'none',False)
        query.remember(('corpus','one'),b'one',values,{'examples.words.form':'词形'})
        for case in (True,False):
            for needle in ('é','STRASSE','Straße','abc','abcd','漢','𐀀','\x00','i\u0307s','missing'):
                import unicodedata
                normalized=[unicodedata.normalize('NFC',v) for v in values]
                expected={v for v in normalized if (needle in v if case else needle.casefold() in v.casefold())}
                got={index.values[i][0] for i in index.matching(needle,case)}
                self.assertEqual(got,expected,(case,needle))

    def test_incremental_updates_eviction_and_deletion_release_shared_values(self):
        index=evidence_index.EvidenceIndex(limit=22000)
        for i in range(80):
            source=str(i);key=('corpus',source);q=evidence_index.Query(index,'common',False)
            fingerprint,_=q.lookup(key,source)
            q.remember(key,fingerprint,['common',str(i)*8],{'examples.words.form':'词形'})
            self.assertLessEqual(index.bytes,index.limit)
            self.assertTrue(index.matching('common',False))
        key=next(reversed(index.records));q=evidence_index.Query(index,'changed',False)
        fingerprint,cached=q.lookup(key,'new source');self.assertIsNone(cached)
        self.assertTrue(q.remember(key,fingerprint,['changed'],{'examples.notes':'备注'}))
        q.finish();self.assertEqual(list(index.records),[key])
        self.assertFalse(index.matching('common',False))
        evidence_index.Query(index,'',False).finish()
        self.assertEqual((index.bytes,index.values,index.field_sets),(0,{},{}))


class EvidenceIntegrationTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown

    def rows(self,db):
        return [{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT * FROM dictionary_targets')]

    def compare(self,db,needle,case=False):
        rows=self.rows(db);spec=dict(field='all',case=case)
        full=dictionary_search.SearchIndex(db,'ordos',rows).prepare(spec)
        indexed=dictionary_search.SearchIndex(db,'ordos',rows,search_spec=spec,query=needle).prepare(spec)
        expected=[r['id'] for r in rows if full.matches(r,needle)]
        self.assertEqual([r['id'] for r in rows if indexed.matches(r,needle)],expected)
        self.assertEqual(indexed.fields,full.fields)
        return expected

    def test_sources_catalog_owners_layers_rollback_and_deletion_stay_current(self):
        with server.connect(audit=False) as db:
            db.executemany('INSERT INTO lexemes VALUES(?,?,?,?,1)',[(x,'ordos',x,'{}') for x in ('one','two')])
            def body(label,owner='one'):
                return json.dumps(dict(ipa='Straße',translation='e\u0301cole',words=[dict(form=label,gloss='词',annotation_id='word')],targets=[dict(lexeme_id=owner)],custom=dict(title='custom-only')))
            db.execute('INSERT INTO dictionary_examples VALUES(?,?,?,1)',('example','ordos',body('before-only')))
            db.execute("INSERT INTO annotation_layers(id,language_id,name,font,anchor) VALUES('layer','ordos','extra','Junicode','word')")
            db.execute("INSERT INTO annotation_cells VALUES('cell','independent','example','word','layer','layer-only',1)")
            for needle in ('before-only','STRASSE','Straße','é','layer-only','custom-only','词','absent'):
                for case in (False,True):self.compare(db,needle,case)
            # Warm reuse must not walk this source again.
            original=dictionary_search.SearchIndex.document
            def checked(self,row,*args,**kwargs):
                if kwargs.get('prefix')==('examples',):raise AssertionError('unchanged source was reparsed')
                return original(self,row,*args,**kwargs)
            with patch.object(dictionary_search.SearchIndex,'document',checked):
                rows=self.rows(db);dictionary_search.SearchIndex(db,'ordos',rows,search_spec=dict(field='all'),query='new query')
            db.execute('SAVEPOINT preview')
            db.execute('UPDATE dictionary_examples SET body=? WHERE id=?',(body('after-only','two'),'example'))
            self.assertEqual(self.compare(db,'after-only'),['two']);self.assertEqual(self.compare(db,'before-only'),[])
            db.execute('ROLLBACK TO preview');db.execute('RELEASE preview')
            self.assertEqual(self.compare(db,'before-only'),['one']);self.assertEqual(self.compare(db,'after-only'),[])
            # No revision bump is needed for correctness: actual JSON is checked.
            db.execute('UPDATE dictionary_examples SET body=? WHERE id=?',(body('before-only','two'),'example'))
            self.assertEqual(self.compare(db,'before-only'),['two'])
            db.execute("DELETE FROM dictionary_examples WHERE id='example'")
            self.assertEqual(self.compare(db,'before-only'),[])
            self.assertEqual(self.compare(db,'layer-only'),[])
            # Catalog names and symbols also invalidate derived evidence values.
            db.execute("INSERT INTO writing_types(id,language_id,name,font,position) VALUES('writing','ordos','Old script','Junicode',0)")
            b=json.loads(body('word'));b['orthographies']=[dict(type_id='writing',text='sample')]
            db.execute('INSERT INTO dictionary_examples VALUES(?,?,?,1)',('new','ordos',json.dumps(b)))
            self.assertEqual(self.compare(db,'Old script'),['one'])
            db.execute("UPDATE writing_types SET name='New script' WHERE id='writing'")
            self.assertEqual(self.compare(db,'Old script'),[]);self.assertEqual(self.compare(db,'New script'),['one'])
