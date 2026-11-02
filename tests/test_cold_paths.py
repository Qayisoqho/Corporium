"""Cold search/statistics reuse must preserve fields, identities and counts."""
import copy
import json
import unittest
from unittest.mock import patch
import corpus
import corpus_statistics
import dictionary_search
import server
import test_vocabulary_statistics


class ColdPathTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','entry','undo','m','bind'):
        locals()[name]=getattr(test_vocabulary_statistics.VocabularyTests,name)

    def test_word_sequence_cache_preserves_leaves_catalog_and_changes(self):
        with server.connect(audit=False) as db:
            index=dictionary_search.SearchIndex(db,'ordos',[],query='needle')
            words=[dict(form='a#sup[h]',gloss='go.PST',form_kind='plain',gloss_kind='plain'),
                   dict(form='na',gloss='N',notes='needle',features=[],orthographies=[dict(label='writing',text='é')])]
            body=dict(ipa='IPA',translation='translation',words=words,notes='note')
            def doc():return index.document(dict(id='',headword='',body=body),include_extra=False,prefix=('examples',),all_only=True,field_catalog={})
            expected=index.document(dict(id='',headword='',body=body),include_extra=False,prefix=('examples',))['all']
            first=doc();self.assertEqual(first['all'],expected);self.assertEqual(len(index.word_sequences),1)
            index.word_values.clear();index.word_value_bytes=0
            # all_only is the evidence-membership path: its all leaves and
            # field catalog are authoritative, not per-field value lists.
            second=doc();self.assertEqual(second['all'],first['all']);self.assertFalse(index.word_values)
            # Cached leaf collections are private; modifying a caller's list
            # cannot poison later matches or field discovery.
            second['all'].clear();self.assertEqual(doc()['all'],first['all'])
            changed=copy.deepcopy(body);changed['words'][1]['notes']='changed';body=changed
            self.assertIn('changed',doc()['all']);self.assertNotIn('needle',doc()['all'])
            self.assertTrue(any('orthographies' in name for name in index.fields))
            for n in range(300):
                body['words'][0]['form']='unique'+str(n);doc()
                self.assertLessEqual(index.word_sequence_bytes,4*1024**2)
                self.assertLessEqual(len(index.word_sequences),256)

    def test_sentence_citations_need_no_structural_parsing(self):
        target=self.entry('word','N')
        self.api('example-save',dict(body=dict(ipa='IPA',translation='T',words=[dict(form='word',gloss='N')],targets=[dict(lexeme_id=target['id'])])))
        with server.connect(audit=False) as db,patch.object(corpus,'analyze',side_effect=AssertionError('sentence citation has no unit reference')):
            result=corpus_statistics.calculate(db,'ordos',corpus_statistics.normalize({'mode':'independent'}))
        self.assertEqual((result['words'],result['types'],result['morpheme_words']),(1,1,0))

    def test_evidence_prefilter_keeps_unicode_mapped_names_enums_and_escapes(self):
        with server.connect(audit=False) as db:
            index=dictionary_search.SearchIndex(db,'ordos',[],query='unused')
            # Namespaces can share an identifier; no later catalog may conceal
            # a matching name used by a different field.
            index.names['shared']='North'
            index.people['shared']='Alice'
            index.tags['shared']=dict(symbol='PST',description='Past tense',aliases=['preterite'])
            odd='quoted"\\é';index.names[odd]='Odd name'
            body=dict(ipa='Straße',translation='e\u0301',notes='a"b \\path a\nb',entry_type='root',flag=True,
                      relation=dict(base_id='shared'),other=dict(base_id=odd),speakers=['shared'],
                      words=[dict(form='na#sup[h]',gloss='ROOT',features=['shared'])])
            full=index.document(dict(id='',headword='',body=body),include_extra=False,prefix=('examples',))['all']
            for case in (True,False):
                norm=lambda v:__import__('unicodedata').normalize('NFC',v) if case else __import__('unicodedata').normalize('NFC',v).casefold()
                for query in ('North','Alice','PST','preterite','Odd','STRASSE','é','词根','是','a"b','\\path','a\nb','na#sup[h]','neverappears'):
                    needle=norm(query)
                    possible=dictionary_search.EvidencePrefilter(index,needle,case).possible(body)
                    if any(needle in norm(v) for v in full):self.assertTrue(possible,(case,query))
                    if query=='neverappears':self.assertFalse(possible)

    def test_prefilter_negative_does_not_poison_a_later_evidence_query(self):
        root=self.m('na');src=self.source('corpus',[('na','ROOT')]);self.bind(src,root)
        self.assertEqual(self.api('morphemes?q=neverappears')['total'],0)
        result=self.api('morphemes?q=translation')
        self.assertEqual([r['id'] for r in result['items']],[root['id']])

    def test_raw_prefilter_requires_unescaped_text_and_canonical_numeric_fallback(self):
        with server.connect(audit=False) as db:
            index=dictionary_search.SearchIndex(db,'ordos',[],query='unused')
            index.names['source-id']='North'
            body=dict(ipa='Straße',translation='é',words=[dict(form='lemma42',gloss='N')],relation=dict(base_id='source-id'))
            source=json.dumps(body,ensure_ascii=False,indent=2)
            full=index.document(dict(id='',headword='',body=body),include_extra=False,prefix=('examples',))['all']
            for needle in ('lemma42','north','strasse','é','neverappears'):
                f=dictionary_search.EvidencePrefilter(index,needle,False)
                self.assertTrue(f.raw_allowed(body,source))
                self.assertEqual(f.possible(body,source),f.possible(body))
                if any(needle in value.casefold() for value in full):self.assertTrue(f.possible(body,source))
            escaped=json.dumps(body,ensure_ascii=True)
            self.assertFalse(dictionary_search.EvidencePrefilter(index,'lemma42',False).raw_allowed(body,escaped))
            raw='{"words":[],"value":1.23456789123456789123456789}'
            numbers=json.loads(raw);needle=str(numbers['value'])
            f=dictionary_search.EvidencePrefilter(index,needle,False)
            self.assertFalse(f.raw_allowed(numbers,raw));self.assertTrue(f.possible(numbers))
            composed={**body,'gloss':'go','gloss_addition':'PST'}
            self.assertFalse(dictionary_search.EvidencePrefilter(index,'go.pst',False).raw_allowed(composed,json.dumps(composed)))

    def test_broad_query_word_proof_uses_only_visible_effective_forms_and_glosses(self):
        with server.connect(audit=False) as db:
            index=dictionary_search.SearchIndex(db,'ordos',[],query='unused')
            f=dictionary_search.EvidencePrefilter(index,'strasse',False)
            body=dict(ipa='',translation='',words=[dict(form='Straße',gloss='N')])
            original=copy.deepcopy(body)
            for _ in range(64):self.assertTrue(f.possible(body))
            self.assertTrue(f.broad);self.assertTrue(f.visible_word_hit(body));self.assertEqual(body,original)
            self.assertFalse(f.visible_word_hit(dict(words=[dict(form='other',gloss='N',notes='STRASSE')],notes='STRASSE')))

    def test_independent_analysis_reuse_matches_full_parsing_without_shared_identity(self):
        root=self.m('na')
        for gloss in ('ROOT','ROOT '):
            src=self.source('independent',[('na-na',gloss+'-ROOT'),('na','ROOT')])
            self.bind(src,root,word=1)
        scope=corpus_statistics.normalize({'mode':'independent'})
        analyze=corpus.analyze
        with server.connect(audit=False) as db:
            fast=corpus_statistics.calculate(db,'ordos',scope)
        with server.connect(audit=False) as db,patch.object(corpus,'analyze',side_effect=lambda body,**kw:analyze(body)):
            full=corpus_statistics.calculate(db,'ordos',scope)
        self.assertEqual(json.dumps(fast,ensure_ascii=False,sort_keys=True),json.dumps(full,ensure_ascii=False,sort_keys=True))
        self.assertEqual(fast['morpheme_words'],2)


if __name__=='__main__':unittest.main()
