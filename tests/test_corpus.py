import unittest
import copy
import corpus
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from corpus import parse, export_entry, match


class CorpusTests(unittest.TestCase):
    def test_analysis_cache_ignores_occurrence_identity_but_preserves_it(self):
        from unittest.mock import patch
        cache=corpus.WordAnalysisCache()
        with patch.object(corpus,'_analyze',wraps=corpus._analyze) as full:
            for i in range(12):
                source=dict(ipa='',translation='',words=[dict(form='a-b',gloss='A-B',annotation_id=str(i),token_id='t'+str(i),notes=str(i))])
                got=corpus.analyze(source,cache=cache)
                self.assertEqual(got['words'][0]['annotation_id'],str(i))
                self.assertEqual(got['words'][0]['notes'],str(i))
            self.assertEqual(full.call_count,1)
        # Failed analysis historically leaves an earlier analysis_form intact.
        for old in ('old-a','old-b'):
            source=dict(ipa='',translation='',words=[dict(form='a-b',gloss='A',analysis_form=old)])
            self.assertEqual(corpus.analyze(copy.deepcopy(source),cache=cache),corpus.analyze(source))

    def test_fixed_slot_reanalysis_matches_full_analysis_with_warnings_and_refs(self):
        import segmentation
        source=dict(ipa='#ipa',translation='#translation',orphaned_morphology=[{}],words=[
            dict(form='a-b',gloss='A'),dict(form='。',gloss=''),dict(form='so<l>ma',gloss='home<GEN>'),
            dict(form='c',gloss='#bad'),dict(form='word',gloss='meaning')])
        previous=corpus.analyze(copy.deepcopy(source))
        previous['targets']=[dict(segmentation_ref=segmentation.reference(previous['words'][2],2,previous['words'][2]['morphemes'][1]))]
        for cache in (None,corpus.WordAnalysisCache()):
            changed=copy.deepcopy(previous);changed['words'][0]['gloss']='A-B';changed['words'][2]['gloss']='home<POSS>'
            expected=corpus.analyze(copy.deepcopy(changed))
            got=corpus.reanalyze(changed,previous,{0,2},cache=cache)
            self.assertEqual(got,expected)
            self.assertEqual(previous['words'][0]['gloss'],'A')

    def test_operation_cache_preserves_analysis_warning_positions_and_isolation(self):
        cache=corpus.WordAnalysisCache()
        words=[dict(form='a-b',gloss='A-B'),dict(form='a#bad',gloss=''),dict(form='。',gloss=''),dict(form='#',gloss='#')]
        for offset in range(5):
            source=dict(ipa='#source',translation='译文',words=copy.deepcopy(words[offset%4:]+words[:offset%4]),orphaned_morphology=[{}])
            expected=corpus.analyze(copy.deepcopy(source))
            got=corpus.analyze(source,cache=cache)
            self.assertEqual(got,expected)
            got['words'][0]['form']='changed after caching'
            got['words'][0]['morphemes'].clear()
        small=corpus.WordAnalysisCache(limit=2000,items=2)
        for i in range(20):
            corpus.analyze(dict(ipa='',translation='',words=[dict(form=str(i),gloss='汉字𐀀')]),cache=small)
            self.assertLessEqual(small.bytes,small.limit);self.assertLessEqual(len(small.values),2)

    def test_mixed_nested_and_comments(self):
        text = '''// #pass([],(),[])
/* ignored /* nested */ #gloss([],(),[]) */
#gloss([IPA "unpaired quotation], (("a-b", [名-prt#sub[PQ]]), //([],[]),
([« c=d. »], "词=也")), [译文, 有（括号）])'''
        entries, errors = parse(text)
        self.assertEqual(errors,[])
        self.assertEqual(len(entries),1)
        e=entries[0]
        self.assertEqual(len(e['words']),2)
        self.assertEqual(e['words'][0]['gloss_kind'],'content')
        self.assertEqual(e['words'][0]['morphemes'][1]['boundary'],'-')
        self.assertTrue(match(e,'PQ','gloss',True)[1])
        self.assertTrue(match(e,'c','morpheme',True)[1])
        self.assertEqual(export_entry(e),text[text.index('#gloss([IPA'):])

    def test_samples_roundtrip(self):
        from public_fixtures import typ_source
        for count in (46,523):
            source=typ_source(count)
            entries,errors=parse(source)
            self.assertEqual(errors,[])
            self.assertEqual(len(entries),count)
            for entry in entries:
                for edited in (False,True):
                    entry['edited']=edited
                    again,errors=parse(export_entry(entry))
                    self.assertEqual(errors,[])
                    self.assertEqual(len(again),1)
                    for key in ('ipa','translation','words'):
                        self.assertEqual(again[0][key],entry[key])

    def test_mismatch_is_not_guessed(self):
        e,err=parse('#pass([], (([a-b],[x]),([c=d],[y-z])), [])')
        self.assertEqual(len(e[0]['warnings']),2)
        self.assertEqual(e[0]['words'][0]['morphemes'],[])

    def test_query_counts_unicode_and_case(self):
        e,_=parse('#pass([], (([« mülüü?],[prt#sub[PQ]]),([mülüü?],[prt#sub[PQ]]),([a-UUl],[词-caus])), [])')
        self.assertEqual(match(e[0],'mu\u0308lu\u0308u\u0308','form',True)[0],[0,1])
        self.assertFalse(match(e[0],'uul','morpheme',True,True)[1])
        self.assertTrue(match(e[0],'uul','morpheme',True,False)[1])

    def test_prefix_suffix(self):
        e,_=parse('#pass([abc end], (([« a-UUl. »],[词-caus]),), [翻译结束])')
        self.assertTrue(match(e[0],'a-','form',mode='prefix')[1])
        self.assertFalse(match(e[0],'UUl','form',mode='prefix')[1])
        self.assertTrue(match(e[0],'uul','form',mode='suffix')[1])
        self.assertFalse(match(e[0],'uul','form',case=True,mode='suffix')[1])
        self.assertTrue(match(e[0],'end','ipa',mode='suffix')[1])
        self.assertTrue(match(e[0],'ca','gloss',mode='prefix')[1])

    def test_bad_input_reported(self):
        e,errors=parse('#pass([], (([a], bad)), [])')
        self.assertEqual(len(e),0)
        self.assertEqual(errors[0]['line'],1)

    def test_empty_edited_entry(self):
        e={'function':'pass','ipa':'','words':[],'translation':'','edited':True}
        parsed,errors=parse(export_entry(e))
        self.assertEqual(errors,[])
        self.assertEqual(parsed[0]['words'],[])


if __name__=='__main__':
    unittest.main()
