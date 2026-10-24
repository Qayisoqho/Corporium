"""Semantic and transaction guards for the optimized read/write paths."""
import copy
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import server
import corpus
import languages
import lexicon
import journal
import gloss_inheritance
import test_text_tools


class PerformancePathsTests(unittest.TestCase):
    setUp=test_text_tools.TextToolsTests.setUp
    tearDown=test_text_tools.TextToolsTests.tearDown
    call=test_text_tools.TextToolsTests.call
    seed=test_text_tools.TextToolsTests.seed
    entries=test_text_tools.TextToolsTests.entries
    word=test_text_tools.TextToolsTests.word
    link=test_text_tools.TextToolsTests.link
    plan=test_text_tools.TextToolsTests.plan
    apply=test_text_tools.TextToolsTests.apply
    undo=test_text_tools.TextToolsTests.undo

    def test_search_matches_eager_reference_and_only_expands_page(self):
        self.seed('\n'.join(f'#pass([IPA {i}], (([ger-n],[家-GEN]),([so<l>ma],[home<PL>]),([#],[#])), [译文 {i}])' for i in range(23)))
        with server.connect() as db:
            catalogue={r['id']:dict(r) for r in db.execute('SELECT * FROM languages')}
            entries=[languages.annotate(json.loads(r['body']),'ordos',catalogue) for r in db.execute('SELECT body FROM entries ORDER BY position')]
        for field,query in [('all','ger'),('form','ger'),('morpheme','l'),('gloss','GEN'),('ipa','IPA 2'),('translation','译文'),('notes','absent')]:
            for mode in ('contains','exact','prefix','suffix'):
                for case in (True,False):
                    expected=[corpus.match(copy.deepcopy(e),query,field,case=case,mode=mode) for e in entries]
                    q=dict(field=field,q=query,mode=mode,case=str(case).lower(),page=2,page_size=10)
                    code,result=self.call('/api/entries?'+urlencode(q))
                    self.assertEqual(code,200,result)
                    hits=[h for h,ok in expected if ok]
                    self.assertEqual(result['total'],len(hits));self.assertEqual(result['tokens'],sum(map(len,hits)))
                    start=(result['page']-1)*10
                    self.assertEqual([e['hits'] for e in result['items']],hits[start:start+10])
        with patch.object(languages,'annotate',wraps=languages.annotate) as annotate:
            result=self.call('/api/entries?page=999&page_size=10')[1]
            self.assertEqual((result['page'],result['total'],len(result['items'])),(3,23,3))
            self.assertEqual(annotate.call_count,3)
        result=self.call('/api/entries?warnings=true&page_size=100')[1]
        self.assertEqual(result['total'],sum(bool(e['warnings']) for e in entries))

    def test_translation_preserves_unit_rows_and_stale_dependencies(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        with server.connect() as db:
            units=[tuple(r) for r in db.execute('SELECT * FROM corpus_units ORDER BY id')]
            segments=[tuple(r) for r in db.execute('SELECT * FROM unit_segments ORDER BY id')]
        b,p=self.plan(e,'translation',e['translation'],'new translation')
        self.assertEqual(self.apply(b,p)[0],200)
        # Binding preparation may consult sync_entry; the persisted units and
        # segment snapshots, including their revisions, must stay unchanged.
        with server.connect() as db:
            self.assertEqual(units,[tuple(r) for r in db.execute('SELECT * FROM corpus_units ORDER BY id')])
            self.assertEqual(segments,[tuple(r) for r in db.execute('SELECT * FROM unit_segments ORDER BY id')])
        self.assertEqual(self.undo()[0],200)
        b,p=self.plan(e,'form','home','house')
        # Even a dependency change that does not bump the sentence revision invalidates the token.
        with server.connect() as db:
            db.execute("UPDATE morphology_analyses SET features='[\"changed\"]'")
        self.assertEqual(self.apply(b,p)[0],400)

    def test_selective_validation_rolls_back_dangling_unit(self):
        e=self.seed();x=self.word();uid=e['words'][0]['unit_id'];self.link(uid,x)
        token=journal.action.set('test deletion')
        try:
            with self.assertRaises(ValueError):
                with server.connect() as db:db.execute('DELETE FROM corpus_units WHERE id=?',(uid,))
        finally:journal.action.reset(token)
        with server.connect() as db:self.assertIsNotNone(db.execute('SELECT id FROM corpus_units WHERE id=?',(uid,)).fetchone())

    def test_second_change_after_explicit_sync_is_not_skipped(self):
        e=self.seed();token=journal.action.set('test synchronization')
        try:
            with server.connect() as db:
                b=json.loads(db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0])
                b['words'][0]['form']='first'
                db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(b),e['id']))
                lexicon.sync_entry(db,e['id'])
                b['words'][0]['form']='second'
                db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(b),e['id']))
        finally:journal.action.reset(token)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT form FROM corpus_units WHERE entry_id=? AND kind='word' AND active=1 ORDER BY position",(e['id'],)).fetchone()[0],'second')

    def test_analysis_reuse_never_overrides_a_different_stored_snapshot(self):
        e=self.seed()
        with server.connect(audit=False) as db:
            row=db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()
            stale=corpus.analyze(json.loads(row['body']))
            fresh=copy.deepcopy(stale);fresh['words'][0]['form']='updated'
            db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(fresh,ensure_ascii=False),e['id']))
            lexicon.sync_entry(db,e['id'],analyzed_body=stale)
            self.assertEqual(db.execute("SELECT form FROM corpus_units WHERE entry_id=? AND kind='word' AND active=1 ORDER BY position",(e['id'],)).fetchone()[0],'updated')

    def test_dictionary_meaning_keeps_legacy_snapshots_and_units_intact(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        with server.connect(audit=False) as db:
            untouched=db.execute("SELECT s.id,s.body FROM unit_segments s JOIN corpus_units m ON m.id=s.id JOIN corpus_units w ON w.id=m.parent_id WHERE w.entry_id=? AND w.position=1 LIMIT 1",(e['id'],)).fetchone()
            body=json.loads(untouched['body']);body.pop('gloss_fragments',None)
            saved=json.dumps(body,ensure_ascii=False)
            db.execute('UPDATE unit_segments SET body=? WHERE id=?',(saved,untouched['id']))
            units=[tuple(r) for r in db.execute('SELECT * FROM corpus_units ORDER BY id')]
        x['body']['usages'][0]['senses'][0]['short_gloss']='改义'
        code,result=self.call('/api/lexeme-save',x);self.assertEqual(code,200,result)
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT body FROM unit_segments WHERE id=?',(untouched['id'],)).fetchone()[0],saved)
            self.assertEqual(units,[tuple(r) for r in db.execute('SELECT * FROM corpus_units ORDER BY id')])
            raw=db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0]
            self.assertEqual(gloss_inheritance.load(db,'corpus',e['id'],raw)['words'][0]['gloss'],'改义-GEN')

    def test_dictionary_meaning_inherits_without_expanding_untouched_source_words(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        with server.connect(audit=False) as db:
            body=json.loads(db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0])
            untouched={k:body['words'][1][k] for k in ('form','gloss')}
            body['words'][1]=untouched
            db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(body,ensure_ascii=False),e['id']))
            original=body['words'][0]['gloss']
        x['body']['usages'][0]['senses'][0]['short_gloss']='改义'
        code,result=self.call('/api/lexeme-save',x);self.assertEqual(code,200,result)
        with server.connect(audit=False) as db:
            stored=json.loads(db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0])
            self.assertEqual(stored['words'][1],untouched)
            self.assertEqual(stored['words'][0]['gloss'],original)
            self.assertEqual(gloss_inheritance.load(db,'corpus',e['id'],stored)['words'][0]['gloss'],'改义-GEN')

    def test_new_dictionary_target_does_not_scan_unrelated_occurrence_analyses(self):
        self.seed();statements=[];token=journal.action.set('scoped new word')
        try:
            with server.connect() as db:
                db.set_trace_callback(statements.append)
                lexicon.mutate(db,'lexeme-save',dict(headword='fresh',body=dict(usages=[dict(senses=[dict(short_gloss='new')])])),'ordos')
        finally:journal.action.reset(token)
        self.assertFalse(any(s.startswith('SELECT DISTINCT l.lexeme_id,a.form_id,a.features') and ' WHERE ' not in s for s in statements))

    def test_scoped_link_deletion_still_rejects_orphan_analysis(self):
        e=self.seed();x=self.word();uid=e['words'][0]['unit_id'];self.link(uid,x)
        token=journal.action.set('invalid link deletion')
        try:
            with self.assertRaisesRegex(ValueError,'形态分析|依赖记录'):
                with server.connect() as db:db.execute('DELETE FROM lexical_links WHERE unit_id=?',(uid,))
        finally:journal.action.reset(token)
        with server.connect(audit=False) as db:self.assertIsNotNone(db.execute('SELECT id FROM lexical_links WHERE unit_id=?',(uid,)).fetchone())

    def test_undo_new_target_cannot_remove_an_external_reference(self):
        e=self.seed();x=self.word();u=x['body']['usages'][0]
        with server.connect(audit=False) as db:
            db.execute('INSERT INTO lexical_links VALUES(?,?,?,?,?,?,?,1)',('external-link',e['words'][0]['unit_id'],x['id'],u['id'],u['senses'][0]['id'],'','ordos'))
        self.assertEqual(self.undo()[0],400)
        with server.connect(audit=False) as db:self.assertIsNotNone(db.execute('SELECT id FROM lexemes WHERE id=?',(x['id'],)).fetchone())
