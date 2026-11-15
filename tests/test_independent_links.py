import json
import unittest
from unittest.mock import patch

import dictionary_targets
import evidence_owners
import independent_links
import journal
import server
import test_server
import undo_codec


class IndependentLinkTests(unittest.TestCase):
    setUp = test_server.APITests.setUp
    tearDown = test_server.APITests.tearDown
    call = test_server.APITests.call

    def api(self, path, body=None):
        status, result = self.call('/api/' + path, body)
        self.assertEqual(status, 200, result)
        return result

    def entry(self, form, gloss):
        return self.api('lexeme-save', {'headword':form,'body':{'usages':[
            {'id':'usage','pos':'','senses':[{'id':'sense','short_gloss':gloss}]}
        ]}})

    def revision(self, rid):
        with server.connect(audit=False) as db:
            return db.execute('SELECT revision FROM dictionary_examples WHERE id=?', (rid,)).fetchone()[0]

    def undo(self, redo=False):
        self.api('redo' if redo else 'undo', {'generation':self.api('undo-state')['generation']})

    def test_link_editor_and_word_actions_never_decode_source(self):
        first, second = self.entry('home', 'house'), self.entry('other', 'dwelling')
        marker = 'association-test-source-only'
        example = self.api('example-save', {'body':{'translation':marker,'words':[{'form':'home','gloss':'house'}]}})
        rid = example['id']
        with server.connect(audit=False) as db:
            original = db.execute('SELECT body FROM dictionary_examples_documents WHERE id=?', (rid,)).fetchone()[0]
        decode = json.loads

        def guarded(value, *args, **kwargs):
            if isinstance(value, str) and value.lstrip().startswith('{'):
                self.assertNotIn(marker, value, 'Association action decoded the sentence source')
            return decode(value, *args, **kwargs)

        def word_link(entry, revision):
            return self.api('segmentation-link', {'kind':'independent','id':rid,'revision':revision,
                'word':0,'key':'@word','lexeme_id':entry['id'],'lexeme_revision':entry['revision'],
                'usage_id':'usage','sense_id':'sense'})

        with patch('json.loads', side_effect=guarded):
            word_link(first, example['revision'])
            word_link(second, self.revision(rid))
            selection = {'id':rid,'revision':self.revision(rid),'targets':[
                {'index':0,'lexeme_id':second['id'],'usage_id':'usage','sense_id':'sense'},
                {'lexeme_id':first['id']}
            ]}
            self.api('example-links-save', selection)
            self.assertEqual(self.call('/api/example-links-save', selection)[0], 400)
            with server.connect(audit=False) as db:
                self.assertEqual(evidence_owners.independent_ids(db, [first['id']]), {rid})
                self.assertEqual(dictionary_targets.references(db, second['id'])['independent'], 1)
                independent_links.validate(db)
            self.api('segmentation-link', {'kind':'independent','id':rid,'revision':self.revision(rid),'remove_target':0})
            self.undo()
            self.undo(redo=True)
            self.api('dictionary-examples-unlink', {'lexeme_id':first['id'],
                'items':[{'id':rid,'revision':self.revision(rid)}]})
            self.undo()
            with server.connect(audit=False) as db:
                self.assertEqual(db.execute('SELECT body FROM dictionary_examples_documents WHERE id=?', (rid,)).fetchone()[0], original)
                current = db.execute('SELECT changes FROM undo_steps WHERE applied=0 ORDER BY id DESC LIMIT 1').fetchone()[0]
                example_change = next(c for c in undo_codec.decode(current) if c['table']=='dictionary_examples')
                self.assertTrue(example_change['revision_only'])
                self.assertNotIn('body', example_change['before'])

        source = self.api('segmentation?kind=independent&id='+rid)['body']
        self.assertEqual(source['words'][0]['gloss'], 'dwelling')
        self.assertEqual([ref['lexeme_id'] for ref in source['targets']], [first['id']])

    def test_legacy_project_migration_and_existing_undo(self):
        from pathlib import Path
        import record_sources
        server.DB=Path(self.temp.name)/'old.sqlite3'
        server.init(source_mode='legacy')
        entry = self.entry('home', 'house')
        example = self.api('example-save', {'body':{'translation':'legacy', 'words':[{'form':'home','gloss':'house'}]}})
        rid = example['id']
        with server.connect(audit=False) as db:
            before = dict(db.execute('SELECT rowid,* FROM dictionary_examples WHERE id=?', (rid,)).fetchone())
            original = json.loads(before['body'])
            before['body'] = json.dumps({**original,'targets':[]})
            association = {'lexeme_id':entry['id'],'usage_id':'usage','sense_id':'sense','form_id':None,
                           'features':[],'notes':'legacy note','review_reason':'legacy review'}
            after = {**before,'body':json.dumps({**original,'targets':[association]}),'revision':before['revision']+1}
            independent_links.drop_triggers(db)
            for table in (*independent_links.TABLES,'independent_words','independent_dictionary_keys'):
                db.execute('DROP TABLE '+table)
            db.execute('UPDATE dictionary_examples SET body=?,revision=? WHERE id=?', (after['body'],after['revision'],rid))
            journal.record(db,{('dictionary_examples',before['rowid']):(before,after)},journal.LABELS['/api/segmentation-link'])

        server.init()
        with server.connect(audit=False) as db:
            self.assertIsNone(db.execute('PRAGMA foreign_key_check').fetchone())
            self.assertEqual(independent_links.targets(db,rid),[association])
            self.assertEqual(record_sources.read(db,'dictionary_examples',rid),original)
            step=undo_codec.decode(db.execute('SELECT changes FROM undo_steps ORDER BY id DESC LIMIT 1').fetchone()[0])
            self.assertTrue(step[0]['revision_only'])
            self.assertEqual(step[1]['table'],'independent_links')
        self.assertTrue(list((server.DB.parent/'backups').glob('before-lexicon-*.sqlite3')))
        self.undo()
        self.assertEqual(dictionary_targets_count(self, entry['id']), 0)
        self.undo(redo=True)
        self.assertEqual(self.api('dictionary-examples?id='+entry['id'])[0]['body']['targets'], [association])
        server.init()
        self.assertEqual(dictionary_targets_count(self, entry['id']), 1)


def dictionary_targets_count(test, xid):
    return test.api('dictionary-examples?paged=1&id='+xid)['total']
