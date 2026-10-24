import json
import unittest
from pathlib import Path
from urllib.parse import urlencode
import server
import dictionary_organization as org
import test_lexicon
from restore_backup import restore

class OrganizationTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    undo=test_lexicon.LexiconTests.undo

    def action(self,action,**b):
        code,r=self.call('/api/dict-org-'+action,b);self.assertEqual(code,200,r);return r

    def word(self,name,ids=()):
        code,r=self.call('/api/lexeme-save',{'headword':name,'body':{'semantic_classes':list(ids)}});self.assertEqual(code,200,r);return r

    def test_sort_longest_unicode_prefix_and_unlisted(self):
        key=org.sort_key('b g a')
        self.assertEqual(sorted(['gba','bag','bga','ba','x'],key=key),['bga','ba','bag','gba','x'])
        self.assertEqual(sorted(['ca','cha','ch','b'],key=org.sort_key('ch b c a')),['ch','cha','b','ca'])
        self.assertEqual(org.sort_key('é')("e\u0301"),org.sort_key('é')('é'))
        with self.assertRaises(ValueError):org.sort_key('a A')
        self.assertNotEqual(org.sort_key('A a',True)('A'),org.sort_key('A a',True)('a'))
        self.assertEqual(len(org.alphabet(' '.join('unit'+str(n) for n in range(15000)))),15000)

    def test_tree_assign_filter_move_delete_and_undo(self):
        root=self.action('class-save',name='自然');child=self.action('class-save',name='动物',parent_id=root['id']);leaf=self.action('class-save',name='鸟',parent_id=child['id'])
        w=self.word('bird',[leaf['id']]);self.word('stone')
        rows=self.call('/api/lexemes?'+urlencode({'language':'ordos','semantic_class':root['id']}))[1]
        self.assertEqual([x['id'] for x in rows['items']],[w['id']])
        self.assertEqual(self.call('/api/dict-org-class-save',{**root,'parent_id':leaf['id']})[0],400)
        self.action('class-delete',**child,children='promote')
        data=self.call('/api/dictionary-organization?language=ordos')[1]
        self.assertEqual(next(x for x in data['classes'] if x['id']==leaf['id'])['parent_id'],root['id'])
        self.assertEqual(self.undo()[0],200)
        self.action('class-delete',**root,children='subtree')
        self.assertEqual(self.call('/api/lexeme?id='+w['id'])[1]['body']['semantic_classes'],[])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/lexeme?id='+w['id'])[1]['body']['semantic_classes'],[leaf['id']])

    def test_batch_stale_failure_rolls_back_and_cross_language_rejected(self):
        c=self.action('class-save',name='类');a=self.word('a');b=self.word('b')
        bad={'items':[{'id':a['id'],'revision':a['revision']},{'id':b['id'],'revision':999}],'classes':[c['id']]}
        self.assertEqual(self.call('/api/dict-org-assign',bad)[0],400)
        self.assertEqual(self.call('/api/lexeme?id='+a['id'])[1]['body']['semantic_classes'],[])
        self.action('assign',items=[{'id':a['id'],'revision':a['revision']}],classes=[c['id']],mode='add')
        self.assertEqual(self.undo()[0],200)
        other=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id']
        self.assertEqual(self.call('/api/dict-org-class-save',{**c,'_language':other})[0],400)
        self.assertEqual(self.call('/api/lexeme-save',{'headword':'foreign','body':{'semantic_classes':[c['id']]},'_language':other})[0],400)

    def test_order_crud_preview_language_and_pagination(self):
        for w in ['gba','bag','bga']+[f'z{n}' for n in range(12)]:self.word(w)
        rule=self.action('order-save',name='测试',alphabet='b g a')
        url='/api/lexemes?'+urlencode({'language':'ordos','sort_order':rule['id'],'page_size':10})
        result=self.call(url)[1];self.assertEqual([r['headword'] for r in result['items'][:3]],['bga','bag','gba']);self.assertEqual(result['pages'],2)
        self.assertEqual(self.action('preview',alphabet='b g a')['items'][0]['headword'],'bga')
        copy=self.action('order-copy',id=rule['id'],revision=rule['revision'],name='副本');self.assertNotEqual(copy['id'],rule['id'])
        self.action('order-save',**{**copy,'alphabet':'a b g'})
        self.action('order-delete',**rule);self.assertEqual(self.undo()[0],200)
        other=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id']
        self.assertEqual(self.call('/api/lexemes?'+urlencode({'language':other,'sort_order':rule['id']}))[0],400)

    def test_language_export_import_and_full_backup(self):
        c=self.action('class-save',name='自然');child=self.action('class-save',name='动物',parent_id=c['id']);w=self.word('bird',[child['id']]);self.action('order-save',name='顺序',alphabet='b a')
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',{'name':'Copy','metadata':{}})[1]['id']
        code,result=self.call('/api/import-language',{'_language':other,'bundle':bundle});self.assertEqual(code,200,result)
        config=self.call('/api/dictionary-organization?language='+other)[1]
        self.assertEqual(len(config['classes']),2);self.assertEqual(config['orders'][0]['alphabet'],'b a')
        imported=self.call('/api/lexemes?language='+other)[1]['items'][0]
        self.assertIn(imported['body']['semantic_classes'][0],{x['id'] for x in config['classes']});self.assertNotEqual(imported['body']['semantic_classes'],w['body']['semantic_classes'])
        backup=self.call('/api/backup')[1];path=Path(self.temp.name)/'org.json';path.write_text(json.dumps(backup),encoding='utf-8');target=Path(self.temp.name)/'restored-org.sqlite3';restore(path,target)
        old=server.DB
        try:
            server.DB=target
            self.assertEqual(self.call('/api/dictionary-organization?language='+other)[1],config)
        finally:server.DB=old
