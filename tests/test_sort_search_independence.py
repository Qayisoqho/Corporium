"""Custom collation must not turn literal replacement into whole-grapheme matching."""
import unittest
from urllib.parse import urlencode
import test_lexicon


class SortSearchIndependenceTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo

    def api(self,path,body=None):
        code,r=self.call('/api/'+path,body);self.assertEqual(code,200,r);return r

    def scheme(self):return self.api('dict-org-order-save',dict(name='Diacritics',alphabet='p p̄ b ḇ a á x x́'))

    def replace(self,prefix,args):
        plan=self.api(prefix+'-preview',args)
        self.assertEqual(len(plan['changes']),2,plan)
        self.api(prefix+'-apply',{**args,'token':plan['token'],'keys':[c['key'] for c in plan['changes']]})

    def test_dictionary_base_replacement_preserves_marks_in_both_entry_kinds(self):
        self.scheme()
        for kind,save,field,read in [('lexeme','lexeme-save','headword','lexeme'),('morpheme','morpheme-save','form','morpheme')]:
            with self.subTest(kind=kind):
                entry=self.api(save,{field:'a á', 'body':{}})
                args=dict(kind=kind,field=field,scope='current',find='a',replacement='x',**{kind+'_id':entry['id']})
                self.replace('dictionary-replace',args)
                self.assertEqual(self.api(read+'?id='+entry['id'])[field],'x x́')
                self.assertEqual(self.undo()[0],200)
                self.assertEqual(self.api(read+'?id='+entry['id'])[field],'a á')

    def test_corpus_and_independent_base_replacement_preserves_marks(self):
        self.scheme()
        corpus=self.seed('#pass([a á], (([a],[A]),([á],[A])), [test])')
        example=self.api('example-save',dict(body=dict(ipa='a á',translation='test',words=[dict(form='a',gloss='A'),dict(form='á',gloss='A')],targets=[])))
        for owner in ['corpus','independent']:
            with self.subTest(owner=owner):
                self.replace('text-replace',dict(owner_kind=owner,field='form',find='a',replacement='x'))
                words=self.entries()[0]['words'] if owner=='corpus' else self.api('independent-example?id='+example['id'])['body']['words']
                self.assertEqual([w['form'] for w in words],['x','x́'])
                self.assertEqual(self.undo()[0],200)

    def test_sorting_does_not_change_search_hits_or_stored_spelling(self):
        spellings=['a','á','pa','p̄a','ḵeéḵa']
        for word in spellings:self.api('lexeme-save',dict(headword=word,body={}))
        queries=['a','á','p','p̄','ḵ']
        def hits(query,order=''):
            return {r['id']:r['headword'] for r in self.api('lexemes?'+urlencode(dict(language='ordos',q=query,sort_order=order)))['items']}
        before={q:hits(q) for q in queries};scheme=self.scheme()
        for q in queries:self.assertEqual(hits(q,scheme['id']),before[q])
        self.assertEqual({r['headword'] for r in self.api('lexemes')['items']},set(spellings))
