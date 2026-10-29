import json
import unittest
import server
from pathlib import Path
from unittest.mock import patch
import test_sentence_dictionary as sd
from test_paradigms import body as paradigm_body


class DictionaryCopyTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','entry','undo'):
        locals()[name]=getattr(sd.SentenceDictionaryTests,name)

    def copy(self,x,kind='lexeme',**extra):
        return self.api('dictionary-copy',dict(id=x['id'],revision=x['revision'],kind=kind,confirmed=True,**extra))

    def test_paradigm_owned_ids_inheritance_new_date_and_one_undo(self):
        x=self.api('lexeme-save',dict(headword='go',body=paradigm_body()))
        before=self.api('undo-state')['generation'];y=self.copy(x)
        self.assertNotEqual(x['id'],y['id']);self.assertEqual(y['headword'],'go')
        self.assertEqual(self.api('undo-state')['generation'],before+1)
        self.assertNotEqual(x['body']['created_at'],y['body']['created_at'])
        u=y['body']['usages'][0];p=y['body']['paradigms'][0]
        self.assertNotEqual(u['id'],'verb');self.assertEqual(p['usage_id'],u['id'])
        r=p['rows'][0]['realizations'][0]
        self.assertEqual(r['form_id'],y['body']['variants'][0]['id'])
        self.assertEqual(r['meanings'][0]['base_sense_id'],u['senses'][0]['id'])
        self.assertEqual(self.api('lexeme?id='+x['id'])['body']['usages'][0]['id'],'verb')
        self.undo();self.assertEqual(self.call('/api/lexeme?id='+y['id'])[0],400)
        self.undo(True);self.assertEqual(self.api('lexeme?id='+y['id'])['body']['paradigms'],y['body']['paradigms'])

    def test_native_and_converted_morphemes_copy_without_incoming_links(self):
        for converted in (False,True):
            if converted:
                x=self.entry('root2','ROOT');plan=self.api('lexeme-to-morpheme-preview',x)
                x=self.api('lexeme-to-morpheme',dict(id=x['id'],revision=x['revision'],token=plan['token'],target_id='@new'))
            else:x=self.api('morpheme-save',dict(form='root1',body=dict(gloss='ROOT',senses=[dict(id='other',gloss='stem')],variants=[dict(id='v',form='roots')],notes='keep')))
            src=self.source('independent',[(x['form'],'ROOT')]);u=self.api('lexeme?id='+x['id'])['body']['usages'][0]
            self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',link_revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][-1]['id']))
            x=self.api('morpheme?id='+x['id']);y=self.copy(x,'morpheme')
            self.assertEqual(y['headword'],x['form']);self.assertNotEqual(y['id'],x['id'])
            if converted:self.assertEqual(y['body']['converted_from'],x['body']['converted_from'])
            self.assertEqual(self.api('lexeme-examples?id='+y['id'])['total'],0)
            self.assertEqual(self.api('dictionary-examples?id='+y['id']),[])
            self.assertEqual(self.detail(src)['body']['targets'][0]['lexeme_id'],x['id'])
            self.assertNotEqual(y['body']['variants'][0]['id'],x['body']['variants'][0]['id']) if x['body']['variants'] else None

    def test_shared_component_copy_preserves_target_and_external_form_identity(self):
        m=self.api('morpheme-save',dict(form='root',body=dict(gloss='ROOT',variants=[dict(id='shared-v',form='roots')])));
        x=self.entry('rootword','ROOT',word_structure=dict(analyses=[dict(id='analysis',components=[dict(id='component',form='roots',gloss='ROOT')])]))
        self.api('morpheme-assign',dict(lexeme_id=x['id'],lexeme_revision=x['revision'],components=[dict(analysis_id='analysis',component_id='component',revision=0)],morpheme_id=m['id'],morpheme_revision=m['revision'],form_id='shared-v'))
        x=self.api('lexeme?id='+x['id']);before_shared=self.api('morpheme?id='+m['id']);y=self.copy(x)
        self.assertGreater(self.api('morpheme?id='+m['id'])['revision'],before_shared['revision'])
        self.assertEqual(self.call('/api/morpheme-save',before_shared)[0],400)
        with server.connect(audit=False) as db:
            rows=list(db.execute('SELECT * FROM morpheme_components WHERE lexeme_id=?',(y['id'],)))
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['morpheme_id'],m['id'])
            self.assertEqual(json.loads(rows[0]['body'])['form_id'],'shared-v')
            self.assertEqual(rows[0]['analysis_id'],y['body']['word_structure']['analyses'][0]['id'])
        self.undo();self.undo(True)
        self.assertEqual(self.api('lexeme?id='+y['id'])['body']['word_structure'],y['body']['word_structure'])

    def test_stale_wrong_kind_language_and_missing_confirmation_are_atomic(self):
        x=self.entry('root','ROOT');other=self.api('save-language',dict(name='Other',metadata={}))['id']
        for extra in (dict(revision=0),dict(kind='morpheme'),dict(_language=other),dict(confirmed=False)):
            before=self.api('undo-state')['generation']
            status,_=self.call('/api/dictionary-copy',{**dict(id=x['id'],revision=x['revision'],kind='lexeme',confirmed=True),**extra})
            self.assertEqual(status,400);self.assertEqual(self.api('undo-state')['generation'],before)
            self.assertEqual(self.api('lexemes')['total'],1)

    def test_media_sense_relationships_and_backup_history_keep_separate_owners(self):
        import test_object_media
        from restore_backup import restore
        x=self.entry('recording','ROOT',variants=[dict(id='sound-form',form='recordings')]);peer=self.entry('peer','RELATED')
        sound=test_object_media.ObjectMediaTests.audio(self)
        status,value=test_object_media.ObjectMediaTests.add(self,x,sound,dict(target_id='sound-form',start_ms=100,end_ms=900))
        self.assertEqual(status,200,value)
        self.api('synonym-save',dict(source=dict(kind='lexeme',id=x['id'],sense=x['body']['usages'][0]['senses'][0]['id']),target=dict(kind='lexeme',id=peer['id'],sense=peer['body']['usages'][0]['senses'][0]['id'])))
        x=self.api('lexeme?id='+x['id']);y=self.copy(x)
        original=self.api('object-media?kind=lexeme&id='+x['id'])['items'][0]
        copied=self.api('object-media?kind=lexeme&id='+y['id'])['items'][0]
        self.assertEqual(copied['asset_id'],original['asset_id']);self.assertNotEqual(copied['id'],original['id'])
        self.assertEqual(copied['body']['target_id'],y['body']['variants'][0]['id'])
        with server.connect(audit=False) as db:
            rows=[json.loads(r[0]) for r in db.execute('SELECT body FROM synonym_links')]
            self.assertEqual(len(rows),2);self.assertTrue(any(any(e['id']==y['id'] for e in ends) for ends in rows))
        backup=Path(self.temp.name)/'copy.json';backup.write_text(json.dumps(self.api('backup')),encoding='utf-8')
        restored=Path(self.temp.name)/'restored.sqlite3';restore(backup,restored);server.DB=restored
        self.assertEqual(len(self.api('object-media?kind=lexeme&id='+y['id'])['items']),1)
        self.undo();self.assertEqual(self.call('/api/lexeme?id='+y['id'])[0],400)
        self.undo(True);self.assertEqual(len(self.api('object-media?kind=lexeme&id='+y['id'])['items']),1)

    def test_failure_after_insert_rolls_back_copy_and_homonym_renumbering(self):
        import lexicon
        x=self.entry('rollback','ROOT');before=self.api('undo-state')['generation'];real=lexicon.get_lexeme
        def fail(db,xid):
            if xid!=x['id']:raise ValueError('injected post-insert failure')
            return real(db,xid)
        with patch.object(lexicon,'get_lexeme',side_effect=fail):
            self.assertEqual(self.call('/api/dictionary-copy',dict(id=x['id'],revision=x['revision'],kind='lexeme',confirmed=True))[0],400)
        self.assertEqual(self.api('undo-state')['generation'],before);self.assertEqual(self.api('lexemes')['total'],1)
        self.assertEqual(self.api('lexeme?id='+x['id'])['body'],x['body'])
