import copy
import json
import unittest
from pathlib import Path
import test_lexicon
import server
import component_links
from restore_backup import restore


class ComponentLinkTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo

    def fixture(self):
        e=self.seed()
        body={'word_structure':{'analyses':[{'id':'a','title':'共时分析','level':'synchronic','status':'confirmed','components':[{'id':'c','form':'home','gloss':'家'}]},{'id':'b','title':'另一假说','components':[{'id':'d','form':'home','gloss':'另一解释'}]}]}}
        code,x=self.call('/api/lexeme-save',{'headword':'home-n','body':body});self.assertEqual(code,200,x)
        return e,x

    def link(self,e,x,selection=True,whole=False):
        uid=e['words'][0]['unit_id'] if whole else e['words'][0]['morphemes'][0]['unit_id']
        u=self.call('/api/unit-dictionary?id='+uid)[1]
        b=dict(unit_id=uid,unit_revision=u['revision'],entry_revision=u['entry_revision'],revision=u['link'].get('revision',0),lexeme_id=x['id'],lexeme_revision=x['revision'])
        if selection is not True:b['component_selection']=selection
        else:b['component_selection']={'analysis_id':'a','component_id':'c'}
        return self.call('/api/lexeme-link',b)

    def test_changed_deleted_components_stay_reviewable_and_undo_restores(self):
        e,x=self.fixture();self.assertEqual(self.link(e,x)[0],200)
        uid=e['words'][0]['morphemes'][0]['unit_id']
        old=self.call('/api/unit-dictionary?id='+uid)[1]['link']['component_ref']
        x['body']['word_structure']['analyses'][0]['components'][0]['gloss']='住所'
        code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x)
        link=self.call('/api/unit-dictionary?id='+uid)[1]['link'];self.assertTrue(link['component_review']);self.assertEqual(link['component_ref'],old)
        self.assertTrue(self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]['needs_review'])
        self.assertEqual(self.undo()[0],200)
        self.assertFalse(self.call('/api/unit-dictionary?id='+uid)[1]['link']['component_review'])
        x=self.call('/api/lexeme?id='+x['id'])[1];x['body']['word_structure']['analyses']=[]
        code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x)
        self.assertTrue(self.call('/api/unit-dictionary?id='+uid)[1]['link']['component_review'])
        self.assertEqual(self.link(e,x)[0],400)
        self.assertEqual(self.link(e,x,None)[0],200)
        self.assertIsNone(self.call('/api/unit-dictionary?id='+uid)[1]['link']['component_ref'])

    def test_invalid_pair_whole_word_and_stale_revision_rejected(self):
        e,x=self.fixture()
        self.assertEqual(self.link(e,x,{'analysis_id':'a','component_id':'d'})[0],400)
        self.assertEqual(self.link(e,x,whole=True)[0],400)
        before=copy.deepcopy(x);x['body']['notes']='changed';self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        self.assertEqual(self.link(e,before)[0],400)

    def test_independent_component_preserved_by_editor_and_language_exchange(self):
        _,x=self.fixture()
        code,e=self.call('/api/example-save',{'body':{'words':[{'form':'home-n','gloss':'家-GEN'}],'targets':[]}});self.assertEqual(code,200,e)
        d=self.call('/api/segmentation?kind=independent&id='+e['id'])[1]
        b=dict(kind='independent',id=e['id'],revision=d['revision'],word=0,key=d['body']['words'][0]['morphemes'][0]['key'],lexeme_id=x['id'],lexeme_revision=x['revision'],component_selection={'analysis_id':'a','component_id':'c'})
        self.assertEqual(self.call('/api/segmentation-link',b)[0],200)
        fresh=self.call('/api/dictionary-examples?id='+x['id'])[1][0];ref=fresh['body']['targets'][0]['component_ref']
        fresh['body']['notes']='编辑备注';self.assertEqual(self.call('/api/example-save',fresh)[0],200)
        self.assertEqual(self.call('/api/dictionary-examples?id='+x['id'])[1][0]['body']['targets'][0]['component_ref'],ref)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',{'name':'Copy','metadata':{}})[1]['id']
        code,r=self.call('/api/import-language',{'_language':other,'bundle':bundle});self.assertEqual(code,200,r)
        with server.connect() as db:
            row=db.execute('SELECT body FROM dictionary_examples WHERE language_id=?',(other,)).fetchone();t=json.loads(row[0])['targets'][0]
            body=json.loads(db.execute('SELECT body FROM lexemes WHERE id=?',(t['lexeme_id'],)).fetchone()[0])
            self.assertFalse(component_links.review(body,t['component_ref']))

    def test_corpus_export_and_backup_restore(self):
        e,x=self.fixture();self.assertEqual(self.link(e,x)[0],200)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',{'name':'Copy','metadata':{}})[1]['id']
        code,r=self.call('/api/import-language',{'_language':other,'bundle':bundle});self.assertEqual(code,200,r)
        with server.connect() as db:
            rows=db.execute('SELECT c.body,x.body FROM component_links c JOIN lexical_links l ON c.id=l.id JOIN lexemes x ON x.id=l.lexeme_id').fetchall()
            self.assertEqual(len(rows),2)
            for ref,body in rows:self.assertFalse(component_links.review(json.loads(body),json.loads(ref)))
        backup=self.call('/api/backup')[1];src=Path(self.temp.name)/'backup.json';src.write_text(json.dumps(backup),encoding='utf-8')
        target=Path(self.temp.name)/'restored.sqlite3';restore(src,target)
        import sqlite3
        db=sqlite3.connect(target)
        try:self.assertEqual(db.execute('SELECT count(*) FROM component_links').fetchone()[0],2)
        finally:db.close()

    def test_copy_and_transfer_preserve_component_evidence(self):
        e,x=self.fixture();self.assertEqual(self.link(e,x)[0],200)
        code,r=self.call('/api/duplicate-entry',dict(id=e['id'],text_id=e['text_id'],revision=e['revision'],order=[v['id'] for v in self.entries()],where='end'))
        self.assertEqual(code,200,r)
        with server.connect() as db:
            refs=[json.loads(v[0]) for v in db.execute('SELECT body FROM component_links')]
            self.assertEqual(len(refs),2);self.assertEqual(refs[0],refs[1])
        target=self.call('/api/add',{'text_id':e['text_id']})[1]
        a=self.call('/api/word-transfer-snapshot?kind=corpus&id='+e['id'])[1]
        z=self.call('/api/word-transfer-snapshot?kind=corpus&id='+target['id'])[1]
        code,r=self.call('/api/word-transfer',dict(source=dict(kind='corpus',id=e['id'],token=a['transfer_token']),target=dict(kind='corpus',id=target['id'],token=z['transfer_token']),slots=[a['words'][0]['id']],mode='move',confirmed=True,position=0))
        self.assertEqual(code,200,r)
        with server.connect() as db:
            rows=db.execute('SELECT c.body FROM component_links c JOIN lexical_links l ON l.id=c.id JOIN corpus_units u ON u.id=l.unit_id WHERE u.entry_id=?',(target['id'],)).fetchall()
            self.assertEqual(len(rows),1);self.assertEqual(json.loads(rows[0][0]),refs[0])

    def test_legacy_target_change_clears_component_and_invalid_evidence_rejected(self):
        e,x=self.fixture();self.assertEqual(self.link(e,x)[0],200)
        uid=e['words'][0]['morphemes'][0]['unit_id']
        y=self.call('/api/lexeme-save',{'headword':'other','body':{}})[1]
        u=self.call('/api/unit-dictionary?id='+uid)[1]
        code,r=self.call('/api/lexeme-link',dict(unit_id=uid,unit_revision=u['revision'],entry_revision=u['entry_revision'],revision=u['link']['revision'],lexeme_id=y['id'],lexeme_revision=y['revision']))
        self.assertEqual(code,200,r)
        self.assertIsNone(self.call('/api/unit-dictionary?id='+uid)[1]['link']['component_ref'])
        with self.assertRaises(ValueError):component_links.validate({'analysis_id':'a','component_id':'c','snapshot':{}})
