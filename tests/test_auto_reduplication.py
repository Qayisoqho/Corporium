import copy
import unittest

import auto_reduplication as auto
import corpus
import grammar
import reduplication
import server
import test_reduplication


class AutoReduplicationTests(unittest.TestCase):
    setUp=test_reduplication.ReduplicationTests.setUp
    tearDown=test_reduplication.ReduplicationTests.tearDown
    call=test_reduplication.ReduplicationTests.call
    seed=test_reduplication.ReduplicationTests.seed
    entries=test_reduplication.ReduplicationTests.entries
    get=test_reduplication.ReduplicationTests.get
    undo=test_reduplication.ReduplicationTests.undo
    draft=test_reduplication.ReduplicationTests.draft

    def tags(self,language='ordos'):
        for symbol,aliases in [('intesf',['INTS']),('dur',[]),('PL',[])]:
            code,result=self.call('/api/grammar-save',dict(symbol=symbol,aliases=aliases,_language=language))
            self.assertEqual(code,200,result)

    def example(self,kind,form='zub~zuzaan',gloss='intesf~厚的'):
        if kind=='corpus':return self.seed('#pass([ipa], ((['+form+'],['+gloss+']),), [translation])')
        code,e=self.call('/api/example-save',dict(body=dict(ipa='ipa',words=[dict(form=form,gloss=gloss)])))
        self.assertEqual(code,200,e);return e

    def save_full(self,kind,e):
        if kind=='corpus':
            current=next(r for r in self.entries() if r['id']==e['id'])
            payload={**current,'notes':current.get('notes','')}
            return self.call('/api/save',payload)
        current=self.draft(kind,e)
        return self.call('/api/example-save',dict(id=e['id'],revision=current['revision'],body=current['body']))

    def relations(self,kind,e):return self.get(e,kind)['body'].get('reduplications',[])

    def test_both_full_editors_and_no_read_or_import_mutation(self):
        # Seed before registering to cover old saved independent examples too.
        examples=[(kind,self.example(kind)) for kind in ('corpus','independent')]
        self.tags()
        for kind,e in examples:
            self.assertEqual(self.relations(kind,e),[])
            code,result=self.save_full(kind,e);self.assertEqual(code,200,result)
            rows=self.relations(kind,e);self.assertEqual(len(rows),1)
            self.assertEqual((rows[0]['source']['form'],rows[0]['base']['form']),('zub','zuzaan'))
            self.assertEqual(rows[0]['type'],'unspecified')
            code,result=self.save_full(kind,e);self.assertEqual(code,200,result)
            self.assertEqual(self.relations(kind,e),rows)

    def test_both_inline_editors_undo_redo_and_stable_identity(self):
        examples=[(kind,self.example(kind)) for kind in ('corpus','independent')]
        self.tags()
        for kind,e in examples:
            d=self.draft(kind,e);d['body']['translation']='saved with relation'
            code,result=self.call('/api/inline-save',d);self.assertEqual(code,200,result)
            rows=self.relations(kind,e);self.assertEqual(len(rows),1)
            self.assertEqual(self.undo()[0],200);self.assertEqual(self.relations(kind,e),[])
            self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.relations(kind,e),rows)
            d=self.draft(kind,e);d['body']['notes']='again'
            self.assertEqual(self.call('/api/inline-save',d)[0],200)
            self.assertEqual(self.relations(kind,e),rows)

    def test_fixed_slot_legacy_editor_and_creation(self):
        e=self.example('corpus');self.tags()
        d=self.draft('corpus',e);d.pop('slot_ids')
        code,result=self.call('/api/inline-save',d);self.assertEqual(code,200,result)
        self.assertEqual(len(self.relations('corpus',e)),1)
        e=self.example('independent');self.assertEqual(len(self.relations('independent',e)),1)
        for kind in ('corpus','independent'):
            body=dict(ipa='ipa',translation='',notes='',words=[dict(form='zub~zuzaan',gloss='INTS~thick')])
            text=self.example('corpus')
            payload=dict(kind=kind,text_id=text['text_id'],body=body,slot_ids=['new:word'],before=[],cells=[],layers=[])
            code,result=self.call('/api/sentence-create',payload);self.assertEqual(code,200,result)
            self.assertEqual(len(self.relations(kind,result)),1)

    def test_prefix_suffix_mixed_gloss_and_outside_affixes(self):
        self.tags()
        for form,gloss,source,base in [('zub~zuzaan','intesf~厚的','zub','zuzaan'),
                ('zuzaan~zub','thick~INTS','zub','zuzaan'),
                ('zub~zuzaan','INTS~thick.PL','zub','zuzaan'),
                ('a-zub~zuzaan-s','x-intesf~thick-PL','zub','zuzaan')]:
            e=self.example('independent',form,gloss)
            row=self.relations('independent',e)[0]
            self.assertEqual((row['source']['form'],row['base']['form']),(source,base))

    def test_invalid_incomplete_and_ambiguous_cells_do_not_block_good_cells(self):
        self.tags()
        invalid=[('zub~zuzaan',''),('zub~zuzaan','intesf'),('zub~zuzaan','intesf~'),
            ('zub~zuzaan-','intesf~thick-PL'),('zub~zuzaan','intesf-thick'),
            ('zub~zuzaan','intesf~PL'),('zub~zuzaan','thick~thick'),
            ('zub~zuzaan','MYSTERY~thick'),('zub~zuzaan','intesf~UNKNOWN'),
            ('zub~zuzaan','[unregistered]~thick'),('a~b~c','intesf~dur~thick'),
            ('kam~am~ri','home~intesf~home'),('a-zub~zuzaan','-intesf~thick')]
        words=[dict(form=f,gloss=g) for f,g in invalid]+[dict(form='zub~zuzaan',gloss='intesf~厚的')]
        code,e=self.call('/api/example-save',dict(body=dict(ipa='ipa',words=words)))
        self.assertEqual(code,200,e)
        info=self.get(e,'independent')['body']['reduplication_info']['relations']
        self.assertEqual(len(info),1);self.assertEqual(info[0]['source_word'],len(invalid))

    def test_existing_manual_direction_and_stale_relation_are_preserved(self):
        e=self.example('corpus')
        d=self.get(e)
        payload=dict(kind='corpus',id=e['id'],revision=d['revision'],action='redup-save',
            source=dict(word=0,key='r:1:host'),base=dict(word=0,key='r:0:host'),type='modified',notes='manual')
        self.assertEqual(self.call('/api/segmentation-save',payload)[0],200)
        original=self.relations('corpus',e);self.tags()
        self.assertEqual(self.save_full('corpus',e)[0],200)
        self.assertEqual(self.relations('corpus',e),original)
        d=self.draft('corpus',e);d['body']['words'][0]['form']='zob~zuzaan'
        self.assertEqual(self.call('/api/inline-save',d)[0],200)
        self.assertEqual(self.relations('corpus',e),original)
        self.assertTrue(self.get(e)['body']['reduplication_info']['relations'][0]['review'])

    def test_manual_delete_in_draft_is_not_recreated_during_same_save(self):
        self.tags();e=self.example('independent')
        d=self.draft('independent',e)
        d['body']['reduplications']=[]
        self.assertEqual(self.call('/api/inline-save',d)[0],200)
        self.assertEqual(self.relations('independent',e),[])

    def test_stale_manual_relation_does_not_block_unrelated_valid_word(self):
        e=self.example('corpus');self.tags();self.assertEqual(self.save_full('corpus',e)[0],200)
        old=self.relations('corpus',e)
        d=self.draft('corpus',e);d['body']['words'][0]['form']='zob~zuzaan'
        d['body']['words'].append(dict(form='yb~tell',gloss='dur~tell'));d['slot_ids'].append('new:other')
        self.assertEqual(self.call('/api/inline-save',d)[0],200)
        rows=self.relations('corpus',e)
        self.assertEqual(rows[0],old[0]);self.assertEqual(len(rows),2)
        self.assertEqual(rows[1]['source']['form'],'yb')

    def test_code_marked_cell_is_manual_but_unmarked_cell_can_link(self):
        e=self.seed('#pass([ipa], (([zub~zuzaan],[intesf~thick]),([yb~tell],[dur~tell])), [])')
        self.tags()
        code=self.call('/api/timeline-code-save',dict(name='Unknown language',metadata=dict(number='X')))[1]['id']
        d=self.call('/api/code-detail?kind=corpus&id='+e['id'])[1]
        payload=dict(kind='corpus',record_id=e['id'],token=d['token'],code_id=code,word_ids=[d['words'][0]['id']],notes='')
        status,result=self.call('/api/code-save',payload);self.assertEqual(status,200,result)
        self.assertEqual(self.call('/api/inline-save',self.draft('corpus',e))[0],200)
        rows=self.relations('corpus',e);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['source']['form'],'yb')

    def test_grouped_discontinuous_base_and_invalid_group(self):
        e=self.example('corpus','kam~am~ri','home~intesf~home');self.tags()
        d=self.get(e)
        p=dict(kind='corpus',id=e['id'],revision=d['revision'],action='save',word=0,
            members=['r:0:host','r:2:host'],type='stem',gloss='home',notes='')
        self.assertEqual(self.call('/api/segmentation-save',p)[0],200)
        self.assertEqual(self.relations('corpus',e),[])
        self.assertEqual(self.save_full('corpus',e)[0],200)
        row=self.relations('corpus',e)[0]
        self.assertEqual(row['source']['form'],'am')
        self.assertEqual([f['text'] for f in row['base']['fragments']],['kam','ri'])
        self.assertFalse(self.get(e)['body']['reduplication_info']['relations'][0]['review'])

    def test_language_inventory_override_and_aliases(self):
        self.tags()
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        e=self.example('corpus')
        d=next(r for r in self.entries() if r['id']==e['id']);d.update(language_id=other,notes='')
        self.assertEqual(self.call('/api/save',d)[0],200)
        self.assertEqual(self.relations('corpus',e),[])
        self.tags(other)
        self.assertEqual(self.save_full('corpus',e)[0],200)
        self.assertEqual(len(self.relations('corpus',e)),1)

    def test_typst_roundtrip_and_import_does_not_infer(self):
        self.tags();e=self.example('independent')
        body=self.get(e,'independent')['body']
        text=corpus.export_entry({**body,'function':'pass','edited':True})
        parsed,errors=corpus.parse(text);self.assertEqual(errors,[])
        self.assertEqual(parsed[0]['reduplications'],body['reduplications'])
        e=self.example('corpus')
        self.assertEqual(self.relations('corpus',e),[])

    def test_failure_rolls_back_automatic_relation_with_sentence(self):
        e=self.example('corpus');self.tags()
        d=self.draft('corpus',e)
        d['cells']=[dict(unit_id='missing',layer_id='missing',value='x')]
        self.assertEqual(self.call('/api/inline-save',d)[0],400)
        self.assertEqual(self.relations('corpus',e),[])

    def test_gloss_classification_is_inventory_based(self):
        lookup=grammar.index([dict(language_id='x',symbol=s,aliases=a) for s,a in
            [('intesf',['INTS']),('PL',[]),('PASS',[]),('A',[]),('N#sub[1]',[])]])
        for value,expected in [('intesf','grammatical'),('INTS','grammatical'),
                ('3PL','grammatical'),('N#sub[1]','grammatical'),('thick.PL','lexical'),
                ('厚的','lexical'),('pass','lexical'),('PASS','grammatical'),
                ('UNKNOWN','unknown'),('[undeclared]','unknown'),('RED','unknown'),('','unknown')]:
            with self.subTest(value=value):self.assertEqual(auto.gloss_role(value,'x',lookup),expected)


if __name__=='__main__':unittest.main()
