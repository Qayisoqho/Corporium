"""Scoped text saves must retain graph, revision and transaction guarantees."""
import source_fixtures
import copy
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import journal
import lexicon
import save_validation
import sentence_search_index
import server
import test_inline_slots
import test_lexicon


class SaveValidationTests(unittest.TestCase):
    setUp = test_lexicon.LexiconTests.setUp
    tearDown = test_lexicon.LexiconTests.tearDown
    call = test_lexicon.LexiconTests.call
    seed = test_lexicon.LexiconTests.seed
    entries = test_lexicon.LexiconTests.entries
    word = test_lexicon.LexiconTests.word
    link = test_lexicon.LexiconTests.link
    undo = test_lexicon.LexiconTests.undo
    draft = test_inline_slots.SlotTests.draft

    def ok(self,path,body=None):
        code,result = self.call('/api/' + path,body)
        self.assertEqual(code,200,result)
        return result

    def note(self,word,value='changed'):
        draft = self.ok('lexeme?id=' + word['id'])
        draft['body']['notes'] = value
        return self.ok('lexeme-save',draft)

    def prime(self,word):
        result = self.note(word,'prime')
        with server.connect(audit=False) as db:
            self.assertIsNotNone(save_validation.snapshot(db))
        return result

    def test_untrusted_first_save_checks_full_graph_then_notes_are_scoped(self):
        word = self.word()
        with patch.object(lexicon,'validate_links',wraps=lexicon.validate_links) as full:
            self.prime(word)
            self.assertEqual(full.call_count,1)
            self.assertEqual(len(full.call_args.args),1)
        with patch.object(lexicon,'validate_links',side_effect=AssertionError('unneeded global scan')):
            saved = self.note(word,'only notes')
        self.assertEqual(saved['body']['notes'],'only notes')

    def test_corpus_and_independent_translations_use_real_slot_save(self):
        corpus = self.seed()
        independent = self.ok('example-save',dict(body=dict(ipa='ipa',translation='old',words=[dict(form='form',gloss='G')],targets=[])))
        # The first inline edit also fills missing persisted analysis defaults;
        # that mixed update deliberately retains the original full checks.
        self.ok('inline-save',self.draft('independent',independent))
        self.prime(self.word())
        for kind,record in [('corpus',corpus),('independent',independent)]:
            with self.subTest(kind=kind):
                draft = self.draft(kind,record)
                identities = copy.deepcopy(draft['slot_ids'])
                draft['body']['translation'] = 'new translation'
                draft['body']['notes'] = 'new note'
                with patch.object(lexicon,'validate_links',side_effect=AssertionError('unneeded global scan')):
                    self.ok('inline-save',draft)
                fresh = self.draft(kind,record)
                self.assertEqual(fresh['slot_ids'],identities)
                self.assertEqual(fresh['body']['translation'],'new translation')
                self.assertEqual(self.call('/api/inline-save',draft)[0],400)
                self.assertEqual(self.undo()[0],200)
                self.assertEqual(self.draft(kind,record)['body']['translation'],'old' if kind == 'independent' else 'translation')
                self.assertEqual(self.undo('redo')[0],200)
                self.assertEqual(self.draft(kind,record)['slot_ids'],identities)

    def test_existing_sense_text_and_new_sense_both_validate_locally(self):
        word=self.prime(self.word())
        word['body']['usages'][0]['senses'][0]['short_gloss']='new meaning'
        with patch.object(lexicon,'validate_links',wraps=lexicon.validate_links) as full:
            self.ok('lexeme-save',word)
            self.assertEqual(full.call_count,0)
            word=self.ok('lexeme?id='+word['id'])
            word['body']['usages'][0]['senses'].append({'short_gloss':'another'})
            saved=self.ok('lexeme-save',word)
            self.assertEqual(len(saved['body']['usages'][0]['senses']),2)
            self.assertEqual(full.call_count,0)

    def test_scoped_dictionary_edits_keep_incoming_selections_and_both_graphs_valid(self):
        word=self.word()
        usage=word['body']['usages'][0]
        other=self.ok('lexeme-save',dict(headword='composite',body={
            'relation':dict(base_id=word['id'],type='derivation'),
            'word_structure':dict(analyses=[dict(components=[dict(form='home',lexeme_id=word['id'],
                usage_id=usage['id'],sense_id=usage['senses'][0]['id'])])]),
        }))
        word=self.prime(word)
        with patch.object(lexicon,'validate_links',side_effect=AssertionError('Unneeded dictionary scan')):
            for fields in (
                dict(relation=dict(base_id=other['id'],type='derivation')),
                dict(word_structure=dict(analyses=[dict(components=[dict(form='composite',lexeme_id=other['id'])])])),
                dict(usages=[]),
                dict(orthographies=[dict(text='written',type_id='missing')]),
            ):
                with self.subTest(fields=fields):
                    self.assertEqual(self.call('/api/lexeme-save',{**word,'body':{**word['body'],**fields}})[0],400)
                    self.assertEqual(self.ok('lexeme?id='+word['id']),word)

    def test_saved_evidence_reads_only_requested_links_at_the_committed_revision(self):
        corpus=self.seed()
        word=self.word()
        self.link(corpus['words'][0]['unit_id'],word)
        independent=self.ok('example-save',dict(body=dict(translation='keep',words=[dict(form='home',gloss='G')],
            targets=[dict(lexeme_id=word['id'])])))
        word=self.prime(word)
        corpus_id=self.ok('lexeme-examples?id='+word['id'])['items'][0]['id']
        word['body']['usages'][0]['senses'][0]['short_gloss']='changed'
        word['_view_revision']=self.ok('undo-state')['workspace_revision']
        receipt=self.ok('lexeme-save',word)['_view_update']
        self.assertTrue(receipt['evidence_rows'])
        query=urlencode(dict(id=word['id'],view_revision=receipt['current'],language='ordos',
                             corpus=json.dumps([corpus_id]),independent=json.dumps([independent['id']])))
        route='lexeme-evidence-rows?'+query
        rows=self.ok(route)
        self.assertEqual(rows['history'],self.ok('undo-state'))
        self.assertEqual(rows['corpus'],self.ok('lexeme-examples?id='+word['id'])['items'])
        self.assertEqual(rows['independent'],self.ok('dictionary-examples?paged=1&id='+word['id'])['items'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.ok(route),{'stale':True})

    def test_existing_word_slots_validate_locally_with_references_and_history(self):
        corpus=self.seed()
        word=self.word()
        self.link(corpus['words'][0]['unit_id'],word)
        independent=self.ok('example-save',dict(body=dict(translation='keep',words=[dict(form='home',gloss='G')],
            targets=[dict(lexeme_id=word['id'])])))
        self.prime(word)
        for kind,record in (('corpus',corpus),('independent',independent)):
            with self.subTest(kind=kind),patch.object(lexicon,'validate_links',side_effect=AssertionError('Unneeded dictionary scan')):
                draft=self.draft(kind,record)
                old=draft['body']['words'][0]['form']
                draft['body']['words'][0]['form']='house-n' if kind=='corpus' else 'house'
                draft['_view_revision']=self.ok('undo-state')['workspace_revision']
                saved=self.ok('inline-save',draft)['_view_update']
                fresh=self.draft(kind,record)
                self.assertEqual(fresh['slot_ids'],draft['slot_ids'])
                self.assertEqual(fresh['body']['words'][0]['form'],draft['body']['words'][0]['form'])
                self.assertEqual((saved['before_revision'],saved['revision']),(draft['revision'],fresh['revision']))
                self.assertEqual(saved['current'],self.ok('undo-state')['workspace_revision'])
                if kind=='corpus':
                    current=next(e for e in self.entries() if e['id']==record['id'])
                else:
                    current=next(e['body'] for e in self.ok('example-groups-library')['items'] if e['id']==record['id'])
                self.assertEqual(saved['record'],current)
                self.assertEqual(self.undo()[0],200)
                self.assertEqual(self.draft(kind,record)['body']['words'][0]['form'],old)
                self.assertEqual(self.undo('redo')[0],200)
                self.assertEqual(self.draft(kind,record)['slot_ids'],draft['slot_ids'])

    def test_existing_spelling_and_registry_reassignment_validate_locally(self):
        shared=self.ok('morpheme-save',dict(form='ma',body={}))
        other=self.ok('morpheme-save',dict(form='na',body={}))
        word=self.ok('lexeme-save',dict(headword='mapa',body=dict(variants=[dict(form='map')],
            word_structure=dict(analyses=[dict(id='main',components=[dict(id='part',form='ma')])]))))
        self.ok('morpheme-assign',dict(lexeme_id=word['id'],lexeme_revision=word['revision'],
            morpheme_id=shared['id'],morpheme_revision=shared['revision'],components=[dict(analysis_id='main',component_id='part')]))
        word=self.prime(word)
        with patch.object(lexicon,'validate_links',side_effect=AssertionError('Unneeded dictionary scan')):
            word['headword']='newword';word['body']['variants'][0]['form']='newvariant'
            word['_view_revision']=self.ok('undo-state')['workspace_revision']
            word=self.ok('lexeme-save',word)
            self.assertEqual(word['headword'],'newword')
            self.assertEqual(word['body']['variants'][0]['form'],'newvariant')
            self.assertEqual(word['_view_update']['structure'],dict(heading=True,morphology=False,variants=True,registry=False,evidence=[]))
            assignments=[dict(analysis_id='main',component_id='part',morpheme_id=other['id'],form_id=None)]
            word['body']['word_structure']['analyses'][0]['components'][0]['form']='na'
            plan=self.ok('morpheme-save-preview',dict(id=word['id'],body=word['body'],assignments=assignments))
            saved=self.ok('lexeme-save',dict(word,morpheme_confirmation=plan['token'],morpheme_assignments=assignments,
                _view_revision=self.ok('undo-state')['workspace_revision']))
            update=saved['_view_update']
            self.assertEqual(update['structure'],dict(heading=False,morphology=True,variants=False,registry=True,evidence=[]))
            self.assertEqual(update['components'][0]['link']['morpheme_id'],other['id'])
            read=lambda:self.ok('morpheme-components?id='+word['id'])['items'][0]['link']['morpheme_id']
            self.assertEqual(read(),other['id'])
            self.assertEqual(self.undo()[0],200)

            self.assertEqual(read(),shared['id'])
            self.assertEqual(self.undo('redo')[0],200)
            self.assertEqual(read(),other['id'])
            info=self.ok('morpheme-components?id='+word['id'])
            item=info['items'][0]
            prior=self.ok('morpheme?id='+shared['id'])
            saved=self.ok('morpheme-assign',dict(lexeme_id=word['id'],lexeme_revision=info['lexeme']['revision'],
                morpheme_id=prior['id'],morpheme_revision=prior['revision'],form_id=None,
                components=[dict(analysis_id='main',component_id='part',revision=item['link']['revision'])],
                _view_revision=self.ok('undo-state')['workspace_revision']))
            update=saved['_view_update']
            self.assertTrue(update['structure']['morphology'])
            self.assertEqual(update['record'],self.ok('lexeme?id='+word['id']))
            self.assertEqual(update['components'][0]['link']['morpheme_id'],prior['id'])

    def test_previously_assigned_components_still_require_a_review_if_new_items_appear(self):
        shared=self.ok('morpheme-save',dict(form='ma',body={}))
        word=self.ok('lexeme-save',dict(headword='mapa',body=dict(word_structure=dict(
            analyses=[dict(id='main',components=[dict(id='part',form='ma')])]))))
        self.ok('morpheme-assign',dict(lexeme_id=word['id'],lexeme_revision=word['revision'],
            morpheme_id=shared['id'],morpheme_revision=shared['revision'],components=[dict(analysis_id='main',component_id='part')]))
        word=self.prime(word)
        word['body']['notes']='assigned'
        saved=self.ok('lexeme-save',dict(word,morpheme_confirmation='@assigned'))
        draft=copy.deepcopy(saved)
        draft['body']['word_structure']['analyses'][0]['components'].append(dict(id='new-part',form='ma'))
        self.assertEqual(self.call('/api/lexeme-save',dict(draft,morpheme_confirmation='@assigned'))[0],400)
        self.assertEqual(self.ok('lexeme?id='+word['id']),saved)

    def test_note_decode_count_does_not_grow_with_dictionary_size(self):
        word = self.prime(self.word())
        with patch.object(json,'loads',wraps=json.loads) as loads:
            self.note(word,'small dictionary')
            small = loads.call_count
        with server.connect(audit=False) as db:
            for index in range(123):
                body = lexicon.normalize({'usages':[{'pos':'N','senses':[{'short_gloss':'sense'}]}]})
                source_fixtures.seed(db,'lexemes',('id', 'language_id', 'headword', 'body', 'revision'),('bounded-'+str(index), 'ordos', 'form-'+str(index), json.dumps(body), 1))
        self.prime(word)
        with patch.object(json,'loads',wraps=json.loads) as loads,patch.object(lexicon,'validate_links',side_effect=AssertionError('unneeded global scan')):
            self.note(word,'larger dictionary')
            large = loads.call_count
        self.assertLessEqual(large,small+5,(small,large))

    def test_external_write_without_revision_invalidates_and_rejects_dangling_sense(self):
        entry = self.seed();word = self.word()
        self.link(entry['words'][0]['unit_id'],word)
        other = self.ok('lexeme-save',dict(headword='unrelated',body={}))
        self.prime(word)
        # Simulate an external SQLite client that does not participate in revisions.
        sense=word['body']['usages'][0]['senses'][0]['id']
        with closing(sqlite3.connect(server.DB)) as external, external:
            external.execute("UPDATE dictionary_value_rows SET value='external-new-sense' WHERE target_kind='lexeme' AND target_id=? AND slot='id' AND value=?",(word['id'],sense))
        with server.connect(audit=False) as db:
            self.assertIsNone(save_validation.snapshot(db))
        draft = self.ok('lexeme?id=' + other['id']);old = draft['body']['notes']
        draft['body']['notes'] = 'must roll back'
        with patch.object(lexicon,'validate_links',wraps=lexicon.validate_links) as full:
            self.assertEqual(self.call('/api/lexeme-save',draft)[0],400)
            self.assertTrue(full.called)
        self.assertEqual(self.ok('lexeme?id=' + other['id'])['body']['notes'],old)
        draft=self.ok('lexeme?id='+other['id'])
        with patch.object(lexicon,'validate_links',wraps=lexicon.validate_links) as full:
            self.assertEqual(self.call('/api/lexeme-save',dict(draft,headword='must also roll back'))[0],400)
            self.assertEqual(len(full.call_args.args),1)
        self.assertEqual(self.ok('lexeme?id='+other['id'])['headword'],draft['headword'])

    def test_untrusted_corpus_translation_keeps_original_limited_checks(self):
        entry = self.seed();draft = self.draft('corpus',entry)
        draft['body']['translation'] = 'new translation'
        with patch.object(lexicon,'validate_links',side_effect=AssertionError('corpus save need not establish dictionary baseline')):
            self.ok('inline-save',draft)
        with server.connect(audit=False) as db:
            self.assertIsNone(save_validation.snapshot(db))

    def test_external_schema_change_repairs_guards_and_requires_full_check(self):
        word = self.prime(self.word())
        with closing(sqlite3.connect(server.DB)) as external, external:
            external.execute('DROP TRIGGER ' + save_validation.PREFIX + 'lexemes_update')
        with patch.object(lexicon,'validate_links',wraps=lexicon.validate_links) as full:
            self.note(word,'after repair')
            self.assertEqual(full.call_count,1)
        with closing(sqlite3.connect(server.DB)) as external, external:
            external.execute('UPDATE lexemes SET revision=revision+1 WHERE id=?',(word['id'],))
        with server.connect(audit=False) as db:
            self.assertIsNone(save_validation.snapshot(db))

    def test_derived_writes_preserve_baseline_but_source_writes_invalidate(self):
        word = self.prime(self.word())
        with server.connect(audit=False) as db:
            db.execute('DELETE FROM dictionary_form_dirty')
            self.assertIsNotNone(save_validation.snapshot(db))
            db.execute("UPDATE lexemes SET revision=revision WHERE id=?",(word['id'],))
            self.assertIsNotNone(save_validation.snapshot(db))
            db.execute('UPDATE lexemes SET revision=revision+1 WHERE id=?',(word['id'],))
            self.assertIsNone(save_validation.snapshot(db))

    def test_failed_save_rolls_back_guard_content_and_history(self):
        word = self.prime(self.word())
        with server.connect(audit=False) as db:
            before = save_validation.snapshot(db)
        with patch('collaborators.validate_changes',side_effect=ValueError('forced final failure')):
            draft = self.ok('lexeme?id=' + word['id']);draft['body']['notes'] = 'must roll back'
            self.assertEqual(self.call('/api/lexeme-save',draft)[0],400)
        with server.connect(audit=False) as db:
            self.assertEqual(save_validation.snapshot(db),before)
        self.assertEqual(self.ok('lexeme?id=' + word['id'])['body']['notes'],'prime')

    def test_benign_reinitialization_preserves_baseline_and_missing_cache_rebuilds(self):
        word = self.prime(self.word())
        server.init()
        with patch.object(lexicon,'validate_links',side_effect=AssertionError('startup lost trusted proof')):
            self.note(word,'after startup')
        with server.connect(audit=False) as db:
            save_validation.drop(db)
        with patch.object(lexicon,'validate_links',wraps=lexicon.validate_links) as full:
            self.note(word,'after missing cache')
            self.assertEqual(full.call_count,1)

    def test_preview_full_check_cannot_certify_later_unvalidated_changes(self):
        word = self.word()
        token = journal.action.set('test preview')
        try:
            with server.connect() as db:
                db.execute('SAVEPOINT preview')
                lexicon.validate_links(db)
                db.execute('ROLLBACK TO preview');db.execute('RELEASE preview')
                # A normal limited validation does not establish a full baseline.
                db.execute("UPDATE languages SET revision=revision+1 WHERE id='ordos'")
            with server.connect(audit=False) as db:
                self.assertIsNone(save_validation.snapshot(db))
        finally:
            journal.action.reset(token)

    def test_portable_snapshot_drop_removes_validation_cache_and_guards(self):
        self.prime(self.word())
        with server.connect(audit=False) as db:
            sentence_search_index.drop(db)
            self.assertIsNone(save_validation.state(db))
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name LIKE 'save_validation_watch_%'").fetchone())

    def test_rule_change_invalidates_prior_validation(self):
        word = self.prime(self.word())
        with patch.object(save_validation,'RULES_VERSION',save_validation.RULES_VERSION+1),patch.object(lexicon,'validate_links',wraps=lexicon.validate_links) as full:
            self.note(word,'after rule change')
            self.assertEqual(full.call_count,1)

    def test_refresh_receipt_identifies_one_committed_edit_and_history_transition(self):
        word = self.prime(self.word())
        base = self.ok('undo-state')['workspace_revision']
        word['_view_revision'] = base
        word['body']['notes'] = 'new note'
        saved = self.ok('lexeme-save',word)
        self.assertEqual(saved['_view_update'],dict(kind='lexeme',id=word['id'],before_revision=word['revision'],
            revision=saved['revision'],base=base,current=self.ok('undo-state')['workspace_revision'],values={'notes':'new note'}))
        self.assertNotIn('_view_update',self.ok('lexeme?id='+word['id']))
        # The same window token no longer describes the current project.
        saved['_view_revision'] = base
        saved['body']['notes'] = 'valid save from an older view'
        self.assertNotIn('_view_update',self.ok('lexeme-save',saved))

    def test_refresh_receipt_rejects_structure_side_effects_and_external_writes(self):
        other = self.ok('lexeme-save',dict(headword='another',body={}))
        word = self.prime(self.word())
        def save(body,*,sense_text=False):
            body['_view_revision'] = self.ok('undo-state')['workspace_revision']
            result = self.ok('lexeme-save',body)
            if sense_text:self.assertTrue(result['_view_update']['sense_text'])
            else:self.assertNotIn('_view_update',result)
            return result
        word['body']['usages'][0]['senses'][0]['short_gloss'] = 'changed meaning'
        word = save(word,sense_text=True)
        word['body']['notes'] = 'changed with another row'
        with patch('collaborators.cleanup',side_effect=lambda db,changes:db.execute('UPDATE lexemes SET revision=revision+1 WHERE id=?',(other['id'],))):
            word = save(word)
        with server.connect(audit=False) as db:
            db.execute('UPDATE lexemes SET revision=revision+1 WHERE id=?',(other['id'],))
        word['body']['notes'] = 'after external change'
        save(word)

    def test_inline_receipt_uses_persisted_values_and_normal_slot_checks(self):
        record = self.ok('example-save',dict(body=dict(ipa='ipa',translation='old',words=[dict(form='w',gloss='G')],targets=[])))
        self.ok('inline-save',self.draft('independent',record))
        self.prime(self.word())
        draft = self.draft('independent',record)
        draft['_view_revision'] = self.ok('undo-state')['workspace_revision']
        draft['body'].update(translation='new',notes='note')
        saved = self.ok('inline-save',draft)['_view_update']
        self.assertEqual(saved['values'],{'translation':'new','notes':'note'})
        self.assertEqual((saved['id'],saved['revision']),(record['id'],self.draft('independent',record)['revision']))
        self.assertEqual(self.call('/api/inline-save',draft)[0],400)

    def test_canonical_defaults_allow_notes_but_keep_unknown_fields(self):
        body = lexicon.normalize({'usages':[{'pos':'N','senses':[{'short_gloss':'sense'}]}]})
        old = copy.deepcopy(body)
        for usage in old['usages']:
            for sense in usage['senses']:
                sense.pop('gloss_addition',None);sense.pop('show_gloss_addition',None)
        body['notes'] = 'changed'
        body['form_parts'] = []
        for usage in body['usages']:
            for sense in usage['senses']:
                sense['gloss_addition'] = '';sense['show_gloss_addition'] = True
        before = dict(id='word',language_id='ordos',headword='form',body=json.dumps(old),revision=1)
        after = {**before,'body':json.dumps(body),'revision':2}
        self.assertTrue(save_validation.text_only([('lexemes',before,after)]))
        old['usages'][0]['opaque'] = {'keep':True}
        before['body'] = json.dumps(old)
        self.assertFalse(save_validation.text_only([('lexemes',before,after)]))
        old.pop('usages')
        old['entry_type'] = 'circumfix'
        body = copy.deepcopy(old);body['form_parts'] = []
        before['body'] = json.dumps(old);after['body'] = json.dumps(body)
        self.assertFalse(save_validation.text_only([('lexemes',before,after)]))

    def test_classifier_keeps_definitions_slots_and_unknown_nested_fields(self):
        word = self.word()
        before = dict(id=word['id'],language_id='ordos',headword='home',body=json.dumps(word['body']),revision=1,rowid=1)
        def accepted(body=None,table='lexemes',**columns):
            after = {**before,'revision':2,'body':json.dumps(body if body is not None else word['body']),**columns}
            return save_validation.text_only([(table,before,after)])
        body = copy.deepcopy(word['body']);body['notes'] = 'new'
        self.assertTrue(accepted(body))
        for change in [lambda b:b['usages'][0]['senses'][0].update(definition='changed'),lambda b:b['usages'][0]['senses'].pop(),lambda b:b['usages'][0].update(features=['missing']),lambda b:b['usages'][0]['senses'][0].update(unknown={'opaque':True}),lambda b:b.update(word_structure={'analyses':[],'unknown':'changed'})]:
            body = copy.deepcopy(word['body']);change(body)
            self.assertFalse(accepted(body))
        self.assertFalse(accepted(language_id='other'))
        self.assertFalse(accepted(headword='other'))
        self.assertFalse(accepted(rowid=2))
        self.assertFalse(save_validation.text_only([('lexemes',None,before)]))
        self.assertFalse(save_validation.text_only([('lexemes',before,None)]))
        self.assertFalse(save_validation.text_only([('lexemes',before,before),('grammar_tags',before,before)]))
        example = dict(id='example',language_id='ordos',body=json.dumps(dict(words=[dict(form='w',annotation_id='w0')],targets=[dict(lexeme_id=word['id'])])),revision=1)
        for key,value in [('targets',[]),('words',[]),('layer_snapshot',{'changed':True}),('grammaticality','unknown')]:
            after = copy.deepcopy(example);b = json.loads(after['body']);b[key] = value;after['body'] = json.dumps(b)
            self.assertFalse(save_validation.text_only([('dictionary_examples',example,after)]))


if __name__ == '__main__':
    unittest.main()
