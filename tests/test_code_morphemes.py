import copy
import io
import json
import unittest
from pathlib import Path

import code_morphemes
import code_switching
import server
import test_code_switching


class CodeMorphemeLayoutTests(unittest.TestCase):
    def layout(self, form, gloss, **extra):
        return code_morphemes.layout(dict(words=[dict(id='word', position=0)],
            body=dict(ipa='', translation='', words=[dict(form=form, gloss=gloss, **extra)])))[0]

    def test_cells_partition_scripts_astral_combining_and_all_boundaries(self):
        for form, gloss in [('𐐀á#sup[21]-na=ke', '家-GEN.SG=CL'),
                            ('a+b~c', 'A+B~C'), ('« a-na,', '“家-GEN.”')]:
            with self.subTest(form=form):
                w = self.layout(form, gloss)
                self.assertTrue(w['selectable'])
                for field, raw in [('form', form), ('gloss', gloss)]:
                    self.assertEqual(''.join(raw[c[field][0]:c[field][1]] for c in w['cells']), raw)
                self.assertEqual(len(w['morphemes']), 3 if form != '« a-na,' else 2)
        self.assertEqual(len(self.layout('a-na', 'A-GEN.SG')['morphemes']), 2)

    def test_infixes_and_discontinuous_hosts_do_not_require_duplicate_glosses(self):
        for form, gloss in [('so<l>ma', 'home<PL>'), ('so<l>ma', '<PL>home'),
                            ('so<l><u>ma', 'home<PL><EMPH>')]:
            w = self.layout(form, gloss)
            self.assertTrue(w['selectable'])
            self.assertEqual(len(w['morphemes']), 3 if '<u>' in form else 2)
            for field, raw in [('form', form), ('gloss', gloss)]:
                self.assertEqual(''.join(raw[c[field][0]:c[field][1]] for c in w['cells']), raw)
        self.assertFalse(self.layout('so<l>ma', 'home<1>3>')['selectable'])
        self.assertFalse(self.layout('a-b', 'A')['selectable'])

    def test_empty_punctuation_and_boundaries_have_no_selectable_units(self):
        for form, gloss, extra in [('', '', {}), ('##', '#', {}), (',', '', dict(punctuation=True, punctuation_form=','))]:
            self.assertFalse(self.layout(form, gloss, **extra)['selectable'])
        w = self.layout('-a', '-A')
        self.assertEqual(len(w['morphemes']), 1)
        self.assertTrue(all(c['key'] is None for c in w['cells'] if c['form'][0] == c['form'][1]))

    def test_snapshot_shape_preserves_evidence_and_rejects_malformed_units(self):
        w = self.layout('a-na', 'A-GEN'); snap = code_morphemes.snapshot(w, w['morphemes'][:1])
        self.assertTrue(code_morphemes.validate(snap))
        self.assertTrue(code_morphemes.matching(snap, self.layout('a-na', '家-SG'), w['morphemes'][0]))
        self.assertFalse(code_morphemes.matching(snap, self.layout('a-NA', 'A-GEN'), w['morphemes'][0]))
        for value in [None, [], {}, dict(version=2, form='a', units=[]), {**snap, 'units': [snap['units'][0]] * 2}]:
            self.assertFalse(code_morphemes.validate(value))


