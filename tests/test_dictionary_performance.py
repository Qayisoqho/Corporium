"""Large-list reads must stay bounded without changing dictionary semantics."""
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import server,lexicon,dictionary_data,dictionary_search,morpheme_registry,homonyms,morphology
import test_lexicon

class DictionaryPerformanceTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call

    def seed(self):
        with server.connect(audit=False) as db:
            for i in range(123):
                b=lexicon.normalize({'notes':'keep','orthographies':[{'label':'旧书写','text':'字'+str(i),'font':'Junicode'}],'usages':[{'pos':'名词','senses':[{'short_gloss':'义'+str(i),'definition':'详细内容'}]}]})
                db.execute('INSERT INTO lexemes VALUES(?,?,?,?,1)',('x'+str(i),'ordos',f'form-{i:03}',json.dumps(b)))
            db.executemany('INSERT INTO morphemes VALUES(?,?,?,?,?,1)',[(f'm{i}','ordos',f'p{i:03}',1,'{"gloss":"note"}') for i in range(123)])

    def test_specific_dictionary_fields_skip_evidence_but_combined_example_conditions_keep_it(self):
        self.seed()
        with server.connect(audit=False) as db:
            db.execute('INSERT INTO dictionary_examples VALUES(?,?,?,1)',('ex','ordos',json.dumps(dict(ipa='',translation='evidence-only',words=[],targets=[dict(lexeme_id='x0')]))))
            statements=[];db.set_trace_callback(statements.append)
            result=lexicon.list_lexemes(db,'ordos','form-0',search=dict(field='headword'),summary=True)
            self.assertEqual(result['total'],100)
            self.assertFalse(any('FROM lexical_links' in s or 'FROM dictionary_examples' in s for s in statements))
            spec=dict(field='headword',conditions=[dict(field='examples.translation',op='contains',value='evidence-only')])
            result=lexicon.list_lexemes(db,'ordos','form-0',search=spec,summary=True)
            self.assertEqual([x['id'] for x in result['items']],['x0'])

    def test_link_picker_keeps_full_meanings_without_unused_occurrence_counts(self):
        self.seed()
        with server.connect(audit=False) as db,patch.object(lexicon,'occurrence_count',side_effect=AssertionError('picker does not display occurrence counts')):
            data=lexicon.list_lexemes(db,'ordos',counts=False,targets=True)
            self.assertTrue(data['items'][0]['body']['usages'][0]['senses'])
            self.assertNotIn('example_count',data['items'][0])
            self.assertEqual(data['total'],246)

    def test_shared_evidence_boolean_matches_complete_documents_with_unicode_and_layers(self):
        self.seed()
        with server.connect(audit=False) as db:
            example=dict(ipa='Straße',translation='e\u0301 evidence-only',notes='',words=[dict(form='word',gloss='GEN',annotation_id='w0')],targets=[dict(lexeme_id='x0'),dict(lexeme_id='x1')])
            db.execute('INSERT INTO dictionary_examples VALUES(?,?,?,1)',('ex','ordos',json.dumps(example)))
            db.execute("INSERT INTO annotation_layers(id,language_id,name,font,anchor) VALUES('layer','ordos','extra','Junicode','word')")
            db.execute("INSERT INTO annotation_cells VALUES('cell','independent','ex','w0','layer','layer-only',1)")
            rows=[{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT * FROM dictionary_targets')]
            full=dictionary_search.SearchIndex(db,'ordos',rows)
            for case in (True,False):
                spec=dict(field='all',case=case)
                for query in ('evidence-only','STRASSE','Straße','é','GEN','layer-only','form-001','absent'):
                    expected=[r['id'] for r in rows if full.prepare(spec).matches(r,query)]
                    fast=dictionary_search.SearchIndex(db,'ordos',rows,search_spec=spec,query=query).prepare(spec)
                    self.assertEqual([r['id'] for r in rows if fast.matches(r,query)],expected,(case,query))
                    self.assertEqual(fast.fields,full.fields)

    def test_full_validation_reuses_target_bodies_without_skipping_dangling_senses(self):
        self.seed()
        self.call('/api/import',dict(title='dense',content='\n'.join('#pass([word], (([word],[note]),), [translation])' for _ in range(80))))
        with server.connect(audit=False) as db:
            raw=db.execute("SELECT body FROM lexemes WHERE id='x0'").fetchone()[0]
            body=json.loads(raw);u=body['usages'][0];sid=u['senses'][0]['id']
            units=list(db.execute("SELECT id FROM corpus_units WHERE kind='word' AND active=1"))
            db.executemany('INSERT INTO lexical_links VALUES(?,?,?,?,?,?,?,1)',[(f'l{i}',r['id'],'x0',u['id'],sid,'','ordos') for i,r in enumerate(units)])
            db.execute('INSERT INTO dictionary_examples VALUES(?,?,?,1)',('ex','ordos',json.dumps(dict(ipa='',words=[],targets=[dict(lexeme_id='x0',usage_id=u['id'],sense_id=sid) for _ in range(80)]))))
            loads=json.loads;seen=[]
            def counting(value,*args,**kwargs):
                if value==raw:seen.append(value)
                return loads(value,*args,**kwargs)
            with patch.object(json,'loads',side_effect=counting):lexicon.validate_links(db)
            self.assertLess(len(seen),12)
            body['usages'][0]['senses']=[]
            db.execute("UPDATE lexemes SET body=? WHERE id='x0'",(json.dumps(body),))
            with self.assertRaisesRegex(ValueError,'义项'):lexicon.validate_links(db)

    def test_default_page_only_expands_its_rows_and_summary_preserves_selection_identity(self):
        self.seed()
        with server.connect(audit=False) as db,patch.object(dictionary_search,'SearchIndex',side_effect=AssertionError('empty filters must not index evidence')):
            spec=dict(field='all',case=False,combine='all',class_id='',conditions=[])
            with patch.object(dictionary_data,'resolve',wraps=dictionary_data.resolve) as resolve:
                full=lexicon.list_lexemes(db,'ordos',page=2,search=spec)
                self.assertEqual(resolve.call_count,30)
            statements=[];db.set_trace_callback(statements.append)
            brief=lexicon.list_lexemes(db,'ordos',page=2,search=spec,summary=True)
            self.assertLess(len(statements),10)
            self.assertEqual((brief['page'],brief['pages'],brief['total']),(2,5,123))
            self.assertEqual([(r['id'],r['revision'],r['headword']) for r in full['items']],[(r['id'],r['revision'],r['headword']) for r in brief['items']])
            self.assertEqual(brief['items'][0]['body']['usages'][0]['pos'],'名词')
            self.assertNotIn('notes',brief['items'][0]['body'])
            self.assertEqual(lexicon.list_lexemes(db,'ordos',ids_only=True),[r['id'] for r in lexicon.list_lexemes(db,'ordos',page_size='all')['items']])

    def test_legacy_homonyms_number_across_page_boundaries_and_languages(self):
        self.seed()
        with server.connect(audit=False) as db:
            body=json.dumps(lexicon.normalize({}))
            db.execute("INSERT INTO lexemes VALUES('peer','ordos','form-029',?,1)",(body,))
            a=lexicon.list_lexemes(db,'ordos',page=1,summary=True)['items'][-1]
            b=lexicon.list_lexemes(db,'ordos',page=2,summary=True)['items'][0]
            self.assertEqual([a['body']['homonym_number'],b['body']['homonym_number']],[1,2])
            self.assertEqual(a['body']['homonym_number'],lexicon.get_lexeme(db,a['id'])['body']['homonym_number'])
            self.assertEqual(b['body']['homonym_number'],lexicon.get_lexeme(db,b['id'])['body']['homonym_number'])
        self.assertEqual(self.call('/api/morphemes?'+urlencode({'search':'[]'}))[0],400)

    def test_catalog_discovery_matches_documents_without_constructing_them(self):
        self.seed()
        with server.connect(audit=False) as db:
            rows=[{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT * FROM lexemes')]
            eager=dictionary_search.SearchIndex(db,'ordos',rows)
            with patch.object(dictionary_search.SearchIndex,'document',side_effect=AssertionError('catalog should not flatten documents')):
                catalog=dictionary_search.catalog(db,'ordos')
            self.assertEqual({r['id'] for r in catalog['fields']},set(eager.fields)|{'all'})

    def test_scoped_morphology_contains_all_forward_and_reverse_relations(self):
        self.seed()
        with server.connect(audit=False) as db:
            def update(xid,change):
                b=json.loads(db.execute('SELECT body FROM lexemes WHERE id=?',(xid,)).fetchone()[0]);change(b);db.execute('UPDATE lexemes SET body=? WHERE id=?',(json.dumps(b),xid))
            update('x0',lambda b:b.update(relation={'type':'derivation','base_id':'x1'},word_structure={'analyses':[{'components':[{'lexeme_id':'x2'}]}]}))
            update('x3',lambda b:b.update(relation={'type':'stem','base_id':'x0'}))
            update('x4',lambda b:b.update(word_structure={'analyses':[{'components':[{'lexeme_id':'x0'}]}]}))
            data=morphology.options(db,'ordos','x0')
            self.assertEqual({r['id'] for r in data['entries']},{'x1','x2','x3','x4'})
            catalog=morphology.options(db,'ordos')['entries']
            self.assertEqual(len([r for r in catalog if r['target_kind']=='lexeme']),123)
            self.assertEqual(len([r for r in catalog if r['target_kind']=='morpheme']),123)
            with self.assertRaises(ValueError):morphology.options(db,'ordos','missing')
