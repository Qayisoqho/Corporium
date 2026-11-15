import source_fixtures
import json
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

import annotations
import dictionary_rows
import gloss_inheritance
import lexicon
import server
import test_server
from corpus import analyze


class RelationalReadTests(unittest.TestCase):
    maxDiff = None
    setUp = test_server.APITests.setUp
    tearDown = test_server.APITests.tearDown
    call = test_server.APITests.call

    def api(self, route, payload=None):
        status, body = self.call('/api/'+route, payload)
        self.assertEqual(status, 200, body)
        return body

    def target(self):
        return self.api('lexeme-save', dict(headword='mala', body=dict(
            usages=[dict(id='u', pos='N', senses=[dict(id='s', short_gloss='石')])],
            variants=[dict(id='v', form='malaŋ', variation='unknown', kind='other')])))

    def link(self, kind, rid, target):
        detail = self.api('segmentation?kind='+kind+'&id='+rid)
        self.api('segmentation-link', dict(kind=kind,id=rid,revision=detail['revision'],
            word=0,key='@word',lexeme_id=target['id'],lexeme_revision=target['revision'],
            usage_id='u',sense_id='s',link_revision=0))

    def test_pages_assemble_the_same_display_without_decoding_the_sentence(self):
        target = self.target()
        self.api('layer-save', dict(name='词类',font='Junicode',source='dictionary',dictionary_field='pos'))
        corpus = self.api('import', dict(title='Corpus',content='#pass([mala], (([mala],[旧]),), [文本翻译])'))
        entry = self.api('entries?text='+corpus['id'])['items'][0]['id']
        example = self.api('example-save', dict(body=dict(original='独立原文',ipa='mala',translation='独立翻译',
            words=[dict(form='mala',gloss='旧')])))['id']
        self.link('corpus',entry,target)
        self.link('independent',example,target)
        with server.connect(audit=False) as db:
            raw = [db.execute('SELECT body FROM '+table+'_documents WHERE id=?',(rid,)).fetchone()[0]
                   for table,rid in [('entries',entry),('dictionary_examples',example)]]
            expected_corpus = annotations.enrich(db,analyze(gloss_inheritance.load(db,'corpus',entry,raw[0])),'corpus',entry)
            detail = annotations.get(db,'independent',example)
            expected_independent = annotations.enrich(db,detail['body'],'independent',example,snapshot=detail)
        loads = json.loads
        def reject_whole_body(value, *args, **kwargs):
            self.assertNotIn(value,raw,'Evidence page decoded a complete sentence source')
            return loads(value,*args,**kwargs)
        with patch('json.loads',side_effect=reject_whole_body):
            current = self.api('lexeme-examples?id='+target['id'])
            standalone = self.api('dictionary-examples?paged=1&id='+target['id'])
        self.assertEqual(current['items'][0]['entry'],expected_corpus)
        self.assertEqual(standalone['items'][0]['body'],expected_independent)
        self.assertEqual(standalone['items'][0]['body']['words'][0]['extra_layers'][0]['value'],'N')

        revised=self.api('independent-example?id='+example)
        revised['body']['translation']='新翻译'
        self.api('example-save',revised)
        self.assertEqual(self.api('dictionary-examples?paged=1&id='+target['id'])['items'][0]['body']['translation'],'新翻译')
        self.api('undo',dict(generation=self.api('undo-state')['generation']))
        self.assertEqual(self.api('dictionary-examples?paged=1&id='+target['id'])['items'][0]['body']['translation'],'独立翻译')

    def test_dictionary_values_preserve_nested_order_and_types_and_invalidate_on_edit(self):
        target = self.target()
        xid = target['id']
        with server.connect(audit=False) as db:
            stored=json.loads(db.execute('SELECT body FROM lexemes_documents WHERE id=?',(xid,)).fetchone()[0])
            stored['test_values']={'标记':[None,False,True,0,3.25,10**30,[],{},['a','b']]}
            source_fixtures.replace(db,'lexemes',xid,json.dumps(stored,ensure_ascii=False))
        with server.connect(audit=False) as db:
            self.assertEqual(dictionary_rows.raw_bodies(db,'lexeme',[xid])[xid],stored)
        with server.connect(audit=False) as db:
            statements=[]
            db.set_trace_callback(statements.append)
            self.assertEqual(dictionary_rows.raw_bodies(db,'lexeme',[xid])[xid],stored)
            self.assertFalse(any('json_tree(' in statement for statement in statements))
        edited=self.api('lexeme?id='+xid)
        self.assertEqual(edited['body']['test_values'],stored['test_values'])
        edited['body']['variants'][0]['form']='malaj'
        self.api('lexeme-save',edited)
        self.assertEqual(self.api('lexeme?id='+xid)['body']['variants'][0]['form'],'malaj')
        self.api('undo',dict(generation=self.api('undo-state')['generation']))
        self.assertEqual(self.api('lexeme?id='+xid)['body']['variants'][0]['form'],'malaŋ')

    def test_unprepared_read_only_snapshot_keeps_the_same_values(self):
        from pathlib import Path
        server.DB=Path(self.temp.name)/'legacy-readonly.sqlite3'
        server.init(source_mode='legacy')
        target=self.target()
        xid=target['id']
        with closing(sqlite3.connect(server.DB.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            values=dictionary_rows.raw_bodies(db,'lexeme',[xid])[xid]
            self.assertEqual(values,json.loads(db.execute('SELECT body FROM lexemes WHERE id=?',(xid,)).fetchone()[0]))

    def test_old_corpus_order_keys_prepare_only_referenced_sentences(self):
        from pathlib import Path
        server.DB=Path(self.temp.name)/'legacy-order.sqlite3'
        server.init(source_mode='legacy')
        target=self.target()
        text=self.api('import',dict(title='Old corpus',content=
            '#pass([mala], (([mala],[旧]),), [引用])\n#pass([other], (([other],[词]),), [未引用])'))
        entries=self.api('entries?text='+text['id'])['items']
        self.link('corpus',entries[0]['id'],target)
        with server.connect(audit=False) as db:
            db.execute('DELETE FROM corpus_sentence_keys')
        with closing(sqlite3.connect(server.DB.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            self.assertEqual(lexicon.occurrence_count(db,target['id']),1)
            self.assertEqual(db.execute('SELECT count(*) FROM corpus_sentence_keys').fetchone()[0],0)
        page=self.api('lexeme-examples?id='+target['id'])
        self.assertEqual(page['occurrences'],1)
        self.assertEqual(page['items'][0]['entry_id'],entries[0]['id'])
        with server.connect(audit=False) as db:
            self.assertEqual([r[0] for r in db.execute('SELECT id FROM corpus_sentence_keys')],[entries[0]['id']])
