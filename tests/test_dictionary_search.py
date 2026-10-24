import json
import unittest
from urllib.parse import urlencode
import test_word_structure
import test_dictionary_organization
import server
import test_annotations
import test_dictionary_manager
import test_object_media

class DictionarySearchTests(unittest.TestCase):
    setUp=test_word_structure.WordStructureTests.setUp
    tearDown=test_word_structure.WordStructureTests.tearDown
    call=test_word_structure.WordStructureTests.call
    undo=test_word_structure.WordStructureTests.undo
    save=test_word_structure.WordStructureTests.save
    setup_structure=test_word_structure.WordStructureTests.setup_structure
    get=test_word_structure.WordStructureTests.get

    def search(self,q='',**spec):
        code,r=self.call('/api/lexemes?'+urlencode({'q':q,'search':json.dumps(spec),'page_size':10}))
        self.assertEqual(code,200,r);return r

    def condition(self,field,value='',op='contains'):
        return dict(field=field,value=value,op=op)

    def test_fields_resolve_labels_custom_writing_and_structure(self):
        c,w,t,root,word=self.setup_structure()
        for field,value in [('word_structure.memberships.class_id','第二变位法'),('writing:'+w['id'],'wɜːd'),('word_structure.analyses.components.lexeme_id','root'),('word_structure.memberships.parts.features','PST'),('part:'+c['id']+':现在时','word'),('word_structure.analyses.level','共时')]:
            self.assertEqual([r['id'] for r in self.search(conditions=[self.condition(field,value)])['items']],[word['id']],(field,value))
        self.assertEqual(self.search(q=t['id'])['total'],0)
        fields={r['id']:r['name'] for r in self.call('/api/dictionary-search-options')[1]['fields']}
        self.assertIn('writing:'+w['id'],fields)
        self.assertIn('part:'+c['id']+':不定式',fields)
        self.assertEqual([r['id'] for r in self.search(class_id=c['id'])['items']],[word['id']])

    def test_boolean_empty_unicode_case_and_pagination(self):
        for n in range(15):self.save('word'+str(n),{'notes':'évidence' if n<12 else 'other'})
        spec={'conditions':[self.condition('notes','e\u0301vidence','exact'),self.condition('headword','word','prefix')]}
        result=self.search(**spec);self.assertEqual((result['total'],len(result['items']),result['pages']),(12,10,2))
        self.assertEqual(self.search(q='ÉVIDENCE')['total'],12)
        self.assertEqual(self.search(q='ÉVIDENCE',case=True)['total'],0)
        self.assertEqual(self.search(conditions=[self.condition('notes','other'),self.condition('headword','word1','exact')],combine='any')['total'],4)
        self.assertEqual(self.search(conditions=[self.condition('variants.form',op='empty')])['total'],15)
        self.assertEqual(self.search(conditions=[self.condition('notes','other','not_contains')])['total'],12)
        self.assertEqual(self.call('/api/lexemes?'+urlencode({'search':json.dumps({'conditions':[self.condition('bad')]})}))[0],400)

    def test_sense_tags_and_category_parent_scope(self):
        tid=self.call('/api/grammar-save',{'symbol':'ANIM','description':'有生','category':'名词特征'})[1]['id']
        a=self.save('plant',{'usages':[{'pos':'名词','subclass':'普通名词','senses':[{'definition':'植物','features':[tid]}]}]})
        self.save('grow',{'usages':[{'pos':'动词','senses':[{'definition':'生长'}]}]})
        self.assertEqual([r['id'] for r in self.search(conditions=[self.condition('usages.senses.features','有生')])['items']],[a['id']])
        classes=self.call('/api/dictionary-search-options')[1]['classes']
        for kind,name in [('pos','名词'),('pos','名词 / 普通名词'),('grammar','名词特征')]:
            cid=next(c['id'] for c in classes if c['kind']==kind and c['name']==name)
            self.assertEqual([r['id'] for r in self.search(class_id=cid)['items']],[a['id']])
        parent=self.call('/api/dict-org-class-save',{'name':'自然'})[1]['id']
        child=self.call('/api/dict-org-class-save',{'name':'植物','parent_id':parent})[1]['id']
        a=self.get(a);a['body']['semantic_classes']=[child];self.save(a['headword'],a['body'],a)
        self.assertEqual(self.search(class_id=parent)['total'],1)
        other=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id']
        url='/api/lexemes?'+urlencode({'language':other,'search':json.dumps({'class_id':parent})})
        self.assertEqual(self.call(url)[0],400)

    def test_example_layers_media_and_empty_principal_part(self):
        x=self.save('plant',{'usages':[{'pos':'名词','senses':[{'definition':'植物'}]}]})
        e=test_dictionary_manager.DictionaryManagerTests.example(self,x)
        layer=test_annotations.AnnotationTests.layer(self)
        test_annotations.AnnotationTests.annotate(self,'independent',e,layer)
        self.assertEqual(self.search(conditions=[self.condition('layer:'+layer['id'],'NOUN')])['total'],1)
        self.assertEqual(self.search(q='调查笔记')['total'],1)
        speaker=self.call('/api/timeline-speaker-save',{'name':'测试录音人','metadata':{}})[1]['id']
        code,result=test_object_media.ObjectMediaTests.add(self,x,test_object_media.ObjectMediaTests.audio(self),{'caption':'测试发音','speakers':[speaker]})
        self.assertEqual(code,200,result)
        self.assertEqual(self.search(conditions=[self.condition('media.speakers','测试录音人')])['total'],1)
        self.assertEqual(self.search(q='测试发音')['total'],1)
        self.assertEqual(self.search(q='sample.wav')['total'],1)
        cls=self.call('/api/class-save',{'name':'空部分测试','kind':'morph'})[1]['id']
        x=self.get(x);x['body']['word_structure']={'memberships':[{'class_id':cls,'parts':[{'label':'空主要部分'}]}]}
        self.save(x['headword'],x['body'],x)
        self.assertEqual(self.search(conditions=[self.condition('part:'+cls+':空主要部分',op='empty')])['total'],1)

    def test_shared_examples_and_orphans_do_not_change_search_scope(self):
        a=self.save('a',{'usages':[{'pos':'名词','senses':[{'definition':'甲'}]}]})
        b=self.save('b',{'usages':[{'pos':'名词','senses':[{'definition':'乙'}]}]})
        example=test_dictionary_manager.DictionaryManagerTests.example(self,a)
        with server.connect() as db:
            row=db.execute('SELECT body FROM dictionary_examples WHERE id=?',(example['id'],)).fetchone()
            body=json.loads(row['body'])
            body['targets'].append({**body['targets'][0],'lexeme_id':b['id']})
            body['notes']='shared-evidence'
            db.execute('UPDATE dictionary_examples SET body=? WHERE id=?',(json.dumps(body),example['id']))
            orphan={**body,'targets':[],'notes':'unlinked-only','orphan_field':'hidden'}
            db.execute('INSERT INTO dictionary_examples(id,language_id,body,revision) VALUES(?,?,?,1)',('orphan','ordos',json.dumps(orphan)))
        self.assertEqual({r['id'] for r in self.search(q='shared-evidence')['items']},{a['id'],b['id']})
        self.assertEqual(self.search(q='unlinked-only')['total'],0)
        self.assertEqual(self.search(conditions=[self.condition('examples.notes','shared-evidence','not_contains')])['total'],0)

    def test_replace_uses_full_filter_scope(self):
        self.save('a',{'notes':'target','usages':[{'pos':'名词'}]})
        self.save('b',{'notes':'target','usages':[{'pos':'动词'}]})
        request=dict(scope='search',query='',search={'conditions':[self.condition('usages.pos','名词','exact')]},field='notes',find='target',replacement='changed',mode='exact',case=True)
        code,plan=self.call('/api/dictionary-replace-preview',request)
        self.assertEqual(code,200,plan);self.assertEqual(plan['records'],1);self.assertEqual(len(plan['changes']),1)
        code,result=self.call('/api/dictionary-replace-apply',{**request,'token':plan['token'],'keys':[c['key'] for c in plan['changes']]})
        self.assertEqual(code,200,result)
        self.assertEqual(self.search(q='changed')['total'],1);self.assertEqual(self.search(q='target')['total'],1)

if __name__=='__main__':unittest.main()
