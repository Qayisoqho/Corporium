import copy
import json
import sqlite3
import unittest
from contextlib import closing,nullcontext
from unittest.mock import patch

import grammar
import grammar_audit_cache as cache
import server
import test_grammar


class AuditSpeedTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','tag','word','link','undo','example'):
        locals()[name]=getattr(test_grammar.GrammarTests,name)

    def audit(self,**q):
        from urllib.parse import urlencode
        code,r=self.call('/api/grammar-audit?'+urlencode(dict(language='ordos',reuse='1',**q)));self.assertEqual(code,200,r);return r

    def fresh(self,**q):
        from urllib.parse import urlencode
        code,r=self.call('/api/grammar-audit?'+urlencode(dict(language='ordos',reuse='0',**q)));self.assertEqual(code,200,r);return r

    def test_new_tag_alias_rename_ignore_and_delete_reclassify_without_source_scan(self):
        self.seed('#pass([], (([home-x],[house-PL]),([p],[1SG.nom]),([l],[NOM.GEN]),([z],[all])), [])')
        self.audit()
        for mode in ('delete','wal'):
            with self.subTest(mode=mode):
                with server.connect(audit=False) as db:db.execute('PRAGMA journal_mode='+mode)
                self.audit()
                with (patch.object(grammar,'analyze',side_effect=AssertionError('tag edit rescanned source')) if mode=='delete' else nullcontext()):
                    tag=self.tag('pl',aliases=['PLURAL'])
                    current=self.audit()
                self.assertEqual(current,self.fresh())
                for values in [dict(description='description',category='number'),dict(symbol='plural',aliases=['PL']),dict(symbol='plural',aliases=['PL','NOM'])]:
                    code,_=self.call('/api/grammar-save',{**tag,**values});self.assertEqual(code,200)
                    with (patch.object(grammar,'analyze',side_effect=AssertionError('tag edit rescanned source')) if mode=='delete' else nullcontext()):current=self.audit(lower='true')
                    self.assertEqual(current,self.fresh(lower='true'))
                    tag=next(t for t in self.call('/api/grammar-tags?language=ordos')[1] if t['id']==tag['id'])
                code,_=self.call('/api/grammar-delete',{**tag,'confirmed':True});self.assertEqual(code,200)
                with (patch.object(grammar,'analyze',side_effect=AssertionError('delete rescanned source')) if mode=='delete' else nullcontext()):current=self.audit()
                self.assertEqual(current,self.fresh())
                code,_=self.call('/api/grammar-ignore',dict(items=[dict(symbol='PL')]));self.assertEqual(code,200)
                with (patch.object(grammar,'analyze',side_effect=AssertionError('ignore rescanned source')) if mode=='delete' else nullcontext()):current=self.audit()
                self.assertEqual(current,self.fresh())
                code,_=self.call('/api/grammar-unignore',dict(items=[dict(symbol='PL')]));self.assertEqual(code,200)

    def test_tag_only_promotion_rejects_external_commit_after_our_save(self):
        self.seed('#pass([], (([x],[PL])), [])')
        for mode in ('delete','wal'):
            with server.connect(audit=False) as db:db.execute('PRAGMA journal_mode='+mode)
            self.audit();real=cache.promote
            def raced(db,proof,changes):
                with closing(sqlite3.connect(server.DB)) as writer:
                    writer.execute("UPDATE entries SET body=json_set(body,'$.words[0].gloss','NOM')");writer.commit()
                real(db,proof,changes)
            with patch.object(cache,'promote',raced):tag=self.tag('PL')
            with patch.object(grammar,'analyze',wraps=grammar.analyze) as analyze:current=self.audit()
            self.assertTrue(analyze.called);self.assertEqual(current,self.fresh())
            self.assertIn('NOM',[u['symbol'] for u in current['unknown']])
            self.call('/api/grammar-delete',{**tag,'confirmed':True})

    def test_batch_registration_and_ignore_reuse_source_facts(self):
        self.seed('#pass([], (([a-b],[NOM-PL]),([c],[PST])), [])');self.audit()
        code,r=self.call('/api/grammar-register-batch',dict(items=[dict(symbol='NOM'),dict(symbol='PL')]))
        self.assertEqual(code,200,r)
        with patch.object(grammar,'analyze',side_effect=AssertionError('batch registration rescanned sources')):current=self.audit()
        self.assertEqual(current,self.fresh())
        self.assertEqual(self.call('/api/grammar-ignore',dict(items=[dict(symbol='PST')]))[0],200)
        with patch.object(grammar,'analyze',side_effect=AssertionError('ignore rescanned sources')):current=self.audit()
        self.assertEqual(current,self.fresh())

    def test_source_edit_undo_and_dictionary_meaning_changes_invalidate_facts(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x);self.audit()
        e=self.entries()[0];e['notes']='changed';code,_=self.call('/api/save',e);self.assertEqual(code,200)
        with patch.object(grammar,'analyze',wraps=grammar.analyze) as analyze:current=self.audit()
        self.assertTrue(analyze.called);self.assertEqual(current,self.fresh())
        self.undo();self.assertEqual(self.audit(),self.fresh())
        x=self.call('/api/lexeme?id='+x['id'])[1];x['body']['usages'][0]['senses'][0]['short_gloss']='PL'
        self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        self.assertEqual(self.audit(),self.fresh())

    def test_usage_cards_are_independent_of_private_analysis_and_fact_cache(self):
        self.seed('\n'.join('#pass([], (([a],[NOM]),([a],[NOM])), [])' for _ in range(25)))
        tag=self.tag('NOM');self.audit()
        current=self.audit(issue='usage',tag=tag['id']);expected=self.fresh(issue='usage',tag=tag['id'])
        self.assertEqual(current,expected)
        current['items'][0]['body']['words'][0]['morphemes'].clear()
        self.assertEqual(self.audit(issue='usage',tag=tag['id']),expected)
        self.assertEqual(self.audit(issue='usage',tag=tag['id'],page='2'),self.fresh(issue='usage',tag=tag['id'],page='2'))

    def test_mixed_write_and_failed_save_never_promote(self):
        self.seed();tag=self.tag('PL');self.audit()
        import journal
        token=journal.action.set(journal.LABELS['/api/grammar-save'])
        try:
            with server.connect() as db:
                db.execute("UPDATE grammar_tags SET description='mixed',revision=revision+1 WHERE id=?",(tag['id'],))
                db.execute("UPDATE entries SET body=json_set(body,'$.words[0].gloss','NOM')")
        finally:journal.action.reset(token)
        self.assertEqual(self.audit(),self.fresh())
        before=self.audit()
        self.assertEqual(self.call('/api/grammar-save',{**tag,'revision':-1})[0],400)
        self.assertEqual(self.audit(),before)

    def test_private_word_cache_matches_full_analysis_and_bounds_memory(self):
        words=[dict(form='so<l>ma',gloss='home<neg#sub[POT]>'),dict(form='x',gloss=''),dict(form='#',gloss=''),dict(form='，',gloss='',punctuation=True,punctuation_form='，'),dict(form='a-b',gloss='PL')]
        cache_=grammar.AuditAnalysisCache(limit=25000,items=2)
        for n,w in enumerate(words*3):
            a=grammar.corpus.analyze(dict(ipa='',translation='',words=[copy.deepcopy(w)]))['words'][0]
            b=copy.deepcopy(w);cache_.apply(b,n)
            self.assertEqual(b,a);self.assertLessEqual(cache_.bytes,25000);self.assertLessEqual(len(cache_.values),2)

    def test_orphan_links_keep_lexeme_then_morpheme_order_and_source_scope(self):
        e=self.seed('#pass([], (([a],[A]),([b],[B])), [])');x=self.word()
        code,m=self.call('/api/morpheme-save',dict(form='b',body=dict(gloss='B',entry_type='root')));self.assertEqual(code,200,m)
        m=self.call('/api/lexeme?id='+m['id'])[1]
        self.link(e['words'][1]['unit_id'],m);self.link(e['words'][0]['unit_id'],x)
        with server.connect(audit=False) as db:db.execute('DELETE FROM entries WHERE id=?',(e['id'],))
        items=self.audit(issue='link')['items']
        self.assertEqual([i['linked_lexeme'] for i in items],[x['id'],m['id']])
        self.assertTrue(all(i['deleted'] for i in items))
        self.assertEqual(self.audit(source='independent')['total'],0)


if __name__=='__main__':unittest.main()
