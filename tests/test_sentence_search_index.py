"""SQL search must preserve the original readers, including their differences."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import annotations
import corpus
import corpus_search
import gloss_inheritance
import sentence_search_index as index
import server
import test_gloss_inheritance as inheritance


class SentenceSearchIndexTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','undo','api','word','example','detail','link','fixture','change','mode'):
        locals()[name] = getattr(inheritance.GlossInheritanceTests, name)

    def compare(self, query, library=False):
        with server.connect(audit=False) as db:
            fn = annotations.search if library else lambda db,q: corpus_search.search(db,q,q.get('language','ordos'))
            with patch.object(index, 'available', return_value=False):
                expected = fn(db, query)
            actual = fn(db, query)
            self.assertEqual(actual, expected, query)
            return actual

    def test_scalar_and_form_modes_unicode_scripts_short_and_literal_queries(self):
        self.seed('#pass([Straße é #sup[h] abcXYZ], (([root-n],[根-GEN]),([Straße],[路]),([é],[音]),([#],[边界]),([x#sub[2]],[x]),([so<l>ma],[home<PL>])), [家 PL a*b?c [x] 100%])')
        ex = self.example([('root-n','根-GEN'),('é','音')])
        with server.connect(audit=False) as db:
            for table in ('entries','dictionary_examples'):
                for row in db.execute('SELECT id,body FROM '+table).fetchall():
                    body=json.loads(row['body']);body['notes']='NUL\0tail %_ "quoted"';body['language_notes']='语言备注'
                    db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),row['id']))
        pairs=[('ipa',q) for q in ('STRASSE','é','h','abc','XYZ')]
        pairs += [('translation',q) for q in ('家','PL','a*b?c','[x]','100%','absent')]
        pairs += [('notes',q) for q in ('\0tail','%_','"quoted"','语言备注')]
        pairs += [('form',q) for q in ('root','root-n','STRASSE','é','#','x2','so<l>ma')]
        for field,term in pairs:
            for mode in ('contains','exact','prefix','suffix'):
                for case in ('true','false'):
                    q=dict(language='ordos',field=field,q=term,mode=mode,case=case,include_independent='true',page_size=10,page=99)
                    self.compare(q)
                    self.compare(dict(q,source='all'),library=True)

    def test_morpheme_forms_match_existing_parser_and_count_words_once(self):
        self.seed('#pass([], (([so<l>ma],[home<PL>]),([a+a],[A+A]),([#],[]),([x#sup[h]],[X]),([root-n],[root-GEN])), [])')
        self.example([('so<l>ma','home<PL>'),('a+a','A+A')])
        for term in ('so','l','ma','a','root','n','h','#','absent'):
            for mode in ('contains','exact','prefix','suffix'):
                q=dict(language='ordos',field='morpheme',q=term,mode=mode,include_independent='true',page_size=10)
                self.compare(q);self.compare(dict(q,source='all'),library=True)

    def test_text_notes_are_shared_but_library_retains_its_existing_scope(self):
        e=self.seed();self.example([('home','家')])
        with server.connect(audit=False) as db:
            db.execute('INSERT INTO text_info(text_id,metadata) VALUES(?,?) ON CONFLICT(text_id) DO UPDATE SET metadata=excluded.metadata',(e['text_id'],json.dumps(dict(notes='text-only'))))
        q=dict(language='ordos',field='notes',q='text-only',include_independent='true')
        self.assertEqual(self.compare(q)['total'],1)
        self.assertEqual(self.compare(dict(q,source='all'),True)['total'],0)
        self.assertEqual(self.undo()[0],200)

    def test_postings_follow_external_edits_deletion_and_rollback(self):
        e=self.seed();self.compare(dict(field='translation',q='translation'))
        with server.connect(audit=False) as db:
            before=db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0]
            body=json.loads(before);body['translation']='new external'
            db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(body),e['id']))
        self.assertEqual(self.compare(dict(field='translation',q='new external'))['total'],1)
        with server.connect(audit=False) as db:
            db.execute('BEGIN');db.execute('DELETE FROM entries WHERE id=?',(e['id'],))
            self.assertEqual(corpus_search.search(db,dict(field='translation',q='new external'),'ordos')['total'],0)
            db.rollback()
        self.assertEqual(self.compare(dict(field='translation',q='new external'))['total'],1)

    def test_meaning_and_override_edits_keep_forms_and_display_current_gloss(self):
        e,ex,x=self.fixture();self.change(x,'住所')
        for field,term in [('form','home'),('morpheme','home')]:
            r=self.compare(dict(field=field,q=term,include_independent='true'))
            self.assertEqual({w['words'][0]['gloss'] for w in r['items']},{'住所.SG'})
        self.mode('independent',ex,'override','本句')
        self.compare(dict(field='morpheme',q='home',include_independent='true'))
        self.assertEqual(self.undo()[0],200)
        self.compare(dict(field='morpheme',q='home',include_independent='true'))
        self.assertEqual(self.undo('redo')[0],200)
        self.compare(dict(field='morpheme',q='home',include_independent='true'))

    def test_repeated_queries_only_decode_visible_sentence_bodies(self):
        self.seed('\n'.join('#pass([unique ipa '+str(i)+'], (([root-n],[root-GEN])), [sentence '+str(i)+'])' for i in range(45)))
        self.compare(dict(field='form',q='root'))
        self.compare(dict(field='morpheme',q='root'))
        for field,term in [('form','root'),('morpheme','root'),('ipa','unique'),('translation','sentence')]:
            with patch.object(corpus,'QueryMatcher',side_effect=AssertionError('normal SQL search must not run the scan matcher')):
                r=self.api('entries?'+urlencode(dict(field=field,q=term,page=2,page_size=10)))
            self.assertEqual((r['total'],r['page'],len(r['items'])),(45,2,10))
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sentence_search_dirty WHERE basic=1 OR morph=1').fetchone()[0],0)

    def test_short_queries_and_no_fts_keep_literal_matching(self):
        self.seed('#pass([a*b Straße], (([é],[音]),([x],[X])), [家 PL])')
        with server.connect(audit=False) as db:
            index.refresh(db,'form');db.execute('DROP TABLE sentence_search_fts')
        for field,term in [('ipa','a*b'),('ipa','STRASSE'),('translation','家'),('translation','PL')]:
            self.compare(dict(field=field,q=term))

    def test_snapshot_removes_search_tables_and_triggers_and_rebuilds(self):
        self.seed();self.compare(dict(field='morpheme',q='home'))
        with server.connect(audit=False) as db:
            target=sqlite3.connect(':memory:');target.row_factory=sqlite3.Row
            try:
                db.backup(target);index.drop(target)
                self.assertFalse(target.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'sentence_search_%'").fetchone())
                index.initialize(target)
                self.assertGreater(target.execute('SELECT count(*) FROM sentence_search_dirty').fetchone()[0],0)
            finally:target.close()

    def test_language_scope_and_same_id_in_both_sentence_kinds(self):
        e=self.seed();ex=self.example([('home-n','家-GEN')])
        other=self.api('save-language',dict(name='Second language',metadata={}))['id']
        with server.connect(audit=False) as db:
            row=db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()
            body=json.loads(row['body']);body['language_id']=other
            db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(body),e['id']))
            db.execute('UPDATE dictionary_examples SET id=? WHERE id=?',(e['id'],ex['id']))
        for lid in ('ordos',other,'all'):
            for field,term in [('ipa','ipa'),('form','home'),('morpheme','n')]:
                q=dict(language=lid,field=field,q=term,include_independent='true')
                self.compare(q)
                self.compare(dict(q,source='all'),library=True)

    def test_missing_fts_rebuilds_existing_values_on_reinitialize(self):
        self.seed();self.compare(dict(field='translation',q='translation'))
        with server.connect(audit=False) as db:
            db.execute('DROP TABLE sentence_search_fts');index.initialize(db)
        self.assertEqual(self.compare(dict(field='translation',q='translation'))['total'],1)

    def test_index_task_publishes_atomically_without_business_history(self):
        import long_tasks,journal
        self.seed()
        with server.connect(audit=False) as db:
            revision=journal.workspace_revision(db)
        job=long_tasks.submit(server.DB,'sentence-index',dict(language='ordos',field='form'))
        long_tasks.JOBS[job]['future'].result(timeout=20)
        self.assertEqual(long_tasks.view(server.DB,job)['state'],'done')
        with server.connect(audit=False) as db:
            self.assertEqual(journal.workspace_revision(db),revision)
            self.assertEqual(index.pending(db,'form'),0)
            before=[tuple(r) for r in db.execute('SELECT * FROM sentence_search_dirty')]
        def cancel(db,field):
            db.execute('UPDATE sentence_search_dirty SET morph=0')
            raise long_tasks.Cancelled()
        with patch.object(index,'refresh',side_effect=cancel):
            job=long_tasks.submit(server.DB,'sentence-index',dict(language='ordos',field='morpheme'))
            long_tasks.JOBS[job]['future'].result(timeout=20)
        self.assertEqual(long_tasks.view(server.DB,job)['state'],'cancelled')
        with server.connect(audit=False) as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM sentence_search_dirty')],before)
            self.assertEqual(journal.workspace_revision(db),revision)


if __name__ == '__main__':
    unittest.main()
