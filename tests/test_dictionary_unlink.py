import copy
import json
import unittest
from unittest.mock import patch
import server
import lexicon
import test_paradigm_inheritance as inherited


class DictionaryUnlinkTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo','complete','get','link','gloss','entry','edit_base'):
        locals()[name]=getattr(inherited.ParadigmInheritanceTests,name)

    def refs(self,x):return self.api('lexeme-examples?id='+x['id'])['items']

    def test_batch_freezes_both_sentences_one_undo_and_redo(self):
        x=self.entry();srcs=[self.source('corpus',[('went','old'),('extra',str(i))]) for i in range(2)]
        for src in srcs:self.link(src,x)
        self.edit_base(x,'2SG')
        refs=self.refs(x);before=self.api('undo-state')['generation']
        with patch('lexicon.validate_links',side_effect=AssertionError('unnecessary dictionary scan')):
            r=self.api('lexeme-unlink',dict(lexeme_id=x['id'],items=[dict(id=e['id'],revision=e['revision']) for e in refs]))
        self.assertEqual(r['count'],2);self.assertEqual(self.api('undo-state')['generation'],before+1)
        self.assertFalse(self.refs(x));self.assertEqual([self.gloss(s) for s in srcs],['2SG.ACC']*2)
        self.undo();self.assertEqual(len(self.refs(x)),2)
        self.undo(True);self.assertFalse(self.refs(x))
        self.edit_base(x,'3SG');self.assertEqual([self.gloss(s) for s in srcs],['2SG.ACC']*2)

    def test_batch_conflict_wrong_target_duplicate_and_scope_are_atomic(self):
        x=self.entry()
        for i in range(2):self.link(self.source('corpus',[('went','old'),('extra',str(i))]),x)
        refs=self.refs(x);items=[dict(id=e['id'],revision=e['revision']) for e in refs]
        for body in [dict(items=[items[0],{**items[1],'revision':99}]),dict(items=[items[0],items[0]]),dict(items=items,lexeme_id='wrong'),dict(items=items,_language='all-other'),dict(items=[]),dict(items=[{}])]:
            self.assertEqual(self.call('/api/lexeme-unlink',body)[0],400)
            self.assertEqual([r['id'] for r in self.refs(x)],[r['id'] for r in refs])

    def test_independent_removes_only_current_target_form_preserving_sentence(self):
        x=self.entry();src=self.source('independent',[('went','old'),('goes','old')])
        self.link(src,x)
        self.api('segmentation-link',dict(**self.args(src),word=1,key='@word',link_revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id='verb',sense_id='goes-meaning',form_id='goes'))
        self.edit_base(x,'2SG');row=self.api('dictionary-examples?id='+x['id'])[0]
        with patch('lexicon.validate_links',side_effect=AssertionError('unnecessary dictionary scan')):
            self.api('dictionary-examples-unlink',dict(lexeme_id=x['id'],form_id='went',items=[dict(id=row['id'],revision=row['revision'])]))
        after=self.api('dictionary-examples?id='+x['id'])[0]
        self.assertEqual([t['form_id'] for t in after['body']['targets']],['goes'])
        self.assertEqual([w['gloss'] for w in after['body']['words']],['2SG.ACC','2SG.GEN'])
        self.undo();self.assertEqual(len(self.api('dictionary-examples?id='+x['id'])[0]['body']['targets']),2)
        self.undo(True);self.edit_base(x,'3SG')
        self.assertEqual([w['gloss'] for w in self.detail(src)['body']['words']],['2SG.ACC','3SG.GEN'])
        row=self.api('dictionary-examples?id='+x['id'])[0]
        self.api('dictionary-examples-unlink',dict(lexeme_id=x['id'],items=[dict(id=row['id'],revision=row['revision'])]))
        self.assertFalse(self.api('dictionary-examples?id='+x['id']))
        self.assertEqual(self.detail(src)['body']['translation'],'translation')

    def test_renumbering_and_detached_paradigm_base_keep_existing_links(self):
        b=inherited.body();b['usages'][0]['senses'].insert(0,dict(id='unused',short_gloss='other'))
        x=self.api('lexeme-save',dict(headword='go',body=b));srcs=[self.source(k,[('went','old')]) for k in ('corpus','independent')]
        for src in srcs:self.link(src,x)
        x['body']['usages'][0]['senses'].pop(0);x=self.api('lexeme-save',x)
        self.assertEqual([self.gloss(s) for s in srcs],['1SG.ACC']*2)
        # The editor freezes inherited labels before removing their actual base.
        for table in x['body']['paradigms']:
            for row in table['rows']:
                for form in row['realizations']:
                    for meaning in form['meanings']:
                        meaning['short_gloss']=inherited.paradigms.effective_gloss(x['body'],table,meaning)
                        meaning.pop('gloss_mode',None);meaning.pop('gloss_addition',None);meaning['base_sense_id']=''
            table.pop('default_base_sense_id',None)
        x['body']['usages'][0]['senses']=[];self.api('lexeme-save',x)
        self.assertEqual([self.gloss(s) for s in srcs],['1SG.ACC']*2)

    def test_removal_proof_rejects_mixed_edits_and_new_references(self):
        link=dict(id='l',unit_id='u');changes={('lexical_links',1):(link,None)}
        self.assertTrue(lexicon.association_removals_only(changes))
        for table in ('lexemes','corpus_units','entries','grammar_tags'):
            self.assertFalse(lexicon.association_removals_only({**changes,(table,1):({'id':'x'},{'id':'x','notes':'changed'})}))
        self.assertFalse(lexicon.association_removals_only({('lexical_links',1):(None,link)}))
        a=dict(id='e',revision=1,body=json.dumps(dict(words=[],targets=[{'id':'a'},{'id':'b'}])))
        b={**a,'body':json.dumps(dict(words=[],targets=[{'id':'b'}]))}
        self.assertTrue(lexicon.association_removals_only({('dictionary_examples',1):(a,b)}))
        for body in (dict(words=[{'form':'changed'}],targets=[]),dict(words=[],targets=[{'id':'c'}])):
            self.assertFalse(lexicon.association_removals_only({('dictionary_examples',1):(a,{**b,'body':json.dumps(body)})}))

    def test_direct_sense_deletion_is_not_retargeted_by_new_ordinal(self):
        x=self.entry();x['body']['usages'][0]['senses'].append(dict(id='direct',short_gloss='DIRECT'))
        x=self.api('lexeme-save',x)
        for kind in ('independent','corpus'):
            src=self.source(kind,[('go','DIRECT')]);self.link(src,x,sid='direct',fid='')
            draft=copy.deepcopy(x);draft['body']['usages'][0]['senses'].pop()
            status,result=self.call('/api/lexeme-save',draft)
            self.assertEqual(status,400);self.assertIn('重新编号不会自动转移关联',result['error'])
            self.assertEqual(self.get(x)['body'],x['body']);self.assertEqual(self.gloss(src),'DIRECT')
