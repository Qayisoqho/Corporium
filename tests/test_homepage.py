import source_fixtures
import unittest
import json
import random
import sqlite3
from contextlib import closing
from unittest.mock import patch
import homepage
import home_candidates
import server
import test_server

class HomeTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def test_empty(self):
        code,r=self.call('/api/home');self.assertEqual(code,200)
        self.assertEqual(r['counts']['sentences'],0);self.assertEqual(r['samples'],[])

    def test_default_source_is_distinguished_from_identical_user_authored_source(self):
        a=self.call('/api/example-save',dict(body=dict(ipa='one')))[1]
        b=self.call('/api/example-save',dict(body=dict(ipa='two',source='独立例句')))[1]
        samples={s['id']:s for s in self.call('/api/home')[1]['samples']}
        self.assertTrue(samples[a['id']]['source_default'])
        self.assertFalse(samples[b['id']]['source_default'])
        self.assertEqual(samples[a['id']]['source'],samples[b['id']]['source'])

    def test_global_counts_dedup_and_sources(self):
        self.call('/api/import',dict(title='Text',content='#pass([ipa], (([a],[A]),), [translation])'))
        x=self.call('/api/lexeme-save',dict(headword='a',body={}))[1]
        self.call('/api/example-save',dict(body=dict(ipa='ipa',translation='translation',targets=[dict(lexeme_id=x['id'])])))
        self.call('/api/example-save',dict(body=dict(original='Independent',translation='other',targets=[dict(lexeme_id=x['id'])])))
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.call('/api/import',dict(_language=other,title='Other text',content='#pass([ipa], (([a],[A]),), [translation])'))
        r=self.call('/api/home?language=ordos')[1]
        self.assertEqual(r['counts'],dict(texts=2,corpus_sentences=2,independent_sentences=2,lexemes=1,sentences=4))
        self.assertEqual(len(r['samples']),3)
        self.assertEqual({s['kind'] for s in r['samples']},{'corpus','independent'})
        self.assertEqual({s['language_id'] for s in r['samples']},{'ordos',other})
        independent=next(s for s in r['samples'] if s['kind']=='independent')
        self.assertEqual(independent['lexeme_id'],x['id'])

    def test_bounded_sample_and_blank_entries(self):
        self.call('/api/new-text',dict(title='Blank'))
        self.call('/api/import',dict(title='Many',content='\n'.join('#pass([ipa'+str(i)+'], (([a],[A]),), [translation])' for i in range(40))))
        r=self.call('/api/home')[1]
        self.assertEqual(len(r['samples']),24)
        self.assertEqual(len({s['id'] for s in r['samples']}),24)

    def test_library_only_unlinked_examples_and_word_forms(self):
        first=self.call('/api/example-save',dict(body=dict(ipa='tʰa',translation='独立例句，无词条关联')))[1]
        second=self.call('/api/example-save',dict(body=dict(words=[dict(form='a',gloss='A'),dict(form='b',gloss='B')],translation='仅词格')))[1]
        r=self.call('/api/home')[1]
        self.assertEqual(r['counts']['texts'],0)
        self.assertEqual(r['counts']['sentences'],2)
        self.assertEqual(r['counts']['independent_sentences'],2)
        self.assertEqual({s['id'] for s in r['samples']},{first['id'],second['id']})
        self.assertTrue(all(s['kind']=='independent' and s['lexeme_id'] is None for s in r['samples']))
        self.assertEqual(next(s['original'] for s in r['samples'] if s['id']==second['id']),'a b')

    def test_shared_library_example_counts_once_and_refreshes_after_delete(self):
        words=[self.call('/api/lexeme-save',dict(headword=w,body={}))[1]['id'] for w in ['a','b']]
        example=self.call('/api/example-save',dict(body=dict(ipa='one',targets=[dict(lexeme_id=w) for w in words])))[1]
        r=self.call('/api/home')[1]
        self.assertEqual(r['counts']['sentences'],1)
        self.assertEqual(len(r['samples']),1)
        code,deleted=self.call('/api/example-delete',dict(id=example['id'],revision=example['revision'],confirmed=True))
        self.assertEqual(code,200,deleted)
        r=self.call('/api/home')[1]
        self.assertEqual(r['counts']['sentences'],0)
        self.assertEqual(r['samples'],[])

    def test_persistent_dedup_promotes_sources_and_rolls_back_with_content(self):
        for word in ('a','b'):
            self.call('/api/import',dict(title=word,content=f'#pass([same], (([{word}],[A]),), [translation])'))
        independent=self.call('/api/example-save',dict(body=dict(ipa='same',translation='translation')))[1]
        with server.connect(audit=False) as db:
            ids=[r[0] for r in db.execute('SELECT e.id FROM entries e JOIN texts t ON t.id=e.text_id ORDER BY t.id,e.position')]
            first=homepage.overview(db)
            self.assertEqual([(s['kind'],s['id']) for s in first['samples']],[('corpus',ids[0])])
            db.execute('SAVEPOINT sample_change')
            db.execute('DELETE FROM entries WHERE id=?',(ids[0],))
            self.assertEqual(homepage.overview(db)['samples'][0]['id'],ids[1])
            db.execute('DELETE FROM entries WHERE id=?',(ids[1],))
            self.assertEqual(homepage.overview(db)['samples'][0]['id'],independent['id'])
            db.execute('ROLLBACK TO sample_change');db.execute('RELEASE sample_change')
            self.assertEqual(homepage.overview(db),first)
            self.assertEqual(db.execute('SELECT n FROM home_candidate_state').fetchone()[0],1)

    def test_identity_changes_refresh_one_source_but_notes_and_fonts_stay_ready(self):
        example=self.call('/api/example-save',dict(body=dict(original='a',translation='one')))[1]
        with server.connect(audit=False) as db:
            homepage.overview(db)
            source_fixtures.patch_values(db,'dictionary_examples',example['id'],((('notes',), 'note'), (('source',), 'new source')))
            self.assertEqual(db.execute('SELECT count(*) FROM home_candidate_dirty').fetchone()[0],0)
            db.execute("UPDATE languages SET metadata=json_set(metadata,'$.ipa_font','Junicode') WHERE id='ordos'")
            self.assertEqual(db.execute('SELECT rebuild FROM home_candidate_state').fetchone()[0],0)
            sample=homepage.overview(db)['samples'][0]
            self.assertEqual((sample['source'],sample['ipa_font']),('new source','Junicode'))
            source_fixtures.patch_values(db,'dictionary_examples',example['id'],((('translation',), 'two'),))
            self.assertEqual(db.execute('SELECT count(*) FROM home_candidate_dirty').fetchone()[0],1)
            with patch.object(home_candidates,'_record',wraps=home_candidates._record) as record:
                self.assertEqual(homepage.overview(db)['samples'][0]['translation'],'two')
                self.assertEqual(record.call_count,1)
            self.assertEqual(db.execute('SELECT count(*) FROM home_candidate_dirty').fetchone()[0],0)

    def test_dense_slots_survive_merges_splits_new_language_and_external_replace(self):
        examples=[self.call('/api/example-save',dict(body=dict(original=x)))[1] for x in ('a','b','c')]
        with server.connect(audit=False) as db:
            homepage.overview(db)
            source_fixtures.patch_values(db,'dictionary_examples',examples[1]['id'],((('original',), 'a'),))
            self.assertEqual(len(homepage.overview(db)['samples']),2)
            source_fixtures.patch_values(db,'dictionary_examples',examples[0]['id'],((('original',), 'd'),))
            self.assertEqual(len(homepage.overview(db)['samples']),3)
            from record_sources import read,write
            owner=examples[2]['id']
            language,revision=db.execute('SELECT language_id,revision FROM dictionary_examples WHERE id=?',(owner,)).fetchone()
            body=read(db,'dictionary_examples',owner)
            db.execute('DELETE FROM dictionary_examples WHERE id=?',(owner,))
            write(db,'dictionary_examples',owner,dict(body,original='e'),columns=dict(language_id=language,revision=revision),insert=True)
            samples=homepage.overview(db)['samples']
            self.assertEqual({s['original'] for s in samples},{'a','d','e'})
            n=db.execute('SELECT n FROM home_candidate_state').fetchone()[0]
            self.assertEqual([r[0] for r in db.execute('SELECT slot FROM home_candidate_slots ORDER BY slot')],list(range(n)))
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        with server.connect(audit=False) as db:
            db.execute('UPDATE dictionary_examples SET language_id=? WHERE id=?',(other,examples[0]['id']))
            sample=next(s for s in homepage.overview(db)['samples'] if s['id']==examples[0]['id'])
            self.assertEqual(sample['language_id'],other)

    def test_readonly_ready_and_dirty_fallback_and_portable_drop(self):
        example=self.call('/api/example-save',dict(body=dict(original='a')))[1]
        first=self.call('/api/home')[1]
        with closing(sqlite3.connect(server.DB.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            self.assertEqual(homepage.overview(db),first)
        with server.connect(audit=False) as db:
            source_fixtures.patch_values(db,'dictionary_examples',example['id'],((('original',), 'b'),))
        with closing(sqlite3.connect(server.DB.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            self.assertEqual(homepage.overview(db)['samples'][0]['original'],'b')
        with server.connect(audit=False) as db:
            server.sentence_search_index.drop(db)
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name GLOB 'home_candidate_*'").fetchone()[0],0)
            self.assertEqual(homepage.overview(db)['samples'][0]['original'],'b')
        server.init()
        self.assertEqual(self.call('/api/home')[1]['samples'][0]['original'],'b')

    def test_initial_fingerprint_collisions_never_merge_distinct_full_identities(self):
        for text in ('a','b','a'):
            self.call('/api/example-save',dict(body=dict(original=text)))
        class Collision:
            def digest(self):return b'constant fingerprint'
        with server.connect(audit=False) as db,patch.object(home_candidates.hashlib,'sha256',return_value=Collision()):
            self.assertEqual({s['original'] for s in homepage.overview(db)['samples']},{'a','b'})
            self.assertEqual(db.execute('SELECT n FROM home_candidate_state').fetchone()[0],2)

    def test_upsert_save_and_undo_refresh_without_duplicate_dirty_keys(self):
        example=self.call('/api/example-save',dict(body=dict(ipa='a',translation='one')))[1]
        self.call('/api/home')
        example['body']['translation']='two'
        code,saved=self.call('/api/example-save',example)
        self.assertEqual(code,200,saved)
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM home_candidate_dirty').fetchone()[0],1)
        self.assertEqual(self.call('/api/home')[1]['samples'][0]['translation'],'two')
        state=self.call('/api/undo-state')[1]
        self.assertEqual(self.call('/api/undo',dict(generation=state['generation']))[0],200)
        self.assertEqual(self.call('/api/home')[1]['samples'][0]['translation'],'one')
