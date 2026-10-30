import unittest
import lexicon
import test_lexicon

class AutoFeatureTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo

    def tag(self,symbol,**kw):
        code,r=self.call('/api/grammar-save',dict(symbol=symbol,**kw));self.assertEqual(code,200,r);return r['id']

    def test_inherent_features_complete_match_form_selection_and_undo(self):
        hon=self.tag('hon',aliases=['HONOR']);pl=self.tag('pl');pst=self.tag('pst')
        e=self.seed('#pass([ipa], (([take],[接受.hon]),([take],[接受]),([take],[接受.hon.pst]),([takes],[接受.pl.HONOR]),([takes],[接受.hon]),([take],[接受;hon])), [translation])')
        code,x=self.call('/api/lexeme-save',{'headword':'take','body':{'features':[hon],'variants':[{'form':'takes','features':[pl]}],'usages':[{'pos':'V','features':[hon],'senses':[{'short_gloss':'接受'}]}]}});self.assertEqual(code,200,x)
        plan=self.call('/api/lexeme-auto-preview?language=ordos')[1]
        self.assertEqual(len(plan['matches']),3,plan)
        variant=next(m for m in plan['matches'] if m['form']=='takes')
        self.assertEqual(variant['form_id'],x['body']['variants'][0]['id'])
        self.assertIn('固有特征',variant['match_reason'])
        before=self.entries()[0]['words']
        self.assertEqual(self.call('/api/lexeme-auto-link',{'token':plan['token']})[1]['count'],3)
        link=self.call('/api/unit-dictionary?id='+variant['unit_id'])[1]['link']
        with __import__('server').connect() as db:
            self.assertEqual(db.execute('SELECT form_id FROM morphology_analyses WHERE id=?',(link['id'],)).fetchone()[0],variant['form_id'])
        self.assertEqual([w['gloss'] for w in self.entries()[0]['words']],[w['gloss'] for w in before])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(len(self.call('/api/lexeme-auto-preview?language=ordos')[1]['matches']),3)
        self.assertEqual(self.undo('redo')[0],200)

    def test_usage_scope_ambiguity_and_stale_tag_alias(self):
        hon=self.tag('hon');pl=self.tag('pl')
        self.seed('#pass([ipa], (([take],[接受.hon]),([take],[接受.pl]),([take],[接受])), [translation])')
        code,x=self.call('/api/lexeme-save',{'headword':'take','body':{'usages':[{'pos':'V','features':[hon],'senses':[{'short_gloss':'接受'},{'short_gloss':'接受.hon'}]},{'pos':'N','features':[pl],'senses':[{'short_gloss':'接受'}]}]}});self.assertEqual(code,200,x)
        plan=self.call('/api/lexeme-auto-preview?language=ordos')[1]
        self.assertEqual(len(plan['matches']),1);self.assertEqual(len(plan['ambiguous']),1)
        self.assertEqual(plan['matches'][0]['pos'],'N')
        tag=next(t for t in self.call('/api/grammar-tags')[1] if t['id']==pl)
        self.assertEqual(self.call('/api/grammar-save',{**tag,'symbol':'plural'})[0],200)
        self.assertEqual(self.call('/api/lexeme-auto-link',{'token':plan['token']})[0],400)

    def test_signature_preserves_structure_and_duplicates(self):
        lookup={'hon':'h','pl':'p','nom':'n'}
        key=lambda s,fs=():lexicon.auto_gloss_key(s,lookup,fs)
        self.assertEqual(key('接受.hon',['h','p']),key('接受.pl.hon'))
        for separator in '.;:\\':self.assertEqual(key('接受'+separator+'hon'),key('接受.hon'))
        self.assertNotEqual(key('接受_hon'),key('接受.hon'))
        for gloss in ['接受[hon]','接受< hon>','接受-hon','接受.hon.hon','接受.HonX','接受. hon']:
            self.assertNotEqual(key(gloss),key('接受',['h']))
        self.assertNotEqual(key('s.1>o.3sg'),key('o.3sg>s.1'))
        self.assertNotEqual(key('son[nom.pl]'),key('son[pl.nom]'))
        self.assertNotEqual(key('接受<nom>',['h']),key('接受<nom>.hon'))

