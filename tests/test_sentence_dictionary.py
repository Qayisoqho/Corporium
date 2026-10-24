import json
import unittest
from unittest.mock import patch
from pathlib import Path

import server
import test_server


class SentenceDictionaryTests(unittest.TestCase):
    setUp = test_server.APITests.setUp
    tearDown = test_server.APITests.tearDown
    call = test_server.APITests.call

    def api(self, path, body=None):
        status, value = self.call('/api/' + path, body)
        self.assertEqual(status, 200, value)
        return value

    def source(self, kind, pairs):
        if kind == 'independent':
            row = self.api('example-save', dict(body=dict(ipa='source', translation='translation',
                words=[dict(form=f, gloss=g) for f, g in pairs], targets=[])))
        else:
            source = '#pass([source], (' + ''.join('(['+f+'],['+g+']),' for f, g in pairs) + '), [translation])'
            tid = self.api('import', dict(title='Source', content=source))['id']
            row = self.api('entries?text='+tid)['items'][0]
        return dict(kind=kind, id=row['id'])

    def detail(self, src):
        return self.api('segmentation?kind='+src['kind']+'&id='+src['id'])

    def args(self, src, **values):
        return {**src, 'revision': self.detail(src)['revision'], **values}

    def entry(self, form, gloss, **values):
        return self.api('lexeme-save', dict(headword=form, body=dict(usages=[dict(pos='', senses=[dict(short_gloss=gloss)])], **values)))

    def complete(self, src):
        b = self.args(src)
        p = self.api('sentence-gloss-preview', b)
        choices = [dict(word=r['word'], key=r['key'], candidate_id=r['candidates'][0]['id'])
                   for r in p['rows'] if r['automatic']]
        self.api('sentence-gloss-apply', dict(**b, token=p['token'], choices=choices))
        return p

    def intake(self, src, **values):
        b = self.args(src, word=0, key='@word', mode='new', target_kind='lexeme', form='source', gloss='词义', **values)
        p = self.api('sentence-dictionary-preview', b)
        return self.api('sentence-dictionary-apply', dict(**b, token=p['token']))

    def undo(self, redo=False):
        state = self.api('undo-state')
        self.api('redo' if redo else 'undo', dict(generation=state['generation']))

    def test_new_word_and_morpheme_are_linked_with_one_undo_both_sources(self):
        for kind in ('corpus', 'independent'):
            for target_kind in ('lexeme', 'morpheme'):
                with self.subTest(kind=kind, target=target_kind):
                    src = self.source(kind, [('source'+kind+target_kind, '原标注')])
                    b = self.args(src, word=0, key='@word', mode='new', target_kind=target_kind,
                                  form='lemma'+kind+target_kind, gloss='新释义')
                    p = self.api('sentence-dictionary-preview', b)
                    before = self.api('undo-state')['generation']
                    x = self.api('sentence-dictionary-apply', dict(**b, token=p['token']))
                    self.assertEqual(self.api('undo-state')['generation'], before+1)
                    self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], '新释义')
                    with server.connect(audit=False) as db:
                        links = db.execute('SELECT count(*) FROM lexical_links WHERE lexeme_id=?', (x['id'],)).fetchone()[0] if kind == 'corpus' else len(self.detail(src)['body']['targets'])
                        self.assertEqual(links, 1)
                    self.undo(); self.assertEqual(self.call('/api/lexeme?id='+x['id'])[0], 400)
                    self.undo(True); self.assertEqual(self.api('lexeme?id='+x['id'])['target_kind'], target_kind)

    def test_complete_explicit_split_entirely_blank_and_preserve_nonempty(self):
        self.entry('home', '家'); self.entry('ka', 'LOC'); self.entry('stay', '更改')
        for kind in ('corpus', 'independent'):
            src = self.source(kind, [('home-ka', ''), ('stay', '保留'), ('missing', ''), ('#', '')])
            before = self.detail(src)
            p = self.complete(src)
            self.assertEqual(len([r for r in p['rows'] if r['automatic']]), 2)
            after = self.detail(src)
            self.assertEqual([w['gloss'] for w in after['body']['words']], ['家-LOC', '保留', '', ''])
            self.assertEqual(before['words'][0]['id'], after['words'][0]['id'])
            self.assertEqual(after['body']['ipa'], 'source')
            self.undo(); self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], '')
            self.undo(True); self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], '家-LOC')

    def test_ambiguity_requires_choice_and_unique_relaxed_candidate_prefills(self):
        x = self.entry('n', 'GEN', variants=[dict(form='ni')])
        x['body']['usages'][0]['senses'].append(dict(short_gloss='POSS'))
        self.api('lexeme-save', x)
        self.entry('-ka', 'LOC')
        for kind in ('corpus', 'independent'):
            src = self.source(kind, [('ni', ''), ('ka', '')]); b = self.args(src)
            p = self.api('sentence-gloss-preview', b)
            self.assertEqual([len(r['candidates']) for r in p['rows']], [2, 1])
            self.assertEqual([r['automatic'] for r in p['rows']], [False, True])
            choices = [dict(word=r['word'], key=r['key'], candidate_id=r['candidates'][0]['id']) for r in p['rows']]
            self.api('sentence-gloss-apply', dict(**b, token=p['token'], choices=choices))
            self.assertEqual([w['gloss'] for w in self.detail(src)['body']['words']], ['GEN', 'LOC'])

    def test_unicode_features_and_specific_variants(self):
        tag = self.api('grammar-save', dict(symbol='SG', explanation='single'))['id']
        x = self.entry('ǰi', '家', features=[tag], variants=[dict(form='ji', features=[tag])])
        for kind in ('corpus', 'independent'):
            src = self.source(kind, [('ǰi', ''), ('ji', '')]); self.complete(src)
            self.assertEqual([w['gloss'] for w in self.detail(src)['body']['words']], ['家.SG', '家.SG'])
            if kind == 'independent':
                targets = self.detail(src)['body']['targets']
                self.assertEqual(targets[1]['form_id'], x['body']['variants'][0]['id'])

    def test_unique_morpheme_citation_forms_prefill_both_sources_only_after_confirmation(self):
        self.api('morpheme-save',dict(form='-ka',body=dict(gloss='LOC')))
        for kind in ('corpus','independent'):
            src=self.source(kind,[('ka','')]);b=self.args(src)
            p=self.api('sentence-gloss-preview',b)
            self.assertTrue(p['rows'][0]['automatic']);self.assertTrue(p['rows'][0]['candidates'][0]['citation_match'])
            self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'')
            self.complete(src);self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'LOC')
        self.api('morpheme-save',dict(form='ka=',body=dict(gloss='POSS')))
        for kind in ('corpus','independent'):
            src=self.source(kind,[('ka',''),('other','保留')]);p=self.api('sentence-gloss-preview',self.args(src))
            self.assertEqual(len(p['rows'][0]['candidates']),2);self.assertFalse(p['rows'][0]['automatic'])
        self.api('morpheme-save',dict(form='a.b',body=dict(gloss='X')))
        src=self.source('corpus',[('ab','')]);p=self.api('sentence-gloss-preview',self.args(src))
        self.assertTrue(all(not r['automatic'] for r in p['rows']))

    def test_existing_selected_sense_wins_over_homographs_and_preserves_features(self):
        x = self.entry('a', 'first'); x['body']['usages'][0]['senses'].append(dict(short_gloss='second'))
        x = self.api('lexeme-save', x); u = x['body']['usages'][0]
        for kind in ('corpus', 'independent'):
            src = self.source(kind, [('a', '')])
            self.api('segmentation-link', self.args(src, word=0, key='@word', lexeme_id=x['id'],
                lexeme_revision=x['revision'], usage_id=u['id'], sense_id=u['senses'][1]['id']))
            # Selecting a concrete meaning now fills it immediately by inheritance.
            p = self.api('sentence-gloss-preview',self.args(src))
            self.assertEqual(p['rows'],[])
            self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'second')
            if kind == 'independent':self.assertFalse(self.detail(src)['body']['targets'][0]['segmentation_review'])

    def test_preview_read_only_stale_dictionary_and_invalid_batch_atomic(self):
        x = self.entry('a', 'A'); self.entry('b', 'B')
        src = self.source('corpus', [('a', ''), ('b', '')]); b = self.args(src)
        before = self.api('undo-state')
        p = self.api('sentence-gloss-preview', b)
        self.assertEqual(before, self.api('undo-state'))
        choices = [dict(word=r['word'], key=r['key'], candidate_id=r['candidates'][0]['id']) for r in p['rows']]
        self.assertEqual(self.call('/api/sentence-gloss-apply', dict(**b, token=p['token'], choices=choices+[choices[0]]))[0], 400)
        self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], '')
        x['body']['notes'] = 'changed'; self.api('lexeme-save', x)
        self.assertEqual(self.call('/api/sentence-gloss-apply', dict(**b, token=p['token'], choices=choices))[0], 400)
        self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], '')

    def test_scope_and_source_revision_protection(self):
        self.entry('a', 'A'); src = self.source('independent', [('a', '')]); b = self.args(src)
        other = self.api('save-language', dict(name='Other', metadata={}))['id']
        self.assertEqual(self.call('/api/sentence-gloss-preview', dict(**b, _language=other))[0], 400)
        p = self.api('sentence-gloss-preview', b)
        with server.connect(audit=False) as db:db.execute('UPDATE dictionary_examples SET revision=revision+1 WHERE id=?', (src['id'],))
        self.assertEqual(self.call('/api/sentence-gloss-apply', dict(**b, token=p['token'], choices=[]))[0], 400)

    def test_intake_existing_add_sense_and_variant_both_target_types(self):
        for tk in ('lexeme', 'morpheme'):
            x = self.entry('base'+tk, 'old') if tk == 'lexeme' else self.api('morpheme-save', dict(form='base'+tk, body=dict(gloss='old')))
            x = self.api('lexeme?id='+x['id']); u = x['body']['usages'][0]
            for kind, mode in [('corpus', 'sense'), ('independent', 'variant'), ('independent', 'existing')]:
                src = self.source(kind, [('surface'+mode+tk, 'source')])
                x = self.api('lexeme?id='+x['id'])
                b = self.args(src, word=0, key='@word', mode=mode, target_id=x['id'],
                    usage_id=u['id'], sense_id=u['senses'][0]['id'], form='variant'+tk, gloss='new')
                p = self.api('sentence-dictionary-preview', b)
                self.api('sentence-dictionary-apply', dict(**b, token=p['token']))
                self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], 'new' if mode=='sense' else 'old')
                updated = self.api('lexeme?id='+x['id'])
                if mode == 'sense':self.assertEqual(len(updated['body']['usages'][0]['senses']), 2)
                if mode == 'variant':self.assertTrue(any(v['form'] == 'variant'+tk for v in updated['body']['variants']))

    def test_intake_homonym_and_existing_link_confirmation(self):
        self.entry('same', 'old'); src = self.source('corpus', [('same', '原文')])
        b = self.args(src, word=0, key='@word', mode='new', target_kind='lexeme', form='same', gloss='new')
        p = self.api('sentence-dictionary-preview', b)
        self.assertTrue(p['peers'])
        self.assertEqual(self.call('/api/sentence-dictionary-apply', dict(**b, token=p['token']))[0], 400)
        self.api('sentence-dictionary-apply', dict(**b, token=p['token'], confirm_homonym=True))
        b = self.args(src, word=0, key='@word', mode='new', target_kind='morpheme', form='other', gloss='new')
        p = self.api('sentence-dictionary-preview', b)
        self.assertEqual(self.call('/api/sentence-dictionary-apply', dict(**b, token=p['token']))[0], 400)

    def test_save_verification_skips_catalog_search_and_keeps_partial_source_identity(self):
        for kind in ('corpus', 'independent'):
            src = self.source(kind, [('source-part', '原文-部分')])
            b = self.args(src, word=0, key='1:host', mode='new', target_kind='lexeme',
                          form='part'+kind, gloss='词义', query='part')
            full = self.api('sentence-dictionary-preview', b)
            with patch('lexicon.list_lexemes', side_effect=AssertionError('save must not search the catalog')):
                fast = self.api('sentence-dictionary-preview', {**b, 'include_items': False})
                self.assertEqual(full['token'], fast['token'])
                self.assertNotIn('items', fast)
                x = self.api('sentence-dictionary-apply', {**b, 'token': fast['token'], 'include_items': True})
            detail = self.detail(src)
            self.assertEqual(detail['body']['words'][0]['gloss'], '原文-词义')
            self.assertEqual(self.api('lexeme?id='+x['id'])['target_kind'], 'lexeme')
            if kind == 'corpus':
                uid = detail['body']['words'][0]['morphemes'][1]['unit_id']
                self.assertEqual(self.api('unit-dictionary?id='+uid)['link']['lexeme_id'], x['id'])
                self.assertFalse(self.api('unit-dictionary?id='+detail['body']['words'][0]['unit_id'])['link'])
            else:
                self.assertEqual(detail['body']['targets'][0]['segmentation_ref']['key'], '1:host')

    def test_fast_verification_rejects_new_same_form_peer_and_changed_target(self):
        for kind in ('corpus', 'independent'):
            src = self.source(kind, [('source', '原文')])
            b = self.args(src, word=0, key='@word', mode='new', target_kind='lexeme',
                          form='collision'+kind, gloss='词义', include_items=False)
            p = self.api('sentence-dictionary-preview', b)
            x = self.entry(b['form'], '另一义')
            self.assertEqual(self.call('/api/sentence-dictionary-apply', {**b, 'token': p['token'], 'confirm_homonym': True})[0], 400)
            usage = x['body']['usages'][0]
            b.update(mode='existing', target_id=x['id'], usage_id=usage['id'], sense_id=usage['senses'][0]['id'])
            p = self.api('sentence-dictionary-preview', b)
            x['body']['notes'] = 'another window'
            self.api('lexeme-save', x)
            self.assertEqual(self.call('/api/sentence-dictionary-apply', {**b, 'token': p['token']})[0], 400)
    def test_partial_empty_components_and_structural_safety(self):
        self.entry('a', 'A'); self.entry('b', 'B'); self.entry('bad', 'X-Y')
        for kind in ('corpus', 'independent'):
            src = self.source(kind, [('a-b', 'Existing-'), ('bad', ''), ('a-b', 'Mismatch')])
            # Legacy snapshots may retain empty aligned components; current full
            # editors compact them. Exercise the actual stored representation.
            if kind == 'independent':
                with server.connect(audit=False) as db:
                    body=json.loads(db.execute('SELECT body FROM dictionary_examples WHERE id=?',(src['id'],)).fetchone()[0])
                    body['words'][0]['gloss']='Existing-'
                    db.execute('UPDATE dictionary_examples SET body=? WHERE id=?',(json.dumps(body),src['id']))
            p = self.complete(src)
            self.assertEqual([w['gloss'] for w in self.detail(src)['body']['words']], ['Existing-B', '', 'Mismatch'])
            self.assertTrue(p['skipped'])

    def test_completion_keeps_ids_layers_codes_exchange_backup_and_restored_undo(self):
        from restore_backup import restore
        self.entry('a', 'A')
        for kind in ('corpus', 'independent'):
            src = self.source(kind, [('a', '')]); before = self.detail(src)
            layer = self.api('layer-save', dict(name='Extra', font='Junicode'))['id']
            before = self.detail(src)
            self.api('annotation-save', dict(**src, revision=before['revision'], layers=before['layers'], before=[],
                cells=[dict(unit_id=before['words'][0]['id'], layer_id=layer, value='keep')]))
            self.complete(src); after = self.detail(src)
            self.assertEqual(after['words'][0]['id'], before['words'][0]['id'])
            self.assertEqual(after['cells'][0]['value'], 'keep')
        snapshot = Path(self.temp.name)/'backup.json'; snapshot.write_text(json.dumps(self.api('backup')), encoding='utf-8')
        restored = Path(self.temp.name)/'restored.sqlite3'; restore(snapshot, restored)
        old = server.DB
        try:
            server.DB = restored; self.undo()
            self.assertEqual(self.detail(src)['body']['words'][0]['gloss'], '')
        finally:server.DB = old
        bundle = self.api('export-language?language=ordos')
        lid = self.api('save-language', dict(name='Copy', metadata={}))['id']
        self.api('import-language', dict(_language=lid, bundle=bundle))
        self.assertTrue(any(e['words'][0]['gloss'] == 'A' for e in self.api('entries?language='+lid)['items']))

    def test_association_changes_invalidate_preview_without_changing_sentence_revision(self):
        x=self.entry('a','A'); y=self.entry('other','Other');src=self.source('corpus',[('a','')])
        b=self.args(src);p=self.api('sentence-gloss-preview',b);u=y['body']['usages'][0]
        self.api('segmentation-link',dict(**b,word=0,key='@word',lexeme_id=y['id'],lexeme_revision=y['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id']))
        self.assertEqual(self.detail(src)['revision'],b['revision'])
        c=p['rows'][0]['candidates'][0]
        self.assertEqual(self.call('/api/sentence-gloss-apply',dict(**b,token=p['token'],choices=[dict(word=0,key='@word',candidate_id=c['id'])]))[0],400)

    def test_failed_variant_intake_rolls_back_target_and_history(self):
        for tk in ('lexeme','morpheme'):
            x=self.entry('base'+tk,'A') if tk=='lexeme' else self.api('morpheme-save',dict(form='base'+tk,body=dict(gloss='A')))
            x=self.api('lexeme?id='+x['id']);src=self.source('independent',[('new','new')])
            b=self.args(src,word=0,key='@word',mode='variant',target_id=x['id'],form='new',usage_id=x['body']['usages'][0]['id'],sense_id='missing')
            p=self.api('sentence-dictionary-preview',b);before=self.api('undo-state')
            self.assertEqual(self.call('/api/sentence-dictionary-apply',dict(**b,token=p['token']))[0],400)
            self.assertEqual(self.api('lexeme?id='+x['id']),x)
            self.assertEqual(self.api('undo-state'),before)
            self.assertFalse(self.detail(src)['body']['targets'])

    def test_filled_links_follow_future_dictionary_edits_and_only_selected_sentence_changes(self):
        x=self.entry('a','A')
        sources=[self.source(k,[('a','')]) for k in ('corpus','independent')]
        untouched=self.source('independent',[('a','')])
        for src in sources:self.complete(src)
        x['body']['usages'][0]['senses'][0]['short_gloss']='Updated';self.api('lexeme-save',x)
        for src in sources:self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'Updated')
        self.assertEqual(self.detail(untouched)['body']['words'][0]['gloss'],'')

    def test_partial_selection_keeps_explicit_boundaries_for_later_completion(self):
        self.entry('a','A');self.entry('b','B')
        for kind in ('corpus','independent'):
            src=self.source(kind,[('a=b','')]);b=self.args(src);p=self.api('sentence-gloss-preview',b)
            row=p['rows'][0];c=row['candidates'][0]
            self.api('sentence-gloss-apply',dict(**b,token=p['token'],choices=[dict(word=row['word'],key=row['key'],candidate_id=c['id'])]))
            self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'A=')
            self.complete(src);self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'A=B')

    def test_script_gloss_and_empty_infix_skip_preserve_original_data(self):
        self.entry('a','neg#sub[POT]');self.entry('x','X')
        for kind in ('corpus','independent'):
            src=self.source(kind,[('a',''),('a<x>','')]);p=self.complete(src)
            self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'neg#sub[POT]')
            self.assertEqual(self.detail(src)['body']['words'][1]['form'],'a<x>')
            self.assertEqual(self.detail(src)['body']['words'][1]['gloss'],'')
            self.assertEqual(len(p['skipped']),1)


if __name__ == '__main__':unittest.main()
