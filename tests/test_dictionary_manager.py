import source_fixtures
import json
from pathlib import Path
import test_lexicon
import unittest
import test_server
import server
from restore_backup import restore

class DictionaryManagerTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    word=test_lexicon.LexiconTests.word
    undo=test_lexicon.LexiconTests.undo

    def writing(self,name='IPA',font='IPAPANNEW',adopt=False):
        code,t=self.call('/api/writing-save',dict(name=name,font=font,position=0,adopt=adopt))
        self.assertEqual(code,200,t);return t

    def example(self,x,others=[]):
        u=x['body']['usages'][0]
        body=dict(original='Example',ipa='ipa',translation='翻译',source='调查笔记',words=[dict(form='home',gloss='家')],targets=[dict(lexeme_id=x['id'],usage_id=u['id'],sense_id=u['senses'][0]['id'])]+[dict(lexeme_id=o['id']) for o in others])
        code,e=self.call('/api/example-save',dict(body=body));self.assertEqual(code,200,e);return e

    def test_writing_adopt_update_delete_reassign_undo(self):
        x=self.word();x['body']['orthographies']=[dict(label='IPA',text='abc',font='Junicode')]
        self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        self.assertEqual(self.call('/api/writing-types?language=ordos')[1]['legacy'][0]['count'],1)
        t=self.writing(adopt=True)
        current=lambda:self.call('/api/lexeme?id='+x['id'])[1]['body']['orthographies'][0]
        self.assertEqual(current()['type_id'],t['id']);self.assertEqual(current()['font'],'IPAPANNEW')
        code,t=self.call('/api/writing-save',{**t,'name':'本地转写','font':'Junicode'});self.assertEqual(code,200)
        self.assertEqual(current()['label'],'本地转写')
        self.assertEqual(self.call('/api/writing-delete',{**t,'confirmed':True})[0],400)
        other=self.writing(name='Latin',font='serif')
        self.assertEqual(self.call('/api/writing-delete',{**t,'replacement_id':other['id'],'confirmed':True})[0],200)
        self.assertEqual(current()['type_id'],other['id'])
        self.assertEqual(self.undo()[0],200);self.assertEqual(current()['type_id'],t['id'])

    def test_examples_multi_reference_edit_delete_and_undo(self):
        x=self.word();y=self.word();e=self.example(x,[y])
        self.assertEqual(len(self.call('/api/dictionary-examples?id='+y['id'])[1]),1)
        e['body']['translation']='更新翻译'
        code,saved=self.call('/api/example-save',e);self.assertEqual(code,200)
        self.assertEqual(self.call('/api/example-save',e)[0],400)
        self.assertEqual(self.call('/api/lexeme-delete',{**x,'confirmed':True})[0],400)
        self.assertEqual(self.call('/api/example-delete',saved)[0],400)
        self.assertEqual(self.call('/api/example-delete',{**saved,'confirmed':True})[0],200)
        self.assertEqual(self.call('/api/dictionary-examples?id='+x['id'])[1],[])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/dictionary-examples?id='+x['id'])[1][0]['body']['translation'],'更新翻译')

    def test_dictionary_exchange_and_backup(self):
        x=self.word();t=self.writing();x['body']['orthographies']=[dict(label='IPA',text='həʊm',font='IPAPANNEW',type_id=t['id'])]
        self.assertEqual(self.call('/api/lexeme-save',x)[0],200);self.example(x)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',{'name':'Copy','metadata':{}})[1]['id']
        code,r=self.call('/api/import-language',dict(_language=other,bundle=bundle));self.assertEqual(code,200,r)
        copy=self.call('/api/lexemes?language='+other)[1]['items'][0]
        self.assertNotEqual(copy['body']['orthographies'][0]['type_id'],t['id'])
        example=self.call('/api/dictionary-examples?id='+copy['id'])[1][0]
        self.assertEqual(example['body']['targets'][0]['lexeme_id'],copy['id'])
        self.assertEqual(example['body']['targets'][0]['sense_id'],copy['body']['usages'][0]['senses'][0]['id'])
        path=Path(self.temp.name)/'full.json';path.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8')
        dest=Path(self.temp.name)/'restored.sqlite3';restore(path,dest);server.DB=dest
        self.assertEqual(self.call('/api/dictionary-examples?id='+copy['id'])[1][0]['body']['source'],'调查笔记')
        self.assertEqual(self.undo(language=other)[0],200)
        self.assertEqual(self.call('/api/lexemes?language='+other)[1]['total'],0)

    def test_cross_language_and_invalid_references(self):
        x=self.word();other=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id'];t=self.writing()
        code,y=self.call('/api/lexeme-save',dict(_language=other,headword='other',body=dict(orthographies=[dict(type_id=t['id'],label='IPA',text='a',font='serif')])));self.assertEqual(code,400)
        self.assertEqual(self.call('/api/example-save',dict(_language=other,body=dict(original='x',targets=[dict(lexeme_id=x['id'])])))[0],400)
        self.assertEqual(self.call('/api/example-save',dict(body=dict(original='x',targets=[dict(lexeme_id=x['id'],sense_id='missing')])))[0],400)

    def test_paged_evidence_matches_legacy_order_filters_focus_and_page_clamp(self):
        x=self.word();e=self.example(x)
        with server.connect(audit=False) as db:
            for i in range(24):
                body=json.loads(json.dumps(e['body']))
                body['targets'][0]['form_id']='variant' if i%2 else ''
                body['targets'].append(dict(body['targets'][0]))
                source_fixtures.seed(db,'dictionary_examples',('id', 'language_id', 'body', 'revision'),('paged-'+str(i), 'ordos', json.dumps(body), 1))
        base='/api/dictionary-examples?id='+x['id']
        legacy=self.call(base)[1]
        second=self.call(base+'&paged=1&page=999')[1]
        self.assertEqual((second['total'],second['page'],second['pages']),(25,2,2))
        self.assertEqual(second['items'],legacy[20:])
        self.assertEqual(self.call(base+'&paged=1&focus=paged-23')[1]['items'],legacy[20:])
        self.assertFalse(self.call(base+'&paged=1&focus=missing')[1]['focus_found'])
        for form in ('variant','unassigned'):
            result=self.call(base+'&paged=1&form_id='+form)[1]
            wanted=[item for item in legacy if any((t.get('form_id') or 'unassigned')==form for t in item['body']['targets'] if t['lexeme_id']==x['id'])]
            self.assertEqual(result['items'],wanted)
            self.assertEqual(result['total'],len(wanted))
        self.assertFalse(self.call(base+'&paged=1&form_id=variant&focus=paged-0')[1]['focus_found'])
