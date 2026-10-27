import json
import unittest
import corpus
import grammar
import test_lexicon


class GlossGroupTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo

    def test_dot_equivalents_and_bracketed_candidates(self):
        for separator in ['.', ';', ':', '_', '\\']:
            gloss='son'+separator+'NOM'+separator+'SG'
            self.assertEqual(list(grammar.tokens(gloss,'ordos',{},candidates=True)),['NOM','SG'])
            e=corpus.analyze(dict(ipa='',translation='',words=[dict(form='puer',gloss=gloss)]))
            self.assertEqual(len(e['words'][0]['morphemes']),1)
            self.assertEqual(e['warnings'],[])
        self.assertEqual(list(grammar.tokens('son[nom.sg]','ordos',{},candidates=True)),['nom','sg'])
        self.assertEqual(list(grammar.tokens('son#sub[nom.sg]','ordos',{},candidates=True)),[])
        self.assertEqual(list(grammar.tokens('son[nom;sg_acc\\pl]','ordos',{},candidates=True)),['nom','sg','acc','pl'])
        for symbol in ['NOM_SG','NOM\\SG','NOM;SG','NOM:SG']:
            self.assertEqual(self.call('/api/grammar-save',dict(symbol=symbol))[0],400)

    def test_groups_do_not_create_morphemes_and_tags_find_sentence(self):
        source='#pass([puer], (([puer],[son[nom.sg]]),([puer-x],[son[nom+sg]-PL])), [son])'
        e=self.seed(source)
        self.assertEqual(e['warnings'],[])
        self.assertEqual([len(w['morphemes']) for w in e['words']],[1,2])
        self.assertEqual(e['words'][1]['morphemes'][0]['gloss'],'son[nom+sg]')
        tag=self.call('/api/grammar-save',dict(symbol='NOM',description='主格'))[1]['id']
        self.call('/api/grammar-save',dict(symbol='SG',description='单数'))
        audit=self.call('/api/grammar-audit?language=ordos&lower=false&issue=usage&tag='+tag)[1]
        self.assertEqual(audit['total'],1)
        self.assertEqual(next(t for t in audit['tags'] if t['id']==tag)['uses'],2)
        u=self.call('/api/unit-dictionary?id='+e['words'][0]['unit_id'])[1]
        self.assertIn(tag,u['suggested_features'])
        self.assertEqual(self.call('/api/export?id='+e['text_id'])[1],source)
        # Inline save preserves the bracket group and its word identity.
        d=self.call('/api/annotations?kind=corpus&id='+e['id'])[1]
        d['body']['words'][0]['gloss']='son[nom;sg]'
        code,r=self.call('/api/inline-save',dict(kind='corpus',id=e['id'],revision=d['revision'],before=d['cells'],layers=d['layers'],body=d['body'],cells=[]))
        self.assertEqual(code,200,r)
        changed=self.entries()[0]
        self.assertEqual(changed['words'][0]['unit_id'],e['words'][0]['unit_id'])
        self.assertEqual(changed['words'][0]['morphemes'][0]['gloss'],'son[nom;sg]')
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.entries()[0]['words'][0]['gloss'],'son[nom.sg]')
        exported=self.call('/api/export-language?language=ordos')[1]
        language=self.call('/api/save-language',dict(name='Copy',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/import-language',dict(_language=language,bundle=exported))[0],200)
        copied=self.call('/api/entries?language='+language)[1]['items'][0]
        self.assertEqual(copied['words'][0]['gloss'],'son[nom.sg]')


if __name__=='__main__':unittest.main()
