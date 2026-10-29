import copy
import json
import unittest
import server
import test_classes


class EditingClassTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','undo','create'):
        locals()[name]=getattr(test_classes.ClassTests,name)

    def save(self,path,body):
        code,result=self.call('/api/'+path,body);self.assertEqual(code,200,result);return result

    def rows(self,kind='pos'):
        return [c for c in self.call('/api/classes?language=ordos')[1] if c['kind']==kind]

    def test_sibling_order_persists_undo_and_stale_rejected(self):
        a=self.create('甲');b=self.create('乙');child=self.create('子',parent_id=a['id'])
        payload=dict(kind='pos',items=[{'id':r['id'],'revision':r['revision']} for r in [b,a]])
        self.save('class-order',payload)
        self.assertEqual([r['id'] for r in self.rows() if not r['parent_id']],[b['id'],a['id']])
        self.assertEqual(self.call('/api/class-order',payload)[0],400)
        self.assertEqual(self.call('/api/class-order',{**payload,'items':[{'id':child['id'],'revision':1},payload['items'][0]]})[0],400)
        server.init();self.assertEqual([r['id'] for r in self.rows() if not r['parent_id']],[b['id'],a['id']])
        self.undo();self.assertEqual([r['id'] for r in self.rows() if not r['parent_id']],[a['id'],b['id']])
        self.undo('redo');self.assertEqual(self.rows()[0]['id'],b['id'])

    def test_order_language_exchange_and_semantic_nested_siblings(self):
        a=self.create('A');b=self.create('B');self.save('class-order',dict(kind='pos',items=[b,a]))
        parent=self.save('dict-org-class-save',dict(name='自然'))
        first=self.save('dict-org-class-save',dict(name='甲',parent_id=parent['id']))
        second=self.save('dict-org-class-save',dict(name='乙',parent_id=parent['id']))
        config=self.call('/api/dictionary-organization?language=ordos')[1]
        children=[r for r in config['classes'] if r['parent_id']==parent['id']]
        self.save('dict-org-class-order',dict(parent_id=parent['id'],items=list(reversed(children))))
        bundle=self.call('/api/export-language?language=ordos')[1]
        lid=self.save('save-language',dict(name='Copy',metadata={}))['id']
        self.save('import-language',dict(bundle=bundle,_language=lid))
        self.assertEqual([r['name'] for r in self.call('/api/classes?language='+lid)[1] if r['kind']=='pos'],['B','A'])
        imported=self.call('/api/dictionary-organization?lexical_language='+lid)[1]['classes']
        self.assertEqual([r['name'] for r in imported if r['parent_id']],['乙','甲'])

    def test_own_class_rename_rebases_editor_and_delete_keeps_meaning(self):
        parent=self.create('名词');child=self.create('方位',parent_id=parent['id'])
        x=self.save('lexeme-save',dict(headword='north',body={'usages':[{'id':'u','pos':'名词','subclass':'方位','senses':[{'id':'s','short_gloss':'北方'}]}]}))
        context=dict(editor_target_id=x['id'],editor_target_revision=x['revision'])
        r=self.save('class-save',{**parent,**context,'name':'N'})
        self.assertEqual(r['editor_before_revision'],x['revision']);fresh=r['editor_target']
        self.assertEqual(fresh['body']['usages'][0]['pos'],'N')
        self.assertGreater(fresh['revision'],x['revision'])
        parent=next(r for r in self.rows() if r['id']==parent['id'])
        r=self.save('class-delete',{**parent,'editor_target_id':x['id'],'editor_target_revision':fresh['revision']})
        u=r['editor_target']['body']['usages'][0]
        self.assertEqual((u['pos'],u['subclass']),('',''));self.assertEqual(u['senses'][0]['id'],'s')
        self.assertEqual(u['senses'][0]['short_gloss'],'北方');self.assertEqual({c['id'] for c in r['deleted_classes']},{parent['id'],child['id']})
        self.undo();self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['usages'][0]['pos'],'N')

    def test_stale_editor_is_never_rebased_over_an_independent_change(self):
        c=self.create('名词');x=self.save('lexeme-save',dict(headword='a',body={'usages':[{'pos':'名词'}]}))
        self.save('lexeme-save',{**x,'headword':'changed elsewhere'})
        result=self.save('class-save',{**c,'name':'N','editor_target_id':x['id'],'editor_target_revision':x['revision']})
        self.assertNotIn('editor_target',result)

    def test_form_and_usage_tag_delete_detach_native_and_word_and_undo(self):
        form=self.create('特殊形式','form');tag=self.create('可靠度','usage_tag');label={'type':'可靠度','value':'待核对','note':''}
        body={'tags':[label],'variants':[{'form':'a','kind':'特殊形式','tags':[label]}],'usages':[{'pos':'','senses':[{'short_gloss':'甲','tags':[label]}]}]}
        x=self.save('lexeme-save',dict(headword='x',body=body))
        m=self.save('morpheme-save',dict(form='m',body={'gloss':'乙','tags':[label],'senses':[{'gloss':'丙','tags':[label]}],'variants':[{'form':'n','kind':'特殊形式'}]}))
        self.save('class-delete',form)
        for endpoint,item in [('lexeme',x),('morpheme',m)]:
            fresh=self.call('/api/'+endpoint+'?id='+item['id'])[1]
            self.assertEqual(fresh['body']['variants'][0]['kind'],'')
            self.save(endpoint+'-save',fresh)
        self.save('class-delete',tag)
        for endpoint,item in [('lexeme',x),('morpheme',m)]:
            fresh=self.call('/api/'+endpoint+'?id='+item['id'])[1];self.assertEqual(fresh['body']['tags'],[])
            for sense in fresh['body'].get('senses',[]):self.assertEqual(sense['tags'],[])
        self.undo();self.assertEqual(self.call('/api/morpheme?id='+m['id'])[1]['body']['senses'][0]['tags'],[label])

    def test_grammar_category_delete_keeps_tag_and_feature_bindings(self):
        c=self.create('空间','grammar');tag=self.save('grammar-save',dict(symbol='LOC',category='空间'))
        x=self.save('lexeme-save',dict(headword='a',body={'features':[tag['id']]}))
        self.save('class-delete',c)
        self.assertEqual(self.call('/api/grammar-tags')[1][0]['category'],'')
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['features'],[tag['id']])
        self.undo();self.assertEqual(self.call('/api/grammar-tags')[1][0]['category'],'空间')

    def test_old_category_schema_is_backed_up_before_adding_order(self):
        self.create('Z');self.create('A')
        with server.connect(audit=False) as db:db.execute('ALTER TABLE category_classes DROP COLUMN position')
        server.init()
        self.assertEqual([r['name'] for r in self.rows()],['A','Z'])
        import sqlite3
        from contextlib import closing
        snapshots=list((server.DB.parent/'backups').glob('*.sqlite3'));self.assertTrue(snapshots)
        found=False
        for path in snapshots:
            with closing(sqlite3.connect(path)) as db:
                columns=[r[1] for r in db.execute('PRAGMA table_info(category_classes)')]
                if columns and 'position' not in columns:found=True
        self.assertTrue(found,'migration must retain a recoverable database with its old schema')

    def test_morph_class_delete_keeps_principal_parts_and_draft_can_save(self):
        c=self.create('第二类','morph')
        b={'word_structure':{'memberships':[{'id':'membership','class_id':c['id'],'title':'基本词形','parts':[{'id':'part','label':'过去时','form':'went','notes':'保留'}]}]}}
        x=self.save('lexeme-save',dict(headword='go',body=b))
        r=self.save('class-delete',{**c,'editor_target_id':x['id'],'editor_target_revision':x['revision']})
        member=r['editor_target']['body']['word_structure']['memberships'][0]
        self.assertEqual(member['class_id'],'');self.assertEqual(member['parts'][0]['id'],'part');self.assertEqual(member['parts'][0]['form'],'went')
        self.save('lexeme-save',r['editor_target'])
        bundle=self.call('/api/export-language?language=ordos')[1];lid=self.save('save-language',dict(name='Copy',metadata={}))['id']
        self.save('import-language',dict(bundle=bundle,_language=lid))
        copied=self.call('/api/lexemes?language='+lid)[1]['items'][0]['body']['word_structure']['memberships'][0]
        self.assertEqual(copied['class_id'],'');self.assertEqual(copied['parts'][0]['form'],'went')

    def test_semantic_rename_and_delete_return_only_their_own_editor_revision(self):
        c=self.save('dict-org-class-save',dict(name='空间'))
        x=self.save('lexeme-save',dict(headword='north',body={'semantic_classes':[c['id']]}))
        c=next(r for r in self.call('/api/dictionary-organization?language=ordos')[1]['classes'] if r['id']==c['id'])
        r=self.save('dict-org-class-delete',{**c,'children':'subtree','editor_target_id':x['id'],'editor_target_revision':x['revision']})
        self.assertEqual(r['editor_target']['body']['semantic_classes'],[])
        self.assertEqual(r['editor_before_revision'],x['revision'])
        self.assertGreater(r['editor_target']['revision'],x['revision'])
