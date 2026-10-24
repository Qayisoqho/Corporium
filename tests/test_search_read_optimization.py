import copy
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import corpus
import evidence_index
import gloss_inheritance as gloss
import lexicon
import server
import test_gloss_inheritance as inheritance


class QueryMatcherTests(unittest.TestCase):
    def test_reuse_keeps_unicode_scripts_boundaries_modes_and_positions(self):
        body=dict(ipa='e\u0301 IPA',translation='Straße',notes='notes',language_notes='GEN note',text_notes='text',words=[
            dict(form=f,gloss=g) for f,g in [('a','GEN.SG'),('a','GEN.SG'),('a',''),('#','GEN'),('\\#','GEN'),
            ('root-n','house-GEN'),('so<l>ma','home<GEN>.SG'),('x','#sub[GEN]'),('x','[GEN.SG]'),('é','e\u0301'),('s','Straße')]])
        for field in ('gloss','form','morpheme','all','ipa','translation','notes'):
            for query in ('GEN','gen','SG','é','STRASSE','absent',''):
                for mode in ('contains','exact','prefix','suffix',None):
                    for case in (True,False):
                        matcher=corpus.QueryMatcher(query,field,True,case,mode)
                        expected=corpus.match(copy.deepcopy(body),query,field,True,case,mode)
                        for _ in range(2):self.assertEqual(matcher(copy.deepcopy(body)),expected,(field,query,mode,case))
        matcher=corpus.QueryMatcher('GEN','gloss')
        self.assertEqual(matcher(dict(words=[dict(form='a',gloss='GEN')]*3)),([0,1,2],True))
        self.assertEqual(matcher(dict(words=[dict(form='#',gloss='GEN')])),([],False))
        self.assertEqual(matcher(dict(words=[dict(form='a',gloss='PST')])),([],False))

    def test_cache_is_bounded_and_does_not_retain_oversize_inputs(self):
        matcher=corpus.QueryMatcher('GEN','gloss',max_entries=3,max_bytes=1024)
        for i in range(50):
            b=dict(words=[dict(form=str(i),gloss='GEN')])
            self.assertEqual(matcher(b),corpus.match(b,'GEN','gloss'))
            self.assertLessEqual(len(matcher.hits),3);self.assertLessEqual(matcher.bytes,1024)
        huge=dict(words=[dict(form='x'*5000,gloss='GEN')]);before=matcher.bytes
        self.assertEqual(matcher(huge),([0],True));self.assertEqual(matcher.bytes,before)
        self.assertTrue(all(len(k[0])<5000 for k in matcher.hits))
        self.assertEqual(corpus.QueryMatcher('PST','gloss')(dict(words=[dict(form='a',gloss='GEN')])),([],False))


class EvidenceReadTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','undo','api','word','example','detail','link','fixture','change','mode'):
        locals()[name]=getattr(inheritance.GlossInheritanceTests,name)

    def search(self,q):
        return self.api('lexemes?'+urlencode(dict(language='ordos',q=q,summary=1,page_size='all')))

    def shared_fixture(self):
        e,ex,x=self.fixture();other=self.word('free',['FREE'])
        for kind,row in [('corpus',e),('independent',ex)]:self.link(row,other,'@word',word=1,kind=kind)
        return e,ex,x,other

    def test_warm_documents_check_narrow_versions_without_loading_slots_or_bindings(self):
        e,ex,x=self.fixture()
        with evidence_index._lock:evidence_index._indexes.clear()
        with patch.object(gloss,'revisions',wraps=gloss.revisions) as versions:
            expected=self.search('家')
            self.assertTrue(versions.called)
        with server.connect(audit=False) as db:
            statements=[];db.set_trace_callback(statements.append)
            with patch.object(gloss,'load',side_effect=AssertionError('validated document needs no render')):
                actual=lexicon.list_lexemes(db,'ordos','家',page_size='all',summary=True)
        self.assertEqual(actual,expected)
        self.assertTrue(any('SELECT b.owner_id,b.id,b.revision' in s for s in statements))
        self.assertFalse(any('SELECT b.*' in s or 'SELECT id,position FROM corpus_units' in s for s in statements))

    def test_only_changed_documents_prepare_full_bindings_after_local_override(self):
        e,ex,x,other=self.shared_fixture();third=self.example([('third','OTHER')]);z=self.word('third',['OTHER']);self.link(third,z,'@word',kind='independent')
        self.search('家')
        for kind,row in [('corpus',e),('independent',ex)]:self.mode(kind,row,'override','新住所')
        prepared=[];prefetch=gloss.prefetch
        def observe(db,kind,ids,**kwargs):
            ids=list(ids)
            if kwargs.get('changed_only'):prepared.extend((kind,rid) for rid in ids)
            return prefetch(db,kind,ids,**kwargs)
        with patch.object(gloss,'prefetch',side_effect=observe):result=self.search('新住所')
        self.assertEqual({r['id'] for r in result['items']},{x['id'],other['id']})
        self.assertEqual(set(prepared),{('corpus',e['id']),('independent',ex['id'])})

    def test_catalog_meaning_edit_keeps_its_existing_global_invalidation(self):
        e,ex,x,other=self.shared_fixture();self.search('家');self.change(x,'新住所')
        self.assertEqual({r['id'] for r in self.search('新住所')['items']},{x['id'],other['id']})

    def test_partial_cache_and_eviction_during_a_batch_keep_hits_and_field_catalog(self):
        e,ex,x=self.fixture()
        with server.connect(audit=False) as db:
            source=json.loads(db.execute('SELECT body FROM dictionary_examples WHERE id=?',(ex['id'],)).fetchone()[0])
            for i in range(105):
                body=copy.deepcopy(source);body['notes']='特有证据'+str(i)
                db.execute('INSERT INTO dictionary_examples VALUES(?,?,?,1)',('extra'+str(i),'ordos',json.dumps(body)))
        expected=self.search('特有证据104')
        with evidence_index._lock:
            index=next(reversed(evidence_index._indexes.values()))
            # Keep some documents warm, force misses and evictions in the same
            # 100-row batch, including reuse of a hit after another is evicted.
            for key in list(index.records)[::3]:index.discard(key)
            index.limit=max(index.bytes//2,4096)
        self.assertEqual(self.search('特有证据104'),expected)
        self.assertEqual(self.search('特有证据104'),expected)
        self.assertLessEqual(index.bytes,index.limit)

    def test_cached_evidence_follows_override_restore_undo_and_redo(self):
        e,ex,x,other=self.shared_fixture();self.assertEqual(self.search('独有覆盖')['total'],0)
        for kind,row in [('corpus',e),('independent',ex)]:self.mode(kind,row,'override','独有覆盖')
        self.assertEqual({r['id'] for r in self.search('独有覆盖')['items']},{x['id'],other['id']})
        for kind,row in [('corpus',e),('independent',ex)]:self.mode(kind,row,'inherit')
        self.assertEqual(self.search('独有覆盖')['total'],0)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.search('独有覆盖')['total'],2)
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.search('独有覆盖')['total'],0)

    def test_unlink_keeps_frozen_evidence_but_removes_the_old_owner(self):
        e,ex,x,other=self.shared_fixture()
        for kind,row in [('corpus',e),('independent',ex)]:self.mode(kind,row,'override','冻结特例')
        self.assertEqual(self.search('冻结特例')['total'],2)
        d=self.detail(e);u=self.api('unit-dictionary?id='+d['body']['words'][0]['unit_id'])
        self.api('lexeme-unlink',dict(id=u['link']['id'],revision=u['link']['revision']))
        d=self.detail(ex,'independent');index=next(i for i,t in enumerate(d['body']['targets']) if t['lexeme_id']==x['id'])
        self.api('segmentation-link',dict(kind='independent',id=ex['id'],revision=d['revision'],remove_target=index))
        self.assertEqual([r['id'] for r in self.search('冻结特例')['items']],[other['id']])
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.search('冻结特例')['total'],2)
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.search('冻结特例')['total'],1)

    def test_batch_stamps_match_full_stamps_for_unbound_and_bound_owners(self):
        e,ex,x=self.fixture();self.mode('independent',ex,'override','')
        for kind,row in [('corpus',e),('independent',ex)]:
            with server.connect(audit=False) as db:
                batch=gloss.revisions(db,kind,[row['id'],'missing',row['id']])
                self.assertEqual(batch,{row['id']:gloss.revision(db,kind,row['id']),'missing':None})


if __name__=='__main__':unittest.main()
