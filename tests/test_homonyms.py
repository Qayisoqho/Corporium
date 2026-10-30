import unittest
import json
from pathlib import Path
from urllib.parse import urlencode
import test_server
import test_lexicon
import server
from restore_backup import restore

class HomonymTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    undo=test_lexicon.LexiconTests.undo

    def preview(self,form='bank',lid='ordos',exclude=''):
        return self.call('/api/homonym-preview?'+urlencode(dict(form=form,language=lid,exclude=exclude)))[1]

    def create(self,form='bank',lid='ordos',num=None):
        b=dict(headword=form,body=dict(homonym_number=num),_language=lid,homonym_confirmation=self.preview(form,lid)['token'])
        code,x=self.call('/api/lexeme-save',b);self.assertEqual(code,200,x);return x

    def get(self,x):return self.call('/api/lexeme?id='+x['id'])[1]

    def test_confirmation_numbering_undo_and_collision(self):
        a=self.create();self.assertIsNone(a['body']['homonym_number'])
        self.assertEqual(self.call('/api/lexeme-save',dict(headword='bank',body={}))[0],400)
        self.assertIsNone(self.get(a)['body']['homonym_number'])
        b=self.create();self.assertEqual(self.get(a)['body']['homonym_number'],1);self.assertEqual(b['body']['homonym_number'],2)
        self.assertEqual(self.undo()[0],200);self.assertIsNone(self.get(a)['body']['homonym_number'])
        self.assertEqual(self.undo('redo')[0],200)
        a=self.get(a);b=self.get(b);b['body']['homonym_number']=1
        self.assertEqual(self.call('/api/lexeme-save',b)[0],400)
        b['body']['homonym_number']=7;self.assertEqual(self.call('/api/lexeme-save',b)[0],200)
        self.assertEqual(self.create()['body']['homonym_number'],2)
        self.assertEqual(self.call('/api/lexeme-save',a)[0],200)

    def test_stale_confirmation_and_language_scope(self):
        a=self.create();plan=self.preview();self.create()
        self.assertEqual(self.call('/api/lexeme-save',dict(headword='bank',body={},homonym_confirmation=plan['token']))[0],400)
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.assertIsNone(self.create(lid=other)['body']['homonym_number'])
        self.assertIsNone(self.create(form='Bank')['body']['homonym_number'])

    def test_rename_requires_confirmation_and_preserves_links(self):
        a=self.create();b=self.create('other');b['headword']='bank'
        self.assertEqual(self.call('/api/lexeme-save',b)[0],400)
        b['homonym_confirmation']=self.preview(exclude=b['id'])['token']
        self.assertEqual(self.call('/api/lexeme-save',b)[0],200)
        self.assertEqual(self.get(a)['body']['homonym_number'],1)
        self.assertEqual(self.get(b)['body']['homonym_number'],2)

    def test_exchange_restore_and_number_validation(self):
        a=self.create(num=4);self.create(num=9)
        for invalid in (0,-1,1.5,True,'x'):
            a=self.get(a);a['body']['homonym_number']=invalid
            self.assertEqual(self.call('/api/lexeme-save',a)[0],400)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',dict(name='Copy',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/import-language',dict(_language=other,bundle=bundle))[0],200)
        nums=sorted(x['body']['homonym_number'] for x in self.call('/api/lexemes?language='+other)[1]['items'])
        self.assertEqual(nums,[4,9])
        p=Path(self.temp.name)/'backup.json';p.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8')
        dest=Path(self.temp.name)/'restored.sqlite3';restore(p,dest);server.DB=dest
        self.assertEqual(self.get(a)['body']['homonym_number'],4)

    def test_legacy_singleton_number_clears_when_sibling_deleted(self):
        a=self.create();b=self.create()
        with server.connect() as db:
            for x in (a,b):
                body=json.loads(db.execute('SELECT body FROM lexemes WHERE id=?',(x['id'],)).fetchone()[0]);body.pop('homonym_number',None)
                db.execute('UPDATE lexemes SET body=? WHERE id=?',(json.dumps(body),x['id']))
        a=self.get(a);b=self.get(b)
        self.assertEqual(b['body']['homonym_number'],2)
        self.assertEqual(self.call('/api/lexeme-delete',dict(id=a['id'],revision=a['revision'],confirmed=True))[0],200)
        self.assertIsNone(self.get(b)['body']['homonym_number'])

    def test_delete_clears_remaining_number_in_detail_lists_and_undo_redo(self):
        a=self.create(num=4);b=self.create(num=9)
        self.assertEqual(self.call('/api/lexeme-delete',dict(id=b['id'],revision=b['revision'],confirmed=True))[0],200)
        self.assertIsNone(self.get(a)['body']['homonym_number'])
        for query in ('','&summary=true','&q=bank'):
            items=self.call('/api/lexemes?language=ordos'+query)[1]['items']
            self.assertIsNone(next(x for x in items if x['id']==a['id'])['body']['homonym_number'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.get(a)['body']['homonym_number'],4);self.assertEqual(self.get(b)['body']['homonym_number'],9)
        self.assertEqual(self.undo('redo')[0],200);self.assertIsNone(self.get(a)['body']['homonym_number'])

    def test_delete_from_three_preserves_remaining_numbers_and_other_groups(self):
        a=self.create();b=self.create();c=self.create()
        other=self.create('Bank',num=6)
        self.assertEqual(self.call('/api/lexeme-delete',dict(id=c['id'],revision=c['revision'],confirmed=True))[0],200)
        self.assertEqual(self.get(a)['body']['homonym_number'],1);self.assertEqual(self.get(b)['body']['homonym_number'],2)
        self.assertEqual(self.get(other)['body']['homonym_number'],6)

    def test_rename_clears_old_group_and_undo_restores_numbers(self):
        a=self.create();b=self.create();b=self.get(b);b['headword']='new-form'
        code,result=self.call('/api/lexeme-save',b);self.assertEqual(code,200,result)
        self.assertIsNone(result['body']['homonym_number'])
        self.assertIsNone(self.get(a)['body']['homonym_number'])
        self.undo()
        self.assertEqual(self.get(a)['body']['homonym_number'],1)
        self.assertEqual(self.get(b)['body']['homonym_number'],2)
        self.undo('redo');self.assertIsNone(self.get(a)['body']['homonym_number'])

    def test_rename_into_another_group_assigns_new_number(self):
        a=self.create();b=self.create();c=self.create('target');d=self.create('target')
        b=self.get(b);b['headword']='target';b['homonym_confirmation']=self.preview('target',exclude=b['id'])['token']
        code,result=self.call('/api/lexeme-save',b);self.assertEqual(code,200,result)
        self.assertEqual(result['body']['homonym_number'],3)
        self.assertIsNone(self.get(a)['body']['homonym_number'])
