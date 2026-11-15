"""Chinese derived headwords keep replacement, indexes and references coherent."""
import json
import unittest
from collections import Counter
from urllib.parse import urlencode

import dictionary_search
import server
import test_lexicon


class ChineseModeIntegrationTests(unittest.TestCase):
    for helper in ('setUp', 'tearDown', 'call', 'seed', 'entries', 'link', 'undo'):
        locals()[helper] = getattr(test_lexicon.LexiconTests, helper)

    def api(self, path, body=None):
        code, result = self.call('/api/' + path, body)
        self.assertEqual(code, 200, result)
        return result

    def enable(self):
        language = next(row for row in self.api('languages') if row['id'] == 'ordos')
        metadata = language['metadata']
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        self.api('save-language', dict(id='ordos', name=language['name'],
                                     revision=language['revision'],
                                     metadata={**metadata, 'chinese_mode': True}))

    def fixture(self):
        self.enable()
        first = self.api('morpheme-save', dict(form='ma', body=dict(gloss='M', readings=['ma55'])))
        second = self.api('morpheme-save', dict(form='pa', body=dict(gloss='P', readings=['pa21'])))
        source = 'private-source-analysis-87'
        body = dict(notes='old note', headword_source=dict(analysis_id=source, joiner=''),
                    usages=[dict(pos='名词', senses=[dict(short_gloss='WORD')])],
                    word_structure=dict(analyses=[dict(id=source, components=[
                        dict(id='first', form='ma', gloss='M', readings=['ma55']),
                        dict(id='second', form='pa', gloss='P', readings=['pa21'])])]))
        assignments = [dict(analysis_id=source, component_id=key, morpheme_id=m['id'], form_id=None)
                       for key, m in [('first', first), ('second', second)]]
        plan = self.api('morpheme-save-preview', dict(body=body, assignments=assignments))
        word = self.api('lexeme-save', dict(headword='mapa', body=body,
                        morpheme_assignments=assignments, morpheme_confirmation=plan['token']))
        return first, second, word

    def preview(self, **extra):
        args = {**dict(kind='lexeme', field='headword', find='ma', replacement='na',
                       scope='language'), **extra}
        return args, self.api('dictionary-replace-preview', args)

    def test_shared_rename_coalesces_whole_and_component_evidence_with_undo(self):
        first,_,word=self.fixture()
        word['body']['headword_source']['joiner']='-'
        word=self.api('lexeme-save',word)
        corpus=self.seed('#pass([keep], (([ma-pa],[M-P]),([«#sub[ma]-pa»],[M-P])), [keep])')
        independent=self.api('example-save',dict(body=dict(translation='keep',words=[
            dict(form='ma-pa',gloss='M-P'),dict(form='«#sub[ma]-pa»',gloss='M-P')])))
        paths=[]
        for kind,record in (('corpus',corpus),('independent',independent)):
            path=f'segmentation?kind={kind}&id={record["id"]}'
            paths.append(path)
            for index in range(2):
                for target,key in ((word,'@word'),(first,'0:host')):
                    detail=self.api(path)
                    fresh=self.api('lexeme?id='+target['id'])
                    self.api('segmentation-link',dict(kind=kind,id=record['id'],revision=detail['revision'],
                        word=index,key=key,lexeme_id=target['id'],lexeme_revision=fresh['revision']))

        def check(form):
            self.assertEqual(self.api('lexeme?id='+word['id'])['headword'],form+'-pa')
            for path in paths:
                body=self.api(path)['body']
                self.assertEqual([w['form'] for w in body['words']],[form+'-pa',f'«#sub[{form}]-pa»'])
                self.assertEqual(body['translation'],'keep')

        shared=self.api('morpheme?id='+first['id'])
        self.api('morpheme-save',dict(shared,form='na'))
        check('na')
        self.assertEqual(self.undo()[0],200)
        check('ma')
        self.assertEqual(self.undo('redo')[0],200)
        check('na')

    def replace(self, args, plan, **extra):
        return self.api('dictionary-replace-apply', dict(**args, token=plan['token'],
                        keys=[change['key'] for change in plan['changes']],
                        confirm_conflicts=True, **extra))

    def find_headword(self, form):
        return self.api('lexemes?' + urlencode(dict(language='ordos', q=form,
                        search=json.dumps(dict(field='headword', mode='exact')))))['items']

    def stats(self):
        run = self.api('analysis-run', dict(query=dict(kind='counts', scope=dict(mode='language'))))
        result = self.api('analysis-result?' + urlencode(dict(language='ordos', id=run['id'])))
        return result['statistics']

    def form_counts(self):
        run = self.api('analysis-run', dict(query=dict(kind='counts', scope=dict(mode='language'))))
        result = self.api('analysis-result?' + urlencode(dict(language='ordos', id=run['id'],
                                                              vocabulary_view='forms')))
        return {row['form']: row['count'] for row in result['vocabulary']['rows']}

    def test_generated_headword_replacement_is_blocked_but_find_notes_and_independent_work(self):
        _, _, word = self.fixture()
        args, plan = self.preview(scope='current', lexeme_id=word['id'])
        self.assertTrue(plan['blocked'])
        self.assertIn('词形由语素生成', plan['blocked'][0]['reason'])
        generation = self.api('undo-state')['generation']
        code, error = self.call('/api/dictionary-replace-apply', dict(**args, token=plan['token'],
                           keys=[change['key'] for change in plan['changes']], confirm_conflicts=True))
        self.assertEqual(code, 400, error)
        self.assertEqual(self.api('undo-state')['generation'], generation)
        self.assertEqual(self.api('lexeme?id=' + word['id']), word)

        find = self.api('dictionary-replace-preview', {**args, 'find_only': True})
        self.assertTrue(find['changes'])
        self.assertEqual(find['blocked'], [])
        notes = {**args, 'field': 'all', 'find': 'old', 'replacement': 'new'}
        preview = self.api('dictionary-replace-preview', notes)
        self.assertEqual(preview['blocked'], [])
        self.replace(notes, preview)
        updated = self.api('lexeme?id=' + word['id'])
        self.assertEqual(updated['headword'], 'mapa')
        self.assertEqual(updated['body']['notes'], 'new note')
        self.assertEqual(updated['body']['headword_source'], word['body']['headword_source'])
        self.assertEqual(self.undo()[0], 200)
        self.assertEqual(self.api('lexeme?id=' + word['id'])['body'], word['body'])

        independent = self.api('lexeme-save', dict(headword='manual', body={}))
        args, plan = self.preview(scope='current', lexeme_id=independent['id'])
        self.assertEqual(plan['blocked'], [])
        self.replace(args, plan)
        self.assertEqual(self.api('lexeme?id=' + independent['id'])['headword'], 'nanual')

    def test_search_hides_generation_metadata_and_indexes_new_forms_after_replace_and_undo(self):
        first, _, word = self.fixture()
        self.assertEqual([row['id'] for row in self.find_headword('mapa')], [word['id']])
        private = self.api('lexemes?' + urlencode(dict(language='ordos', q='private-source-analysis-87',
                                                     search=json.dumps(dict(field='all')))))
        self.assertEqual(private['items'], [])
        with server.connect(audit=False) as db:
            fields = dictionary_search.SearchIndex(db, 'ordos', [word]).documents[word['id']]
            self.assertFalse(any(key.startswith('headword_source') for key in fields))
            self.assertNotIn('private-source-analysis-87', fields['all'])

        args = dict(kind='morpheme', field='form', find='ma', replacement='na', scope='current',
                    morpheme_id=first['id'])
        preview = self.api('dictionary-replace-preview', args)
        self.assertEqual(preview['blocked'], [])
        self.replace(args, preview)
        self.assertEqual(self.api('lexeme?id=' + word['id'])['headword'], 'napa')
        self.assertEqual([row['id'] for row in self.find_headword('napa')], [word['id']])
        self.assertEqual(self.find_headword('mapa'), [])
        source = self.api('homophone-words?' + urlencode(dict(language='ordos', identity=first['id'])))
        self.assertEqual(source['total'], 1)
        self.assertEqual(source['words'][0]['headword'], 'napa')
        self.assertEqual(self.undo()[0], 200)
        self.assertEqual([row['id'] for row in self.find_headword('mapa')], [word['id']])
        self.assertEqual(self.find_headword('napa'), [])
        self.assertEqual(self.undo('redo')[0], 200)
        self.assertEqual([row['id'] for row in self.find_headword('napa')], [word['id']])

    def test_replace_keeps_sentence_references_original_text_and_statistics(self):
        first, _, word = self.fixture()
        original = '#pass([spoken original], (([mapa],[WORD]),), [original translation])'
        entry = self.seed(original)
        self.link(entry['words'][0]['unit_id'], word)
        independent = self.api('example-save', dict(body=dict(ipa='independent original',
                    words=[dict(form='mapa', gloss='WORD')], targets=[dict(lexeme_id=word['id'])])))
        with server.connect(audit=False) as db:
            before_links = [dict(row) for row in db.execute('SELECT * FROM lexical_links')]
            original_export = self.api('export?id=' + entry['text_id'] + '&original=true')
        baseline = self.stats()
        original_forms = self.form_counts()
        args = dict(kind='morpheme', field='form', find='ma', replacement='na', scope='current',
                    morpheme_id=first['id'])
        plan = self.api('dictionary-replace-preview', args)
        self.assertEqual(plan['blocked'], [])
        self.replace(args, plan)
        changed = self.api('lexeme?id=' + word['id'])
        self.assertEqual(changed['headword'], 'napa')
        current = self.entries()[0]
        self.assertEqual((current['ipa'], current['translation']),
                         (entry['ipa'], entry['translation']))
        self.assertEqual(self.api('export?id=' + entry['text_id'] + '&original=true'), original_export)
        with server.connect(audit=False) as db:
            after_links = [dict(row) for row in db.execute('SELECT * FROM lexical_links')]
        self.assertEqual([(r['id'], r['unit_id'], r['lexeme_id'], r['usage_id'], r['sense_id']) for r in after_links],
                         [(r['id'], r['unit_id'], r['lexeme_id'], r['usage_id'], r['sense_id']) for r in before_links])
        self.assertEqual(self.api('lexeme-examples?id=' + word['id'])['total'], 1)
        examples = self.api('dictionary-examples?id=' + word['id'])
        self.assertTrue(any(item['id'] == independent['id'] for item in examples))
        after = self.stats()
        for field in ('sentences', 'words', 'lexemes', 'texts'):
            self.assertEqual(after[field], baseline[field])
        independent_after = self.api('dictionary-examples?id=' + word['id'])[0]
        expected_forms = Counter(w['form'] for w in current['words'])
        expected_forms.update(w['form'] for w in independent_after['body']['words'])
        self.assertEqual(self.form_counts(), dict(expected_forms))
        self.assertEqual(self.undo()[0], 200)
        self.assertEqual(self.api('lexeme?id=' + word['id'])['headword'], 'mapa')
        self.assertEqual(self.stats()['words'], baseline['words'])
        self.assertEqual(self.form_counts(), original_forms)


if __name__ == '__main__':
    unittest.main()

