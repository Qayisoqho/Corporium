import unittest
import test_lexicon

class MarkCandidateTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo

    def word(self,form,gloss='说',senses=None):
        code,x=self.call('/api/lexeme-save',{'headword':form,'body':{'usages':[{'senses':senses or [{'short_gloss':gloss}]}]}})
        self.assertEqual(code,200,x);return x

    def plan(self,query=''):
        code,p=self.call('/api/lexeme-auto-preview?language=ordos'+query);self.assertEqual(code,200,p);return p

    def apply(self,p,selected,**kw):
        return self.call('/api/lexeme-auto-link',{**dict(token=p['token'],mode='candidates',selected=selected,ignore_symbols=p['ignore_symbols'],ignore_position=p['ignore_position']),**kw})

    def test_edge_candidates_not_substrings_or_loose_gloss_and_undo(self):
        self.seed('#pass([ipa], (([kele],[说]),([kelex],[说]),([kele],[讲]),([la],[语气])), [t])')
        self.word('kele-');self.word('=la','语气')
        p=self.plan();self.assertEqual(p['matches'],[]);self.assertEqual(len(p['suggestions']),2,p)
        self.assertEqual(self.call('/api/lexeme-auto-link',{'token':p['token']})[1]['count'],0)
        self.assertEqual(self.apply(p,[])[0],400)
        self.assertEqual(self.apply(p,['fake'])[0],400)
        self.assertEqual(self.apply(p,[p['suggestions'][0]['candidate_id']])[1]['count'],1)
        self.assertEqual(len(self.plan()['suggestions']),1)
        self.assertEqual(self.undo()[0],200);self.assertEqual(len(self.plan()['suggestions']),2)
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.apply(p,[p['suggestions'][1]['candidate_id']])[0],400)

    def test_internal_options_strict_priority_and_collisions(self):
        self.seed('#pass([ipa], (([soma],[家]),([ab],[说]),([kele],[说])), [t])')
        self.word('so-ma','家');self.word('a.b');self.word('kele-',senses=[{'short_gloss':'说','definition':'一'},{'short_gloss':'说','definition':'二'}])
        edge=self.plan();self.assertEqual(len(edge['suggestions']),2)
        self.assertEqual(self.apply(edge,[c['candidate_id'] for c in edge['suggestions']])[0],400)
        allp=self.plan('&ignore_position=all');self.assertEqual(len(allp['suggestions']),4)
        selected=next(c for c in allp['suggestions'] if c['form']=='ab')
        self.assertEqual(self.apply(allp,[selected['candidate_id']],ignore_position='edges')[0],400)
        self.assertEqual(len(self.plan('&ignore_position=all&ignore_symbols=-')['suggestions']),3)
        self.assertEqual(self.plan('&ignore_symbols=')['suggestions'],[])
        self.word('soma','家');p=self.plan('&ignore_position=all')
        self.assertEqual(len(p['matches']),0)
        same=[c for c in p['suggestions'] if c['form']=='soma']
        self.assertEqual(len(same),2)
        self.assertFalse(any(c['default_selected'] for c in same))
        self.assertEqual(self.call('/api/lexeme-auto-preview?language=ordos&ignore_symbols=x')[0],400)
