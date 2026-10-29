import copy
import json
import unittest
from pathlib import Path
import server
import test_lexicon
from restore_backup import restore


class WordStructureTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    undo=test_lexicon.LexiconTests.undo

    def save(self,form,body=None,old=None):
        payload={**(old or {}),'headword':form,'body':body or {}}
        code,result=self.call('/api/lexeme-save',payload);self.assertEqual(code,200,result);return result

    def get(self,x):return self.call('/api/lexeme?id='+x['id'])[1]

    def setup_structure(self):
        code,c=self.call('/api/class-save',{'name':'第二变位法','kind':'morph','notes':'共同说明','template':{'title':'基本词形','slots':[{'label':s} for s in ['现在时','不定式','完成时','分词']]}});self.assertEqual(code,200,c)
        cls=next(c1 for c1 in self.call('/api/classes?language=ordos')[1] if c1['id']==c['id'])
        code,w=self.call('/api/writing-save',{'name':'IPA','font':'IPAPANNEW'});self.assertEqual(code,200,w)
        code,t=self.call('/api/grammar-save',{'symbol':'PST'});self.assertEqual(code,200,t)
        root=self.save('root',{'usages':[{'pos':'名词','senses':[{'short_gloss':'根'}]}],'variants':[{'form':'r','kind':'allomorph'}]})
        u=root['body']['usages'][0]
        data={'memberships':[{'class_id':cls['id'],'title':'我的基本词形','notes':'例外说明','parts':[{'label':'现在时','form':'word','features':[t['id']],'writings':[{'type_id':w['id'],'text':'wɜːd'}]}]}],
              'analyses':[{'id':'a','title':'复合与派生','level':'synchronic','status':'confirmed','default':True,'source':'调查','notes':'研究说明','components':[
                  {'id':'stem','form':'复合词干','role':'词干'},
                  {'id':'root','parent_id':'stem','form':'r','role':'词根','lexeme_id':root['id'],'usage_id':u['id'],'sense_id':u['senses'][0]['id'],'form_id':root['body']['variants'][0]['id'],'features':[t['id']],'writings':[{'type_id':w['id'],'text':'r'}]},
                  {'id':'circum','form':'a…b','role':'环缀','segments':['a','b'],'gloss':'PST'}]}]}
        word=self.save('word',{'word_structure':data});return cls,w,t,root,word

    def test_roundtrip_templates_rename_reverse_inputs_and_undo(self):
        c,w,t,root,word=self.setup_structure()
        self.assertEqual(len(c['template']['slots']),4)
        self.assertEqual(word['body']['word_structure']['analyses'][0]['components'][1]['lexeme_id'],root['id'])
        code,r=self.call('/api/class-save',{**c,'name':'II类'});self.assertEqual(code,200,r)
        self.assertEqual(self.get(word)['body']['word_structure']['memberships'][0]['class_id'],c['id'])
        self.assertEqual(self.call('/api/class-delete',{**c,'revision':c['revision']+1})[0],200);self.undo()
        before=self.get(word);body=copy.deepcopy(before['body']);body['word_structure']['memberships'][0]['notes']='修改'
        self.save('word',body,before);self.undo()
        self.assertEqual(self.get(word)['body']['word_structure']['memberships'][0]['notes'],'例外说明')
        self.undo('redo');self.assertEqual(self.get(word)['body']['word_structure']['memberships'][0]['notes'],'修改')
        options=self.call('/api/morphology-options?language=ordos')[1]
        self.assertIn(c['id'],[r['id'] for r in options['classes']]);self.assertIn(w['id'],[r['id'] for r in options['writing_types']])

    def test_reference_guards_and_writing_transfer(self):
        c,w,t,root,word=self.setup_structure()
        self.assertEqual(self.call('/api/lexeme-delete',{**root,'confirmed':True})[0],400)
        bad=copy.deepcopy(root);bad['body']['usages']=[]
        self.assertEqual(self.call('/api/lexeme-save',bad)[0],400)
        bad=copy.deepcopy(root);bad['body']['variants']=[]
        self.assertEqual(self.call('/api/lexeme-save',bad)[0],400)
        typ=next(x for x in self.call('/api/writing-types?lexical_language=ordos')[1]['items'] if x['id']==w['id'])
        self.assertEqual(self.call('/api/writing-delete',{**typ,'confirmed':True})[0],400)
        _,other=self.call('/api/writing-save',{'name':'替代','font':'Junicode'})
        code,r=self.call('/api/writing-delete',{**typ,'confirmed':True,'replacement_id':other['id']});self.assertEqual(code,200,r)
        body=self.get(word)['body']['word_structure']
        self.assertEqual(body['memberships'][0]['parts'][0]['writings'][0]['type_id'],other['id'])
        self.assertEqual(body['analyses'][0]['components'][1]['writings'][0]['type_id'],other['id'])

    def test_cycles_cross_language_invalid_groups_and_multiple_defaults(self):
        c,w,t,root,word=self.setup_structure()
        b=copy.deepcopy(root);b['body']['word_structure']={'analyses':[{'components':[{'form':'word','lexeme_id':word['id']}]}]}
        self.assertEqual(self.call('/api/lexeme-save',b)[0],400)
        for mutate in [lambda a:a['components'][0].update(parent_id='root'),lambda a:a['components'][1].update(parent_id='missing')]:
            bad=copy.deepcopy(word);mutate(bad['body']['word_structure']['analyses'][0]);self.assertEqual(self.call('/api/lexeme-save',bad)[0],400)
        bad=copy.deepcopy(word);bad['body']['word_structure']['analyses'].append({'id':'b','default':True,'components':[{'form':'another'}]})
        self.assertEqual(self.call('/api/lexeme-save',bad)[0],400)
        _,lid=self.call('/api/save-language',{'name':'其他','metadata':{}})
        _,foreign=self.call('/api/lexeme-save',{'headword':'foreign','body':{},'_language':lid['id']})
        bad=copy.deepcopy(word);bad['body']['word_structure']['analyses'][0]['components'][0]['lexeme_id']=foreign['id']
        self.assertEqual(self.call('/api/lexeme-save',bad)[0],400)

    def test_usage_scope_principal_variant_and_multiple_analyses(self):
        c,w,t,root,word=self.setup_structure()
        b=copy.deepcopy(root['body']);b['word_structure']={'memberships':[{'class_id':c['id'],'usage_id':b['usages'][0]['id'],'parts':[{'label':'变体','variant_id':b['variants'][0]['id']}]}],'analyses':[{'title':'共时','level':'synchronic'},{'title':'词源','level':'diachronic'}]}
        root=self.save('root',b,root)
        self.assertTrue(root['body']['word_structure']['analyses'][0]['default'])
        bad=copy.deepcopy(root);bad['body']['variants']=[];self.assertEqual(self.call('/api/lexeme-save',bad)[0],400)

    def test_export_import_backup_restore_and_legacy_client(self):
        c,w,t,root,word=self.setup_structure()
        old=copy.deepcopy(word);old['body'].pop('word_structure');old['body']['notes']='older client'
        self.save('word',old['body'],old)
        self.assertEqual(self.get(word)['body']['word_structure']['analyses'][0]['source'],'调查')
        bundle=self.call('/api/export-language?language=ordos')[1]
        _,other=self.call('/api/save-language',{'name':'copy','metadata':{}})
        code,r=self.call('/api/import-language',{'bundle':bundle,'_language':other['id']});self.assertEqual(code,200,r)
        words=self.call('/api/lexemes?language='+other['id'])[1]['items'];cw=next(x for x in words if x['headword']=='word');cr=next(x for x in words if x['headword']=='root')
        data=cw['body']['word_structure'];component=data['analyses'][0]['components'][1]
        self.assertEqual(component['lexeme_id'],cr['id']);self.assertNotEqual(component['form_id'],root['body']['variants'][0]['id']);self.assertNotEqual(data['memberships'][0]['class_id'],c['id'])
        cc=next(r for r in self.call('/api/classes?language='+other['id'])[1] if r['kind']=='morph');self.assertEqual(cc['template']['title'],'基本词形')
        path=Path(self.temp.name)/'backup.json';path.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8');dest=Path(self.temp.name)/'restored.sqlite3';restore(path,dest);server.DB=dest
        self.assertEqual(self.get(cw)['body']['word_structure'],data)

    def test_import_keeps_distinct_templates_and_unused_class_undo(self):
        c,w,t,root,word=self.setup_structure()
        bundle=self.call('/api/export-language?language=ordos')[1]
        _,other=self.call('/api/save-language',{'name':'copy','metadata':{}})
        code,existing=self.call('/api/class-save',{'kind':'morph','name':'第二变位法','template':{'title':'不同模板','slots':[{'label':'不同项目'}]},'_language':other['id']});self.assertEqual(code,200,existing)
        code,r=self.call('/api/import-language',{'bundle':bundle,'_language':other['id']});self.assertEqual(code,200,r)
        classes=[c for c in self.call('/api/classes?language='+other['id'])[1] if c['kind']=='morph']
        self.assertEqual(len(classes),2)
        self.assertEqual({c['template']['title'] for c in classes},{'不同模板','基本词形'})
        _,empty=self.call('/api/class-save',{'kind':'morph','name':'空类','template':{'title':'主要部分','slots':[{'label':'第一项'}]}})
        entry=next(c for c in self.call('/api/classes?language=ordos')[1] if c['id']==empty['id'])
        self.assertEqual(self.call('/api/class-delete',entry)[0],200)
        self.undo()
        self.assertEqual(next(c for c in self.call('/api/classes?language=ordos')[1] if c['id']==entry['id'])['template']['slots'][0]['label'],'第一项')
