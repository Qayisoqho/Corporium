import copy
import unittest
import paradigms
import sense_gloss
import test_paradigms


class SenseGlossTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo','complete','get','link','gloss'):
        locals()[name]=getattr(test_paradigms.ParadigmTests,name)

    def entry(self):
        b=test_paradigms.body();s=b['usages'][0]['senses'][0]
        s.update(short_gloss='北方',gloss_addition='LOC',show_gloss_addition=True)
        for row in b['paradigms'][0]['rows'][:2]:row['realizations'][0]['meanings'][0].update(gloss_mode='inherit',gloss_addition='PL',short_gloss='')
        return self.api('lexeme-save',dict(headword='go',body=b))

    def test_separate_storage_projection_and_free_text(self):
        x=self.entry();s=x['body']['usages'][0]['senses'][0]
        self.assertEqual(s['short_gloss'],'北方');self.assertEqual(s['gloss_addition'],'LOC')
        self.assertEqual(paradigms.usages(x['body'])[0]['senses'][0]['short_gloss'],'北方.LOC')
        self.assertEqual(paradigms.usages(x['body'])[0]['senses'][1]['short_gloss'],'北方.LOC.PL')
        self.assertEqual(sense_gloss.effective(dict(short_gloss='toward the north',gloss_addition='LOC.loc.PL')),'toward the north.LOC.PL')
        self.assertEqual(sense_gloss.effective(dict(short_gloss='',gloss_addition='LOC')),'LOC')
        before=copy.deepcopy(x['body']);paradigms.project(x['body']);self.assertEqual(before,x['body'])

    def test_toggle_inherits_to_both_sentence_kinds_and_single_undo(self):
        x=self.entry();sources=[self.source(k,[('go','北方.LOC')]) for k in ('corpus','independent')]
        plan=self.api('lexeme-auto-preview?language=ordos');self.assertEqual(len(plan['matches']),2)
        self.api('lexeme-auto-link',dict(token=plan['token']))
        x=self.get(x);x['body']['usages'][0]['senses'][0]['show_gloss_addition']=False
        self.api('lexeme-save',x)
        self.assertEqual([self.gloss(s) for s in sources],['北方','北方'])
        fresh=self.get(x);self.assertEqual(fresh['body']['usages'][0]['senses'][0]['gloss_addition'],'LOC')
        self.undo();self.assertEqual([self.gloss(s) for s in sources],['北方.LOC']*2)
        self.undo(True);self.assertEqual([self.gloss(s) for s in sources],['北方']*2)

    def test_native_morpheme_main_and_extra_meaning_projection_and_sync(self):
        m=self.api('morpheme-save',dict(form='m',body={'gloss':'北方','gloss_addition':'LOC','senses':[{'gloss':'方向','gloss_addition':'ALL','show_gloss_addition':False}]}))
        source=self.source('corpus',[('m','北方.LOC')]);plan=self.api('lexeme-auto-preview?language=ordos')
        self.assertEqual(len(plan['matches']),1);self.api('lexeme-auto-link',dict(token=plan['token']))
        m=self.api('morpheme?id='+m['id']);m['body']['show_gloss_addition']=False;self.api('morpheme-save',m)
        self.assertEqual(self.gloss(source),'北方');self.undo();self.assertEqual(self.gloss(source),'北方.LOC')
        import dictionary_targets,server
        with server.connect(audit=False) as db:b=dictionary_targets.common(db,m['id'])
        senses=paradigms.usages(b)[0]['senses'];self.assertEqual({s['short_gloss'] for s in senses},{'方向','北方.LOC'})

    def test_validation_and_language_exchange_preserve_raw_values(self):
        x=self.entry();bundle=self.api('export-language?language=ordos');lid=self.api('save-language',dict(name='Copy',metadata={}))['id']
        self.api('import-language',dict(bundle=bundle,_language=lid))
        copied=self.api('lexemes?language='+lid)['items'][0]['body']['usages'][0]['senses'][0]
        self.assertEqual((copied['short_gloss'],copied['gloss_addition'],copied['show_gloss_addition']),('北方','LOC',True))
        for value in ('LOC..PL','LOC-PL',9):
            b=copy.deepcopy(x['body']);b['usages'][0]['senses'][0]['gloss_addition']=value
            self.assertEqual(self.call('/api/lexeme-save',dict(headword='bad',body=b))[0],400)
        b=copy.deepcopy(x['body']);b['usages'][0]['senses'][0]['show_gloss_addition']='false'
        self.assertEqual(self.call('/api/lexeme-save',dict(headword='bad',body=b))[0],400)

    def test_replace_uses_free_text_without_writing_composed_labels_back(self):
        x=self.api('lexeme-save',dict(headword='north',body={'usages':[{'senses':[{'short_gloss':'北方','gloss_addition':'LOC'}]}]}))
        args=dict(kind='lexeme',field='short_gloss',find='LOC',replacement='DAT',scope='current',lexeme_id=x['id'])
        plan=self.api('dictionary-replace-preview',args);self.assertEqual(plan['changes'],[])
        args.update(find='北方',replacement='南方');plan=self.api('dictionary-replace-preview',args)
        self.assertEqual(len(plan['changes']),1)
        self.api('dictionary-replace-apply',{**args,'token':plan['token'],'keys':[p['key'] for p in plan['changes']]})
        s=self.get(x)['body']['usages'][0]['senses'][0]
        self.assertEqual((s['short_gloss'],s['gloss_addition']),('南方','LOC'))
        self.undo();self.assertEqual(self.get(x)['body']['usages'][0]['senses'][0]['short_gloss'],'北方')

    def test_search_projects_visible_native_additions_and_hides_display_metadata(self):
        m=self.api('morpheme-save',dict(form='m',body={'gloss':'北方','gloss_addition':'LOC','show_gloss_addition':True}))
        self.assertEqual(self.api('morphemes?language=ordos&q=LOC')['total'],1)
        m=self.api('morpheme?id='+m['id']);m['body']['show_gloss_addition']=False;self.api('morpheme-save',m)
        self.assertEqual(self.api('morphemes?language=ordos&q=LOC')['total'],0)
        self.assertEqual(self.api('morphemes?language=ordos&q=否')['total'],0)