class CodeMorphemeTests(unittest.TestCase):
    for _name in ('setUp', 'tearDown', 'call', 'api', 'seed', 'detail', 'mark', 'undo', 'session', 'link'):
        locals()[_name] = getattr(test_code_switching.CodeSwitchingTests, _name)

    def prepare(self, form='root-na=ke', gloss='root-GEN.SG=CL'):
        self.seed()
        for kind in ('corpus', 'independent'):
            self.replace(kind, [dict(form=form, gloss=gloss)])

    def replace(self, kind, words, slot_ids=None):
        rid = self.eid if kind == 'corpus' else self.ind
        d = self.api('annotations?kind=' + kind + '&id=' + rid)
        d['body']['words'] = words
        if slot_ids is None:
            slot_ids = [w['id'] for w in d['words'][:len(words)]]
            slot_ids += ['new:' + str(i) for i in range(len(slot_ids), len(words))]
        return self.api('inline-save', dict(kind=kind, id=rid, revision=d['revision'], before=d['cells'],
            layers=d['layers'], slot_ids=slot_ids, body=d['body'], cells=[], delete_confirmed=True))

    def tag(self, picks=((0, 0),), kind='corpus', span=None, code='zh', **extra):
        d = self.detail(kind)
        return self.api('code-save', dict(kind=kind, record_id=d['id'], id=span, token=d['token'],
            morpheme_ids=[d['words'][wi]['morphemes'][mi]['id'] for wi, mi in picks],
            code_id=getattr(self, code) if code else None, **extra))

    def test_both_sources_share_morpheme_display_without_rewriting_material(self):
        self.prepare()
        with server.connect() as db:
            before = {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t + ' ORDER BY id')]
                      for t in ('entries', 'corpus_units', 'dictionary_examples')}
        for kind in ('corpus', 'independent'):
            self.tag(kind=kind)
            d = self.detail(kind); self.assertTrue(d['profile']['mixed'])
            self.assertEqual(len(d['spans'][0]['morpheme_ids']), 1)
        found = self.api('entries?include_independent=true&code_mode=mixed')
        self.assertEqual(found['total'], 2); self.assertEqual(found['code_summary']['mixed'], 2)
        for body in found['items']:
            w = body['words'][0]; self.assertNotIn('code_mark', w)
            cells = w['code_cells']; self.assertEqual(sum('mark' in c for c in cells), 1)
            self.assertTrue(cells[0]['mark']['end']); self.assertEqual(cells[0]['form'], [0, 4])
        with server.connect() as db:
            for t, rows in before.items():
                self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM ' + t + ' ORDER BY id')], rows)

    def test_separate_codes_share_parent_word_and_full_code_coverage_is_not_mixing(self):
        self.prepare()
        self.tag(); self.tag(((0, 1),), code='ru')
        self.assertEqual(len(self.detail()['spans']), 2)
        self.assertTrue(self.detail()['profile']['mixed'])
        d = self.detail(); generation = self.api('undo-state')['generation']
        bad = dict(kind='corpus', record_id=self.eid, token=d['token'], code_id=self.ru,
                   morpheme_ids=[d['words'][0]['morphemes'][0]['id']])
        self.assertEqual(self.call('/api/code-save', bad)[0], 400)
        self.assertEqual(self.api('undo-state')['generation'], generation)
        self.undo(); self.undo()
        self.tag(((0, 0), (0, 1), (0, 2)))
        self.assertFalse(self.detail()['profile']['mixed'])
        marks = [c['mark'] for c in self.api('entries')['items'][0]['words'][0]['code_cells'] if c.get('mark')]
        self.assertEqual([m['end'] for m in marks], [False, False, True])
        self.assertEqual(self.api('entries?code_mode=mixed')['total'], 0)

    def test_contiguous_selection_stale_tokens_and_legacy_overlap(self):
        self.prepare(); d = self.detail()
        payload = dict(kind='corpus', record_id=self.eid, token=d['token'], code_id=self.zh,
                       morpheme_ids=[d['words'][0]['morphemes'][i]['id'] for i in (0, 2)])
        self.assertEqual(self.call('/api/code-save', payload)[0], 400)
        self.mark(indexes=(0,))
        payload['morpheme_ids'] = [d['words'][0]['morphemes'][0]['id']]
        self.assertEqual(self.call('/api/code-save', payload)[0], 400)
        payload['token'] = self.detail()['token']
        self.assertEqual(self.call('/api/code-save', payload)[0], 400)
        old = self.detail()['spans'][0]
        self.assertTrue(old['legacy']); self.assertEqual(len(old['morpheme_ids']), 3)
        self.tag(((0, 0), (0, 1), (0, 2)), span=old['id'])
        self.assertFalse(self.detail()['spans'][0]['legacy'])

    def test_inserted_words_break_runs_and_reordering_follows_saved_parents(self):
        self.prepare()
        words = [dict(form='one-a', gloss='one-A'), dict(form='two-b', gloss='two-B')]
        self.replace('corpus', copy.deepcopy(words))
        self.tag(((0, 0), (0, 1), (1, 0), (1, 1)))
        old = self.detail()['spans'][0]; ids = old['word_ids']
        self.replace('corpus', [words[0], dict(form='new', gloss='NEW'), words[1]], [ids[0], 'new:middle', ids[1]])
        d = self.detail(); self.assertTrue(d['profile']['mixed'])
        self.assertEqual(d['spans'][0]['morpheme_ids'], old['morpheme_ids'])
        body = self.api('entries')['items'][0]
        self.assertTrue([c['mark'] for c in body['words'][0]['code_cells'] if c.get('mark')][-1]['end'])
        self.assertTrue([c['mark'] for c in body['words'][2]['code_cells'] if c.get('mark')][-1]['end'])
        self.tag(((0, 0), (0, 1), (2, 0), (2, 1)), span=old['id'], notes='same original cells')
        self.replace('corpus', [words[1], dict(form='new', gloss='NEW'), words[0]], [ids[1], d['words'][1]['id'], ids[0]])
        self.assertEqual(self.detail()['spans'][0]['text'], 'two · b one · a')
        self.assertFalse(self.detail()['spans'][0]['review'])

    def test_legacy_metadata_can_be_edited_without_dropping_unsegmented_words(self):
        self.prepare()
        self.replace('corpus', [dict(form='a-b', gloss='unsegmented'), dict(form='c', gloss='C')])
        self.mark(indexes=(0, 1)); before = self.detail()['spans'][0]
        self.assertEqual(len(before['morpheme_ids']), 1)
        self.mark(indexes=(0, 1), span=before['id'], code='ru', notes='metadata only')
        current = self.detail()['spans'][0]
        self.assertTrue(current['legacy']); self.assertEqual(current['word_ids'], before['word_ids'])
        self.assertEqual(current['snapshot'], before['snapshot'])
        self.assertFalse(current['review'])
        self.assertEqual(self.api('entries?code_id=' + self.ru)['total'], 1)

    def test_gloss_corrections_remain_attached_form_or_cut_changes_do_not_guess(self):
        self.prepare(); self.tag()
        old = copy.deepcopy(self.detail()['spans'][0])
        self.replace('corpus', [dict(form='root-na=ke', gloss='家-GEN.PL=CL')])
        current = self.detail()['spans'][0]
        self.assertFalse(current['review']); self.assertEqual(current['morpheme_ids'], old['morpheme_ids'])
        self.replace('corpus', [dict(form='roo-tna=ke', gloss='家-GEN.PL=CL')])
        current = self.detail()['spans'][0]
        self.assertTrue(current['unavailable']); self.assertEqual(current['morpheme_ids'], [])
        self.assertEqual(current['snapshot'], old['snapshot'])
        self.assertNotIn('code_cells', self.api('entries')['items'][0]['words'][0])
        self.undo(); self.assertEqual(self.detail()['spans'][0]['morpheme_ids'], old['morpheme_ids'])

    def test_infix_and_circumfix_mark_logical_units_and_each_actual_code_run(self):
        self.prepare('so<l>ma', 'home<PL>'); self.tag(((0, 1),))
        w = self.api('entries')['items'][0]['words'][0]
        marked = [c for c in w['code_cells'] if c.get('mark')]
        self.assertEqual([w['form'][c['form'][0]:c['form'][1]] for c in marked], ['l'])
        self.undo(); self.replace('corpus', [dict(form='we-amos-la', gloss='PST-go-PST')])
        d = self.api('segmentation?kind=corpus&id=' + self.eid)
        self.api('segmentation-save', dict(kind='corpus', id=self.eid, revision=d['revision'], word=0,
            action='save', members=['0:host', '2:host'], type='circumfix', gloss='PST'))
        self.tag(); self.assertEqual(len(self.detail()['spans'][0]['morpheme_ids']), 1)
        w = self.api('entries')['items'][0]['words'][0]
        marked = [c for c in w['code_cells'] if c.get('mark')]
        self.assertEqual([w['form'][c['form'][0]:c['form'][1]] for c in marked], ['we', 'la'])
        self.assertEqual([c['mark']['end'] for c in marked], [True, True])
        self.assertTrue(self.detail()['profile']['mixed'])

    def test_manual_audio_metadata_undo_and_legacy_conversion_keep_exact_correspondence(self):
        self.prepare(); self.mark(indexes=(0,)); span = self.detail()['spans'][0]['id']
        _, _, interval, _ = self.session(); self.link(span, interval)
        self.tag(((0, 0), (0, 1), (0, 2)), span=span, notes='quotation')
        self.assertEqual(next(i for i in self.detail()['intervals'] if i['id'] == interval)['span_id'], span)
        self.tag(((0, 0),), span=span)
        self.assertIsNone(next(i for i in self.detail()['intervals'] if i['id'] == interval)['span_id'])
        self.undo(); self.assertEqual(next(i for i in self.detail()['intervals'] if i['id'] == interval)['span_id'], span)
        self.undo('redo'); self.assertIsNone(next(i for i in self.detail()['intervals'] if i['id'] == interval)['span_id'])

    def test_word_transfer_copy_and_move_remap_morpheme_occurrences(self):
        self.prepare(); self.tag(((0, 1),))
        original = self.detail()['spans'][0]
        a = self.api('word-transfer-snapshot?kind=corpus&id=' + self.eid)
        z = self.api('word-transfer-snapshot?kind=independent&id=' + self.ind)
        payload = dict(source=dict(kind='corpus', id=self.eid, token=a['transfer_token']),
            target=dict(kind='independent', id=self.ind, token=z['transfer_token']),
            slots=[a['words'][0]['id']], mode='copy', confirmed=True)
        self.api('word-transfer', payload)
        copied = self.detail('independent')['spans'][0]
        self.assertEqual(copied['text'], 'na'); self.assertFalse(copied['review'])
        self.assertNotEqual(copied['morpheme_ids'], original['morpheme_ids'])
        self.undo()
        self.api('add', dict(text_id=self.tid))
        target = next(e['id'] for e in self.api('entries')['items'] if e['id'] != self.eid)
        a = self.api('word-transfer-snapshot?kind=corpus&id=' + self.eid)
        z = self.api('word-transfer-snapshot?kind=corpus&id=' + target)
        payload.update(source=dict(kind='corpus', id=self.eid, token=a['transfer_token']),
            target=dict(kind='corpus', id=target, token=z['transfer_token']), mode='move')
        self.api('word-transfer', payload)
        self.assertEqual(self.detail()['spans'], [])
        self.assertFalse(self.detail(rid=target)['spans'][0]['review'])
        self.undo(); self.assertEqual(self.detail()['spans'][0]['morpheme_ids'], original['morpheme_ids'])

    def test_sentence_and_whole_text_copies_and_exchange_remap_only_parent_ids(self):
        self.prepare(); self.tag(((0, 1),)); self.tag(((0, 2),), kind='independent')
        e = self.api('entries')['items'][0]
        copied = self.api('duplicate-entry', dict(id=self.eid, text_id=self.tid, revision=e['revision'], order=[self.eid], where='end'))
        self.assertFalse(self.detail(rid=copied['id'])['spans'][0]['review'])
        plan = self.api('text-copy-preview?id=' + self.tid)
        text = self.api('copy-text', dict(id=self.tid, token=plan['token'], title='Copied'))
        for entry in self.api('entries?text=' + text['id'])['items']:
            self.assertFalse(self.detail(rid=entry['id'])['spans'][0]['review'])
        bundle = self.api('export-language?language=ordos')
        target = self.api('save-language', dict(name='Copy', metadata={}))['id']
        self.api('import-language', dict(bundle=bundle, _language=target))
        self.assertEqual(self.api('entries?language=' + target + '&include_independent=true&code_mode=mixed')['total'], 5)
        with server.connect() as db: code_switching.validate(db)

    def test_streamed_package_backup_and_localization_keep_raw_snapshots(self):
        import language_exchange
        import streaming_json
        import ui_localization
        from restore_backup import restore
        self.prepare(); self.tag()
        with server.connect() as db:
            out = io.BytesIO(); streaming_json.write(language_exchange.export_bundle(db, 'ordos', stream=True), out)
        staged = streaming_json.read(io.StringIO(out.getvalue().decode()))
        try:
            target = self.api('save-language', dict(name='Streamed', metadata={}))['id']
            self.api('import-language', dict(bundle=dict(staged), _language=target))
        finally: staged.close()
        self.assertEqual(self.api('entries?language=' + target + '&code_mode=mixed')['total'], 1)
        path = Path(self.temp.name) / 'code-backup.json'; path.write_text(json.dumps(self.api('backup')), 'utf-8')
        destination = Path(self.temp.name) / 'restored.sqlite3'; restore(path, destination)
        original = server.DB; server.DB = destination
        try:
            self.assertFalse(self.detail()['spans'][0]['review'])
            self.undo(); self.assertEqual(self.detail()['spans'], [])
        finally: server.DB = original
        message = '所选语素已有语码标记，请先编辑或移除原标记'
        presented = ui_localization.present(dict(error=message, body=dict(gloss=message)), '/api/code-save', 'en')
        self.assertNotEqual(presented['error'], message); self.assertEqual(presented['body']['gloss'], message)
        # A span must have one range format. Mixed-format evidence could make
        # legacy words disappear when a newer editor saves the resolvable cells.
        malformed = self.api('export-language?language=ordos')
        row = malformed['code_spans'][0]
        ids = json.loads(row['word_ids']); snap = json.loads(row['snapshot'])
        ids.append('missing:legacy'); snap[ids[-1]] = 'old word'
        row.update(word_ids=json.dumps(ids), snapshot=json.dumps(snap))
        failed = self.api('save-language', dict(name='Rejected mixed format', metadata={}))['id']
        self.assertEqual(self.call('/api/import-language', dict(bundle=malformed, _language=failed))[0], 400)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM code_spans WHERE language_id=?', (failed,)).fetchone()[0], 0)
