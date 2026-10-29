import unittest

import test_paradigms as fixtures


class PrimaryMatchingTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo','complete'):
        locals()[name]=getattr(fixtures.ParadigmTests,name)

    def entry(self,mode='independent',declared=True,**extra):
        b=fixtures.body()
        b['variants'][0]['form']='go'
        meaning=b['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]
        meaning.update(short_gloss='去',base_sense_id='go-meaning' if declared else '')
        if mode=='inherit':meaning.update(gloss_mode='inherit',gloss_addition='')
        b.update(extra)
        return self.api('lexeme-save',dict(headword='go',body=b))

    def preview(self):return self.api('lexeme-auto-preview?language=ordos')

    def test_identical_primary_and_table_form_link_once_both_sources_and_undo(self):
        x=self.entry()
        sources=[self.source(kind,[('go','去')]) for kind in ('corpus','independent')]
        p=self.preview()
        self.assertEqual(len(p['matches']),2)
        self.assertEqual(p['ambiguous'],[]);self.assertEqual(p['suggestions'],[])
        self.assertEqual({m['sense_id'] for m in p['matches']},{'go-meaning'})
        self.assertTrue(all(m['form_id'] is None for m in p['matches']))
        self.api('lexeme-auto-link',dict(token=p['token']))
        self.assertEqual(self.preview()['already_linked'],2)
        self.undo();self.assertEqual(len(self.preview()['matches']),2)
        self.undo(True);self.assertEqual(self.preview()['already_linked'],2)
        x=self.api('lexeme?id='+x['id']);x['body']['usages'][0]['senses'][0]['short_gloss']='移动'
        self.api('lexeme-save',x)
        self.assertEqual([self.detail(s)['body']['words'][0]['gloss'] for s in sources],['移动']*2)

    def test_inherited_and_unassigned_meanings_use_same_rule(self):
        for mode,declared in [('inherit',True),('independent',False)]:
            with self.subTest(mode=mode):
                x=self.entry(mode,declared)
                # Inspect the common matching projection without creating a
                # second homonym in the same database.
                import paradigms,lexicon
                cs=list(paradigms.matching_candidates(x['body'],'go',lambda g,f:lexicon.auto_gloss_key(g,{},f)))
                self.assertNotIn('went-meaning',[s['id'] for u,s,f in cs])
                self.api('lexeme-delete',dict(id=x['id'],revision=x['revision'],confirmed=True))

    def test_blank_gloss_completion_also_has_one_candidate(self):
        self.entry()
        for kind in ('corpus','independent'):
            src=self.source(kind,[('go','')]);p=self.complete(src)
            self.assertTrue(p['rows'][0]['automatic'])
            self.assertEqual(len(p['rows'][0]['candidates']),1)
            self.assertEqual(p['rows'][0]['candidates'][0]['sense_id'],'go-meaning')
            self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'去')

    def test_distinct_entry_and_distinct_base_senses_still_require_selection(self):
        x=self.entry()
        other=self.api('dictionary-copy',dict(kind='lexeme',id=x['id'],revision=x['revision'],confirmed=True))
        self.source('corpus',[('go','去')])
        p=self.preview();self.assertEqual(p['matches'],[])
        self.assertEqual({c['lexeme_id'] for c in p['ambiguous'][0]['candidates']},{x['id'],other['id']})
        self.api('lexeme-delete',dict(id=other['id'],revision=other['revision'],confirmed=True))
        x=self.api('lexeme?id='+x['id'])
        x['body']['usages'][0]['senses'].append(dict(id='another-base',short_gloss='去',definition='另一义项'))
        self.api('lexeme-save',x)
        p=self.preview();self.assertEqual(len(p['ambiguous'][0]['candidates']),2)

    def test_form_features_and_other_base_reference_are_not_discarded(self):
        tag=self.api('grammar-save',dict(symbol='HON'))['id']
        x=self.entry();b=x['body'];b['variants'][0]['features']=[tag]
        self.api('lexeme-save',x)
        src=self.source('independent',[('go','')])
        p=self.api('sentence-gloss-preview',self.args(src))
        self.assertFalse(p['rows'][0]['automatic'])
        self.assertEqual(len(p['rows'][0]['candidates']),2)
        x=self.api('lexeme?id='+x['id']);x['body']['variants'][0]['features']=[]
        x['body']['usages'][0]['senses'].append(dict(id='other',short_gloss='离开'))
        x['body']['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['base_sense_id']='other'
        self.api('lexeme-save',x)
        self.source('corpus',[('go','去')]);p=self.preview()
        self.assertEqual(len(p['ambiguous'][0]['candidates']),2)

    def test_marked_candidates_remain_manual_but_duplicate_primary_is_removed(self):
        x=self.entry();x['headword']='go-';x['body']['variants'][0]['form']='go-';self.api('lexeme-save',x)
        self.source('corpus',[('go','去')]);p=self.preview()
        self.assertEqual(p['matches'],[]);self.assertEqual(p['ambiguous'],[])
        self.assertEqual(len(p['suggestions']),1)
        self.api('lexeme-auto-link',dict(token=p['token'],mode='candidates',selected=[p['suggestions'][0]['candidate_id']]))
        self.assertEqual(self.preview()['already_linked'],1)

    def test_changed_table_invalidates_preview_and_manual_form_ids_are_preserved(self):
        x=self.entry();src=self.source('corpus',[('go','去')]);p=self.preview()
        x['body']['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['short_gloss']='去.PST'
        x=self.api('lexeme-save',x)
        code,error=self.call('/api/lexeme-auto-link',dict(token=p['token']))
        self.assertEqual(code,400,error)
        self.assertEqual(self.preview()['already_linked'],0)
        self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',link_revision=0,
            lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id='verb',sense_id='went-meaning',form_id='went'))
        self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'去.PST')


if __name__=='__main__':unittest.main()
