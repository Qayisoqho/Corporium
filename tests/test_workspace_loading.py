import unittest
import test_server
import server


class WorkspaceLoadingTests(unittest.TestCase):
    setUp = test_server.APITests.setUp
    tearDown = test_server.APITests.tearDown
    call = test_server.APITests.call

    def api(self, path, body=None):
        code, result = self.call('/api/' + path, body)
        self.assertEqual(code, 200, result)
        return result

    def revision(self, language='ordos'):
        return self.api('undo-state?language=' + language)['workspace_revision']

    def test_readonly_check_does_not_modify_data_or_history(self):
        before = self.revision()
        with server.connect() as db:
            changes = db.total_changes
        for language in ['ordos', 'all']:
            self.assertEqual(self.revision(language), before)
        self.assertEqual(self.call('/api/undo-state?language=missing')[0], 400)
        with server.connect() as db:
            self.assertEqual(db.total_changes, changes)
        self.assertEqual(self.call('/workspace-loading.js')[0], 200)

    def test_other_language_edits_and_new_languages_invalidate_all_scope(self):
        before = self.revision('all')
        language = self.api('save-language', dict(name='Loading QA', metadata={}))['id']
        created = self.revision('all')
        self.assertNotEqual(before, created)
        x = self.api('lexeme-save', dict(headword='word', body={}, _language=language))
        edited = self.revision()
        self.assertNotEqual(created, edited)
        state = self.api('undo-state?language=' + language)
        self.api('undo', dict(generation=state['generation'], _language=language))
        undone = self.revision()
        self.assertNotEqual(edited, undone)
        state = self.api('undo-state?language=' + language)
        self.api('redo', dict(generation=state['generation'], _language=language))
        self.assertNotEqual(undone, self.revision())
        self.assertEqual(self.api('lexeme?id=' + x['id'])['headword'], 'word')

    def test_same_count_edit_and_history_trimming_still_change_revision(self):
        x = self.api('lexeme-save', dict(headword='a', body={}))
        before = self.revision()
        self.api('lexeme-save', {**x, 'headword': 'b'})
        self.assertNotEqual(before, self.revision())
        for i in range(12):
            self.api('lexeme-save', dict(headword='item' + str(i), body={}))
        state = self.api('undo-state')
        before = self.revision()
        self.api('undo-limit', dict(generation=state['generation'], limit=10))
        self.assertNotEqual(before, self.revision())
        self.assertEqual(len(self.api('undo-state')['steps']), 10)


if __name__ == '__main__':
    unittest.main()
