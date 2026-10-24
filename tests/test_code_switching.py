import json
import unittest
from contextlib import closing
from pathlib import Path
import server
import code_switching
import test_server
from restore_backup import restore


class CodeSwitchingTests(unittest.TestCase):
    setUp = test_server.APITests.setUp
    tearDown = test_server.APITests.tearDown
    call = test_server.APITests.call

    def api(self, path, body=None):
        if body is None and 'language=' not in path:path+=('&' if '?' in path else '?')+'language=ordos'
        status, data = self.call('/api/' + path, body)
        self.assertEqual(status, 200, (path, data))
        return data

    def seed(self):
        self.tid = self.api('import', dict(title='混用验证', content='#pass([a ni hao b], (([a],[A]),([ni],[你]),([hao],[好]),([b],[B])), [你好])'))['id']
        self.eid = self.api('entries')['items'][0]['id']
        self.ind = self.api('example-save', dict(body=dict(ipa='a ni hao b', words=[dict(form=f, gloss=f) for f in ('a', 'ni', 'hao', 'b')], targets=[])))['id']
        self.zh = self.api('timeline-code-save', dict(name='汉语', metadata=dict(number='ZH')))['id']
        self.ru = self.api('timeline-code-save', dict(name='俄语', metadata=dict(number='RU')))['id']

    def detail(self, kind='corpus', rid=None):
        return self.api('code-detail?kind=' + kind + '&id=' + (rid or (self.eid if kind == 'corpus' else self.ind)))

    def mark(self, indexes=(1, 2), code='zh', kind='corpus', rid=None, span=None, **extra):
        d = self.detail(kind, rid)
        return self.api('code-save', dict(kind=kind, record_id=d['id'], token=d['token'], id=span,
                        word_ids=[d['words'][i]['id'] for i in indexes], code_id=getattr(self, code) if code else None, **extra))

    def undo(self, action='undo'):
        return self.api(action, dict(generation=self.api('undo-state')['generation']))

    def session(self, kind='corpus', rid=None):
        sid = self.api('timeline-create', dict(name='测试'))['id']
        def change(action, **kw):
            rev = self.api('timeline-detail?id=' + sid)['session']['revision']
            return self.api('timeline-' + action, dict(id=sid, revision=rev, **kw))
        track = self.api('timeline-detail?id=' + sid)['tracks'][0]['id']
        change('interval', track_id=track, entry_id=rid or (self.eid if kind == 'corpus' else 'independent:' + self.ind), start_ms=0, end_ms=5000)
        parent = self.api('timeline-detail?id=' + sid)['intervals'][0]['id']
        change('track', name='语言', kind='language', parent_id=track)
        child_track = next(t for t in self.api('timeline-detail?id=' + sid)['tracks'] if t['kind']=='language')['id']
        change('interval', track_id=child_track, parent_id=parent, code_id=self.zh, start_ms=1000, end_ms=2000)
        interval = next(i for i in self.api('timeline-detail?id=' + sid)['intervals'] if i['parent_id'])['id']
        return sid, parent, interval, change

    def link(self, span, interval, kind='corpus', action='link'):
        d = self.detail(kind)
        i = next(i for i in d['intervals'] if i['id'] == interval)
        return self.api('code-' + action, dict(kind=kind, record_id=d['id'], id=span, token=d['token'], interval_id=interval, interval_revision=i['revision']))

    def test_both_sentence_sources_search_statistics_and_shared_display(self):
        self.seed()
        for kind in ('corpus', 'independent'):
            self.mark(kind=kind)
            d = self.detail(kind)
            self.assertTrue(d['profile']['mixed']); self.assertEqual(d['spans'][0]['positions'], [1, 2])
        found = self.api('entries?include_independent=true&code_mode=mixed&code_id=' + self.zh)
        self.assertEqual(found['total'], 2)
        self.assertEqual(found['code_summary']['mixed'], 2)
        self.assertEqual(found['code_summary']['languages'], [dict(id=self.zh, name='汉语', sentences=2)])
        for e in found['items']:
            self.assertEqual(e['words'][1]['code_mark']['name'], '汉语')
            self.assertTrue(e['words'][1]['code_mark']['start']); self.assertFalse(e['words'][2]['code_mark']['start'])
        self.assertEqual(self.api('example-library?source=independent&code_mode=mixed')['total'], 1)
        self.assertEqual(self.api('entries?code_mode=mixed&q=absent')['code_summary']['mixed'], 0)

    def test_one_foreign_code_for_entire_sentence_is_not_mixing_and_unknown_is_not_a_language(self):
        self.seed(); self.mark(indexes=(0, 1, 2, 3))
        self.assertFalse(self.detail()['profile']['mixed'])
        self.assertEqual(self.api('entries?code_mode=mixed')['total'], 0)
        self.assertEqual(self.api('entries?code_id=' + self.zh)['total'], 1)
        s = self.detail()['spans'][0]['id']; self.mark(indexes=(0, 1, 2, 3), code=None, span=s)
        self.assertFalse(self.detail()['profile']['mixed'])
        self.assertEqual(self.api('entries?code_id=' + self.zh)['total'], 0)

    def test_explicit_default_language_mapping_does_not_invent_a_second_code(self):
        self.seed()
        self.zh = self.api('timeline-code-save', dict(name='鄂尔多斯', metadata=dict(workspace_language_id='ordos')))['id']
        self.mark(); self.assertFalse(self.detail()['profile']['mixed'])
        self.mark(indexes=(3,), code='ru'); self.assertTrue(self.detail()['profile']['mixed'])

    def test_overlap_stale_scope_and_invalid_range_are_rejected_atomically(self):
        self.seed(); stale = self.detail(); self.mark()
        payload = dict(kind='corpus', record_id=self.eid, token=stale['token'], word_ids=[stale['words'][0]['id']], code_id=self.zh)
        self.assertEqual(self.call('/api/code-save', payload)[0], 400)
        d = self.detail(); payload['token'] = d['token']; payload['word_ids'] = [d['words'][0]['id'], d['words'][2]['id']]
        self.assertEqual(self.call('/api/code-save', payload)[0], 400)
        payload['word_ids'] = [d['words'][1]['id']]
        self.assertEqual(self.call('/api/code-save', payload)[0], 400)
        payload['word_ids'] = [d['words'][0]['id']]; payload['_language'] = 'other'
        self.assertEqual(self.call('/api/code-save', payload)[0], 400)
        self.assertEqual(len(self.detail()['spans']), 1)

    def test_undo_redo_and_language_catalog_cannot_be_removed_while_referenced(self):
        self.seed(); self.mark();generation=self.api('undo-state')['generation'];self.mark(span=self.detail()['spans'][0]['id'])
        self.assertEqual(self.api('undo-state')['generation'],generation)
        self.undo(); self.assertEqual(self.detail()['spans'], [])
        self.undo('redo'); self.assertTrue(self.detail()['profile']['mixed'])
        code = next(c for c in self.detail()['codes'] if c['id'] == self.zh)
        self.assertEqual(self.call('/api/timeline-code-delete', dict(record_id=self.zh, revision=code['revision'], confirmed=True))[0], 400)
        self.assertTrue(self.detail()['profile']['mixed'])

    def test_audio_links_and_code_changes_are_one_undoable_operation_for_both_sources(self):
        self.seed()
        for kind in ('corpus', 'independent'):
            self.mark(kind=kind); span = self.detail(kind)['spans'][0]['id']
            sid, parent, interval, change = self.session(kind)
            self.link(span, interval, kind)
            self.mark(kind=kind, code='ru', span=span)
            audio = next(i for i in self.api('timeline-detail?id=' + sid)['intervals'] if i['id'] == interval)
            self.assertEqual(audio['code_id'], self.ru)
            self.undo()
            audio = next(i for i in self.api('timeline-detail?id=' + sid)['intervals'] if i['id'] == interval)
            self.assertEqual(audio['code_id'], self.zh)
            change('delete-interval', interval_id=interval, confirmed=True)
            self.assertEqual(len(self.detail(kind)['spans']), 1)
            self.undo(); self.assertTrue(next(i for i in self.detail(kind)['intervals'] if i['id'] == interval)['span_id'])

    def test_audio_cannot_point_to_another_sentence_or_override_a_linked_code(self):
        self.seed(); self.mark(); span = self.detail()['spans'][0]['id']
        sid, parent, interval, change = self.session()
        self.link(span, interval)
        detail = self.api('timeline-detail?id=' + sid); i = next(i for i in detail['intervals'] if i['id'] == interval)
        status, _ = self.call('/api/timeline-interval', dict(id=sid, revision=detail['session']['revision'], interval_id=interval, track_id=i['track_id'], parent_id=parent, code_id=self.ru, start_ms=1000, end_ms=2000))
        self.assertEqual(status, 400)
        self.mark(indexes=(0,), span=span)
        self.assertIsNone(next(i for i in self.detail()['intervals'] if i['id'] == interval)['span_id'])
        self.undo(); self.assertEqual(next(i for i in self.detail()['intervals'] if i['id'] == interval)['span_id'], span)

    def test_inline_word_reordering_insertion_and_changes_keep_identities_and_review(self):
        self.seed(); self.mark(); span = self.detail()['spans'][0]; original_ids = span['word_ids']
        d = self.api('annotations?kind=corpus&id=' + self.eid)
        words = d['body']['words']; words.insert(2, dict(form='inserted', gloss='NEW'))
        ids = [w['id'] for w in d['words']]; ids.insert(2, 'new:insert')
        self.api('inline-save', dict(kind='corpus', id=self.eid, revision=d['revision'], before=d['cells'], layers=d['layers'], slot_ids=ids, body=d['body'], cells=[]))
        s = self.detail()['spans'][0]
        self.assertEqual(s['word_ids'], original_ids); self.assertEqual(s['positions'], [1, 3]); self.assertFalse(s['review'])
        d=self.api('annotations?kind=corpus&id='+self.eid);d['body']['words'].reverse()
        self.api('inline-save',dict(kind='corpus',id=self.eid,revision=d['revision'],before=d['cells'],layers=d['layers'],slot_ids=[w['id'] for w in reversed(d['words'])],body=d['body'],cells=[]))
        self.assertEqual(self.detail()['spans'][0]['text'],'hao ni')
        d = self.api('annotations?kind=corpus&id=' + self.eid); d['body']['words'][1]['form'] = 'changed'
        self.api('inline-save', dict(kind='corpus', id=self.eid, revision=d['revision'], before=d['cells'], layers=d['layers'], slot_ids=[w['id'] for w in d['words']], body=d['body'], cells=[]))
        self.assertTrue(self.detail()['spans'][0]['review'])
        self.assertEqual(self.api('entries?code_mode=review')['total'], 1)
        self.undo(); self.assertFalse(self.detail()['spans'][0]['review'])

    def test_sentence_copy_keeps_marks_with_new_ids_but_does_not_copy_recording_links(self):
        self.seed(); self.mark(); source = self.detail()['spans'][0]
        e = self.api('entries')['items'][0]
        copied = self.api('duplicate-entry', dict(id=self.eid, text_id=self.tid, revision=e['revision'], order=[self.eid], where='end'))
        other = self.detail(rid=copied['id'])['spans'][0]
        self.assertNotEqual(other['id'], source['id']); self.assertTrue(set(other['word_ids']).isdisjoint(source['word_ids']))
        self.assertEqual(other['text'], source['text'])

    def test_json_backup_and_language_exchange_preserve_marks_codes_and_audio_mapping(self):
        self.seed(); self.mark(); self.mark(kind='independent')
        sid, parent, interval, change = self.session(); self.link(self.detail()['spans'][0]['id'], interval)
        backup = self.api('backup'); path = Path(self.temp.name) / 'backup.json'; path.write_text(json.dumps(backup), 'utf-8')
        dest = Path(self.temp.name) / 'restored.sqlite3'; restore(path, dest)
        original = server.DB; server.DB = dest
        try:
            self.assertTrue(self.detail()['profile']['mixed'])
            self.assertEqual(self.api('entries?include_independent=true&code_mode=mixed')['total'], 2)
        finally: server.DB = original
        bundle = self.api('export-language?language=ordos')
        new_language = self.api('save-language', dict(name='副本语言', metadata={}))['id']
        self.api('import-language', dict(bundle=bundle, _language=new_language))
        found = self.api('entries?language=' + new_language + '&include_independent=true&code_mode=mixed')
        self.assertEqual(found['total'], 2)
        with server.connect() as db:
            code_switching.validate(db)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM code_spans WHERE language_id=?', (new_language,)).fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM code_time_links l JOIN code_spans s ON s.id=l.span_id WHERE s.language_id=?', (new_language,)).fetchone()[0], 1)

    def test_partial_word_transfer_carries_codes_and_detaches_only_recording_correspondence(self):
        self.seed(); self.mark(); sid, parent, interval, change=self.session()
        span=self.detail()['spans'][0];self.link(span['id'],interval)
        a=self.api('word-transfer-snapshot?kind=corpus&id='+self.eid)
        z=self.api('word-transfer-snapshot?kind=independent&id='+self.ind)
        payload=dict(source=dict(kind='corpus',id=self.eid,token=a['transfer_token']),target=dict(kind='independent',id=self.ind,token=z['transfer_token']),slots=[a['words'][1]['id']],mode='copy',confirmed=True,position=1)
        self.api('word-transfer',payload)
        copied=self.detail('independent')['spans'][0]
        self.assertEqual(copied['text'],'ni');self.assertNotIn(copied['word_ids'][0],span['word_ids'])
        self.assertEqual(len(self.detail()['spans'][0]['word_ids']),2)
        self.undo()
        self.api('add',dict(text_id=self.tid))
        target=next(e['id'] for e in self.api('entries?text='+self.tid)['items'] if e['id']!=self.eid)
        a=self.api('word-transfer-snapshot?kind=corpus&id='+self.eid);z=self.api('word-transfer-snapshot?kind=corpus&id='+target)
        payload.update(source=dict(kind='corpus',id=self.eid,token=a['transfer_token']),target=dict(kind='corpus',id=target,token=z['transfer_token']),mode='move',position=len(z['words']))
        self.api('word-transfer',payload)
        self.assertEqual(self.detail()['spans'][0]['text'],'hao')
        self.assertIsNone(next(i for i in self.detail()['intervals'] if i['id']==interval)['span_id'])
        self.undo();self.assertEqual(self.detail()['spans'][0]['text'],'ni hao')
        self.assertEqual(next(i for i in self.detail()['intervals'] if i['id']==interval)['span_id'],span['id'])

    def test_mark_edit_invalidates_word_transfer_snapshot_without_changing_sentence_revision(self):
        self.seed();self.mark();a=self.api('word-transfer-snapshot?kind=corpus&id='+self.eid);z=self.api('word-transfer-snapshot?kind=independent&id='+self.ind)
        span=self.detail()['spans'][0]['id'];self.mark(span=span,code='ru')
        status,_=self.call('/api/word-transfer',dict(source=dict(kind='corpus',id=self.eid,token=a['transfer_token']),target=dict(kind='independent',id=self.ind,token=z['transfer_token']),slots=[a['words'][1]['id']],mode='copy',confirmed=True))
        self.assertEqual(status,400);self.assertEqual(self.detail('independent')['spans'],[])

    def test_deleting_original_sentence_removes_marks_and_undo_restores_them(self):
        self.seed();self.mark();e=self.api('entries')['items'][0]
        self.api('delete-entry',dict(id=self.eid,text_id=self.tid,revision=e['revision'],confirmed=True))
        with server.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM code_spans').fetchone()[0],0)
        self.undo();self.assertTrue(self.detail()['profile']['mixed'])

    def test_streamed_exchange_remaps_default_language_codes(self):
        import io,language_exchange,streaming_json,languages
        self.seed();self.zh=self.api('timeline-code-save',dict(name='本语言',metadata=dict(workspace_language_id='ordos')))['id']
        self.mark();self.mark(indexes=(3,),code='ru')
        with server.connect() as db:
            bundle=language_exchange.export_bundle(db,'ordos',stream=True);out=io.BytesIO();streaming_json.write(bundle,out)
        staged=streaming_json.read(io.StringIO(out.getvalue().decode()))
        try:
            target=self.api('save-language',dict(name='流式副本',metadata={}))['id']
            self.api('import-language',dict(bundle=dict(staged),_language=target))
            with server.connect() as db:
                codes=[json.loads(r[0]).get('workspace_language_id') for r in db.execute('SELECT metadata FROM timeline_codes WHERE name=?',('本语言',))]
                self.assertIn(target,codes);code_switching.validate(db)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM code_spans WHERE language_id=?',(target,)).fetchone()[0],2)
            self.assertEqual(self.api('entries?language='+target+'&code_mode=mixed')['total'],1)
        finally:staged.close()

    def test_snapshot_backup_keeps_deleted_mark_history_and_audio_links_for_undo(self):
        import project_backup,language_exchange
        self.seed();self.mark();sid,parent,interval,change=self.session();span=self.detail()['spans'][0]['id'];self.link(span,interval)
        d=self.detail();self.api('code-delete',dict(kind='corpus',record_id=self.eid,id=span,token=d['token'],confirmed=True))
        with server.connect(audit=False) as db:package=project_backup.prepare(db,server.DB)
        target=Path(self.temp.name)/'snapshot.sqlite3';project_backup.restore(language_exchange.staged(server.DB,package['token'],'project-backup'),target)
        original=server.DB;server.DB=target
        try:
            server.init();self.assertEqual(self.detail()['spans'],[]);self.undo()
            self.assertTrue(self.detail()['profile']['mixed'])
            self.assertEqual(next(i for i in self.detail()['intervals'] if i['id']==interval)['span_id'],span)
        finally:server.DB=original

    def test_migration_snapshots_existing_database_before_creating_code_tables(self):
        import sqlite3
        with server.connect(audit=False) as db:
            for table in ('code_spans','code_time_links','code_sentence_index'):db.execute('DROP TABLE '+table)
        old=set((server.DB.parent/'backups').glob('*.sqlite3'));server.init()
        created=set((server.DB.parent/'backups').glob('*.sqlite3'))-old;self.assertEqual(len(created),1)
        with closing(sqlite3.connect(created.pop())) as db:self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='code_spans'").fetchone())

    def test_timeline_copy_keeps_correspondence_and_splitting_language_time_requires_relinking(self):
        self.seed();self.mark();sid,parent,interval,change=self.session();span=self.detail()['spans'][0]['id'];self.link(span,interval)
        copied=change('duplicate')['id'];copy_interval=next(i for i in self.api('timeline-detail?id='+copied)['intervals'] if i['parent_id'])['id']
        self.assertEqual(next(i for i in self.detail()['intervals'] if i['id']==copy_interval)['span_id'],span)
        change('split',interval_id=interval,at_ms=1500)
        self.assertIsNone(next(i for i in self.detail()['intervals'] if i['id']==interval)['span_id'])
        self.assertEqual(len(self.detail()['spans']),1);self.undo()
        self.assertEqual(next(i for i in self.detail()['intervals'] if i['id']==interval)['span_id'],span)


if __name__ == '__main__': unittest.main()
