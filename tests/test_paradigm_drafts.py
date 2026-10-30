import copy
import unittest
import paradigms
import test_paradigms

class ParadigmDraftTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo','complete','get','gloss'):
        locals()[name]=getattr(test_paradigms.ParadigmTests,name)

    def draft(self,partial=False):
        body=test_paradigms.body()
        body['variants']=[v for v in body['variants'] if partial and v['id']=='goes']
        for i,row in enumerate(body['paradigms'][0]['rows'][:2]):
            if partial and i==1:continue
            row['state']='unfilled';row['realizations'][0]['form_id']=''
        return body

    def test_empty_and_partial_tables_keep_blank_forms_and_meanings_without_matching_them(self):
        for partial in (False,True):
            with self.subTest(partial=partial):
                body=self.draft(partial);headword='go'+str(partial)
                x=self.api('lexeme-save',dict(headword=headword,body=body))
                self.assertEqual(x['body']['paradigms'][0]['rows'][0]['realizations'][0]['form_id'],'')
                self.assertEqual(x['body']['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['short_gloss'],'去.PST')
                candidates=list(paradigms.candidates(x['body']))
                self.assertNotIn('went-meaning',[s['id'] for u,s,f in candidates])
                self.assertEqual(len(candidates),2 if partial else 1)
                for kind in ('corpus','independent'):
                    self.source(kind,[('','去.PST'),(headword,'去'),('went','去.PST')])
                plan=self.api('lexeme-auto-preview?language=ordos')
                self.assertFalse(any(not m.get('form','').strip() for k in ('matches','suggestions','ambiguous') for m in plan[k]))
                self.assertFalse(any(m['sense_id']=='went-meaning' for k in ('matches','suggestions','ambiguous') for m in plan[k]))

    def test_blank_form_drafts_survive_language_exchange_with_new_meaning_ids(self):
        x=self.api('lexeme-save',dict(headword='go',body=self.draft()))
        bundle=self.api('export-language?language=ordos')
        other=self.api('save-language',dict(name='Copy',metadata={}))['id']
        self.api('import-language',dict(bundle=bundle,_language=other))
        copied=self.api('lexemes?language='+other)['items'][0]['body']
        row=copied['paradigms'][0]['rows'][0]
        self.assertEqual(row['realizations'][0]['form_id'],'')
        self.assertNotEqual(row['realizations'][0]['meanings'][0]['id'],'went-meaning')
        self.assertEqual(row['realizations'][0]['meanings'][0]['short_gloss'],'去.PST')
        self.assertEqual(list(paradigms.meanings(copied)),[])

    def test_filling_a_draft_restores_its_stable_meaning_to_matching(self):
        x=self.api('lexeme-save',dict(headword='go',body=self.draft()))
        x['body']['variants']=[dict(id='new-form',form='went')]
        row=x['body']['paradigms'][0]['rows'][0];row['state']='filled';row['realizations'][0]['form_id']='new-form'
        x=self.api('lexeme-save',x)
        self.assertEqual([(f['form_id'],m['id']) for t,r,f,m in paradigms.meanings(x['body'])],[('new-form','went-meaning')])
        self.source('corpus',[('went','去.PST')]);plan=self.api('lexeme-auto-preview?language=ordos')
        self.assertEqual(len(plan['matches']),1);self.assertEqual(plan['matches'][0]['sense_id'],'went-meaning')
