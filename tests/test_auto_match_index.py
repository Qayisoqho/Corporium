"""Compare the indexed and direct matchers across source and dictionary edits."""
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import auto_match_index
import independent_annotations
import lexicon
import project_backup
import language_exchange
import server
import test_sentence_dictionary as sd


class AutoMatchIndexTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','entry','undo'):
        locals()[name]=getattr(sd.SentenceDictionaryTests,name)

    def equal_plans(self,**options):
        plan=self.api('lexeme-auto-preview?'+urlencode(dict(language='ordos',**options)))
        with server.connect(audit=False) as db:
            self.assertEqual(plan,lexicon.auto_link_plan(db,'ordos',**options))
            self.assertTrue(auto_match_index.exists(db))
            self.assertEqual(db.execute('SELECT count(*) FROM auto_match_dirty').fetchone()[0],0)
        return plan

    def test_incremental_sources_dictionary_and_tag_alias(self):
        tag=self.api('grammar-save',dict(symbol='PL',aliases=['plural']))['id']
        word=self.entry('ǰad','家',features=[tag])
        self.entry('ǰad-','家',features=[tag])
        corpus=self.source('corpus',[('ǰad','家.plural'),('bad','別')])
        independent=self.source('independent',[('ǰad','家.plural'),('bad','別')])
        with server.connect(audit=False) as db:
            text_id=db.execute('SELECT text_id FROM entries WHERE id=?',(corpus['id'],)).fetchone()[0]
        first_scope=self.api('lexeme-auto-preview?language=ordos&text_id='+text_id)
        with server.connect(audit=False) as db:
            self.assertFalse(auto_match_index.exists(db))
        plan=self.equal_plans()
        self.assertEqual(len(plan['suggestions']),4)
        self.assertEqual(self.equal_plans(text_id=text_id),first_scope)
        self.assertEqual(len(self.equal_plans(text_id='@independent')['suggestions']),2)
        self.assertEqual(len(self.equal_plans(ignore_symbols='',ignore_position='edges')['matches']),2)
        self.equal_plans(ignore_symbols='-',ignore_position='all')

        raw=self.detail(independent)
        self.api('example-save',dict(id=independent['id'],revision=raw['revision'],body={
            **raw['body'],'words':[dict(form='ǰad',gloss='家.plural'),dict(form='ǰad',gloss='家.plural')]}))
        self.assertEqual(len(self.equal_plans()['suggestions']),6)
        self.undo()
        self.assertEqual(len(self.equal_plans()['suggestions']),4)

        saved=self.api('lexeme?id='+word['id'])
        saved['body']['usages'][0]['senses'][0]['short_gloss']='別'
        self.api('lexeme-save',saved)
        self.assertEqual(len(self.equal_plans()['suggestions']),2)
        self.undo()
        self.assertEqual(len(self.equal_plans()['suggestions']),4)

        grammar_tag=next(t for t in self.api('grammar-tags') if t['id']==tag)
        self.api('grammar-save',{**grammar_tag,'aliases':[]})
        self.assertEqual(self.equal_plans()['suggestions'],[])
        self.undo()
        self.assertEqual({r['entry_id'] for r in self.equal_plans()['suggestions']},{corpus['id'],independent['id']})

    def test_fast_undo_with_existing_inherited_word(self):
        self.entry('ger','家')
        whole=self.entry('ger-n','家-GEN')
        src=self.source('independent',[('ger-n','家-GEN')])
        state=self.detail(src)
        use=whole['body']['usages'][0]
        self.api('segmentation-link',dict(**src,revision=state['revision'],word=0,key='@word',lexeme_id=whole['id'],
            lexeme_revision=whole['revision'],usage_id=use['id'],sense_id=use['senses'][0]['id']))
        with server.connect(audit=False) as db:
            lexicon.validate_links(db)
            db.execute('UPDATE save_validation_state SET checked_epoch=epoch')
        before=self.detail(src)
        plan=self.api('lexeme-auto-preview?language=ordos&reuse_preview=1')
        self.assertEqual([r['segmentation_ref']['key'] for r in plan['matches']],['0:host'])
        with patch('independent_links.replace',side_effect=AssertionError('reconciled the word individually')):
            self.assertEqual(self.api('lexeme-auto-link',dict(token=plan['token'],reuse_preview=True))['count'],1)
        self.assertEqual(len(self.detail(src)['body']['targets']),2)
        with patch('journal.undo_appended_links',wraps=server.journal.undo_appended_links) as fast:
            self.undo()
            fast.assert_called_once()
        self.assertEqual(self.detail(src)['body'],before['body'])
        self.undo(True)
        self.assertEqual(len(self.detail(src)['body']['targets']),2)

    def test_batch_fragment_cleanup_and_revision_capture_are_atomic(self):
        import journal
        import read_views
        import save_validation
        self.entry('ger','家')
        src=self.source('independent',[('ger-n','家-GEN'),('ger-n','家-GEN')])
        with server.connect(audit=False) as db:
            lexicon.validate_links(db)
            db.execute('UPDATE save_validation_state SET checked_epoch=epoch')
            db.execute('DELETE FROM word_analysis_dirty WHERE owner_id=?',(src['id'],))
            before_token=read_views.token(db,'dictionary')
        before=self.detail(src)
        plan=self.api('lexeme-auto-preview?language=ordos&reuse_preview=1')
        self.assertEqual(len(plan['matches']),2)
        self.api('lexeme-auto-link',dict(token=plan['token'],reuse_preview=True))
        after=self.detail(src)
        self.assertEqual(after['revision'],before['revision']+2)
        with server.connect(audit=False) as db:
            step=journal.decode_changes(db.execute('SELECT changes FROM undo_steps ORDER BY id DESC LIMIT 1').fetchone()[0])
            revisions=[c for c in step if c['table']=='dictionary_examples']
            self.assertEqual(len(revisions),1)
            self.assertTrue(revisions[0]['revision_only'])
            self.assertEqual(revisions[0]['before']['revision'],before['revision'])
            self.assertEqual(revisions[0]['after']['revision'],after['revision'])
            self.assertEqual(db.execute('SELECT count(*) FROM independent_link_fragments').fetchone()[0],2)
            self.assertFalse(db.execute('SELECT 1 FROM word_analysis_dirty WHERE owner_id=?',(src['id'],)).fetchone())
            self.assertIsNotNone(save_validation.snapshot(db))
            after_token=read_views.token(db,'dictionary')
            self.assertNotEqual(before_token,after_token)
        delete=independent_annotations.delete_references
        def rollback(db,rows):
            delete(db,rows)
            self.assertFalse(db.execute('SELECT 1 FROM independent_link_fragments').fetchone())
            raise ValueError('test rollback after batch fragment removal')
        with patch.object(independent_annotations,'delete_references',side_effect=rollback) as cleanup:
            state=self.api('undo-state')
            code,_=self.call('/api/undo',{'generation':state['generation']})
            self.assertEqual(code,400)
            cleanup.assert_called_once()
        self.assertEqual(self.detail(src),after)
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM independent_link_fragments').fetchone()[0],2)
            self.assertFalse(db.execute('SELECT 1 FROM read_view_association_batch').fetchone())
            self.assertEqual(read_views.token(db,'dictionary'),after_token)
            self.assertIsNotNone(save_validation.snapshot(db))
        # A live fragment can differ even though the parent's stored stamp
        # still matches. The checked batch must leave those newer rows alone.
        with server.connect(audit=False) as db:
            key,stamp,ordinal,value=db.execute('SELECT parent_id,snapshot,ordinal,text FROM independent_link_fragments LIMIT 1').fetchone()
            db.execute('UPDATE independent_link_fragments SET text=? WHERE (parent_id,snapshot,ordinal)=(?,?,?)',
                       ('changed',key,stamp,ordinal))
            self.assertIsNone(save_validation.snapshot(db))
            db.execute('UPDATE save_validation_state SET checked_epoch=epoch')
        state=self.api('undo-state')
        self.assertEqual(self.call('/api/undo',{'generation':state['generation']})[0],400)
        with server.connect(audit=False) as db:
            db.execute('UPDATE independent_link_fragments SET text=? WHERE (parent_id,snapshot,ordinal)=(?,?,?)',
                       (value,key,stamp,ordinal))
            db.execute('UPDATE save_validation_state SET checked_epoch=epoch')
        self.undo()
        self.assertEqual(self.detail(src)['body'],before['body'])
        with server.connect(audit=False) as db:
            self.assertFalse(db.execute('SELECT 1 FROM independent_link_fragments').fetchone())
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchone())
        self.undo(True)
        self.assertEqual([link['segmentation_ref'] for link in self.detail(src)['body']['targets']],
                         [link['segmentation_ref'] for link in after['body']['targets']])

    def test_revision_batch_keeps_an_earlier_source_edit_in_the_same_transaction(self):
        import journal
        import record_sources
        import sentence_rows

        src=self.source('independent',[('ger-n','家-GEN')])
        rid=src['id']
        with server.connect(audit=False) as db:
            changes=journal.watch(db,tables=('dictionary_examples',))
            body=sentence_rows.one(db,'independent',rid)
            sentence_rows.write(db,'independent',rid,{**body,'translation':'家'})
            record_sources.bump_example_revisions(db,{rid:2})
            (before,after),=changes.values()
            self.assertEqual(before['body'],body)
            self.assertEqual(after['body']['translation'],'家')
            self.assertEqual(after['revision'],before['revision']+3)

    def test_project_backup_rebuilds_match_keys_and_preserves_links(self):
        self.entry('source','家')
        src=self.source('independent',[('source','家')])
        first=self.equal_plans()
        self.api('lexeme-auto-link',dict(token=first['token']))
        before=self.detail(src)['body']
        with server.connect(audit=False) as db:
            package=project_backup.prepare(db,server.DB)
        target=Path(self.temp.name)/'restored.sqlite3'
        project_backup.restore(language_exchange.staged(server.DB,package['token'],'project-backup'),target)
        server.DB=target
        server.init()
        with server.connect(audit=False) as db:
            self.assertFalse(auto_match_index.exists(db))
        self.assertEqual(self.detail(src)['body'],before)
        self.assertEqual(self.equal_plans()['already_linked'],1)
        self.undo()
        self.assertEqual(self.detail(src)['body']['targets'],[])
        self.assertEqual(len(self.equal_plans()['matches']),1)
