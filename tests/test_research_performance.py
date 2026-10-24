"""Semantic guards for bounded research reads and independent timeline writes."""
import base64,copy,json,sqlite3,unittest,zlib
from contextlib import closing
from unittest.mock import patch
import analysis_workspace as analysis
import corpus,corpus_statistics,grammar,grammar_audit_cache,lexicon,long_tasks,morpheme_colors,server
import test_analysis_workspace
import test_timeline_hierarchy
import test_grammar


class PackTests(unittest.TestCase):
    def test_streamed_pack_retains_exact_json_and_legacy_decode(self):
        value={'hits':[dict(value='e\u0301𐀀\n"'+str(i),dimensions=dict(value=['汉字'])) for i in range(4000)],
               'records':{str(i):dict(body=dict(words=[dict(form='n',gloss='GEN')],notes='大'*100)) for i in range(20)},
               3:'numeric key',None:'null key','floats':[1.2345678901234567,None,True]}
        expected=analysis.encode(value).encode('utf-8')
        packed=analysis.pack(value)
        self.assertEqual(zlib.decompress(base64.b64decode(packed)),expected)
        self.assertEqual(analysis.unpack(base64.b64encode(zlib.compress(expected)).decode()),json.loads(expected))


class ResearchReadTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','word','link','undo','execute','page'):
        locals()[name]=getattr(test_analysis_workspace.AnalysisTests,name)

    def test_context_sort_renders_only_the_page_and_keeps_snapshot_words(self):
        self.seed('\n'.join('#pass([], (([left'+str(i%7)+'],[L]),([target],[T]),([right'+str(i%5)+'],[R])), [])' for i in range(75)))
        run=self.execute('form','target');seen=[];original=analysis.materialize
        def bounded(db,hits):seen.append(len(hits));return original(db,hits)
        with patch.object(analysis,'materialize',bounded):live=self.page(run,sort='left')
        self.assertEqual(seen,[30]);self.assertEqual(live['total'],75)
        self.assertEqual([i['record']['body']['words'][0]['form'] for i in live['items']],sorted(['left'+str(i%7) for i in range(75)])[:30])
        code,snapshot=self.call('/api/analysis-save',dict(kind='snapshot',name='frozen',run_id=run['id']));self.assertEqual(code,200,snapshot)
        entry=self.entries()[0];entry['words'][0]['form']='ZZZ';entry.setdefault('notes','')
        code,result=self.call('/api/save',entry);self.assertEqual(code,200,result)
        self.assertTrue(self.page(run)['stale'])
        with patch.object(analysis,'context_forms',side_effect=AssertionError('snapshot used live words')):
            frozen=self.page(snapshot,snapshot='true',sort='left')
        self.assertEqual([i['entry_id'] for i in frozen['items']],[i['entry_id'] for i in live['items']])
        self.assertFalse(any(i['record']['body']['words'][0]['form']=='ZZZ' for i in frozen['items']))

    def test_batch_colors_match_single_card_and_preserve_mutable_independence(self):
        self.seed('\n'.join('#pass([], (([home-n],[家-GEN]),), [])' for _ in range(4)))
        entries=self.entries();target=self.word();self.link(entries[0]['words'][0]['morphemes'][1]['unit_id'],target)
        with server.connect(audit=False) as db:
            prepared=morpheme_colors.prepare(db,[e['id'] for e in entries])
            for e in entries:
                a=corpus.analyze(copy.deepcopy(e));b=copy.deepcopy(a)
                morpheme_colors.attach(db,a,'corpus',e['id'],'ordos')
                morpheme_colors.attach(db,b,'corpus',e['id'],'ordos',prepared=prepared)
                self.assertEqual(a,b)
            records=analysis.materialize(db,[dict(entry_id=e['id']) for e in entries])
            hits=[dict(entry_id=e['id']) for e in entries]
            self.assertEqual(analysis.unpack(analysis.pack(dict(records=analysis.RecordStream(db,hits)))),json.loads(analysis.encode(dict(records=records))))
            first,second=list(records.values())[:2];first['body']['words'][0]['morph_colors'].clear()
            self.assertTrue(second['body']['words'][0]['morph_colors'])

    def test_snapshot_task_cancel_after_rendering_started_rolls_back_and_can_retry(self):
        self.seed('\n'.join('#pass([], (([home],[家]),), [])' for _ in range(4)))
        run=self.execute('form','home');original=analysis.materialized_items;seen=[]
        def snapshot():
            with server.connect(audit=False) as db:
                return {t[0]:[tuple(r) for r in db.execute('SELECT * FROM "'+t[0]+'"')] for t in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        def partial(db,hits,**kwargs):
            for item in original(db,hits,**kwargs):
                seen.append(True);yield item
                job=long_tasks.CURRENT.get();long_tasks.cancel(job['project'],job['id']);long_tasks.checkpoint()
        request=dict(language='ordos',operation='analysis-save',body=dict(kind='snapshot',name='完整快照',run_id=run['id']))
        before=snapshot()
        with patch.object(analysis,'materialized_items',partial):
            jid=long_tasks.submit(server.DB,'operation',request);long_tasks.JOBS[jid]['future'].result(timeout=10)
            self.assertEqual(long_tasks.view(server.DB,jid)['state'],'cancelled')
        self.assertTrue(seen);self.assertEqual(before,snapshot())
        jid=long_tasks.submit(server.DB,'operation',request);long_tasks.JOBS[jid]['future'].result(timeout=10)
        state=long_tasks.view(server.DB,jid);self.assertEqual(state['state'],'done',state)
        self.assertEqual(self.page(state['result'],snapshot='true')['total'],4)


class TimelineDependencyTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','detail','mutation','add','undo','tree'):
        locals()[name]=getattr(test_timeline_hierarchy.TimelineHierarchyTests,name)

    def test_timeline_save_and_undo_use_timeline_checks_without_lexical_scan(self):
        with server.connect(audit=False) as db:units=[tuple(r) for r in db.execute('SELECT * FROM corpus_units ORDER BY id')]
        with patch.object(lexicon,'validate_links',side_effect=AssertionError('unrelated dictionary graph was rescanned')):
            self.add();self.assertEqual(self.mutation('rename',name='renamed')[0],200)
            self.assertEqual(self.undo()[0],200)
            self.assertEqual(self.mutation('interval',track_id=self.detail()['tracks'][0]['id'],entry_id=self.eids[0],start_ms=1,end_ms=0)[0],400)
        with server.connect(audit=False) as db:self.assertEqual(units,[tuple(r) for r in db.execute('SELECT * FROM corpus_units ORDER BY id')])

    def test_parent_boundary_checks_are_still_atomic(self):
        # Existing hierarchy checks remain active even though lexical checks are scoped.
        parent,_,track,*_=self.tree()
        code,result=self.mutation('interval',track_id=track['id'],start_ms=0,end_ms=1900,parent_id=parent['id'])
        self.assertEqual(code,400,result)

    def test_mixed_timeline_and_invalid_dictionary_changes_still_reject(self):
        with server.connect(audit=False) as db:
            db.execute("INSERT INTO lexical_links(id,unit_id,lexeme_id,language_id) VALUES('broken-reference','missing-unit','missing-target','ordos')")
            row=dict(db.execute("SELECT * FROM lexical_links WHERE id='broken-reference'").fetchone())
            with self.assertRaises(ValueError):lexicon.validate_changes(db,{('timeline_sessions','x'):(None,dict(id='x')),('lexical_links',row['id']):(None,row)})
            db.rollback()


class AuditReuseTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','word','link','undo','example','tag'):
        locals()[name]=getattr(test_grammar.GrammarTests,name)

    def test_filter_and_page_reuse_but_source_edits_undo_and_raw_api_refresh(self):
        self.seed('\n'.join('#pass([], (([x],[UNKNOWN])), [])' for _ in range(25)))
        first=self.call('/api/grammar-audit?lower=true&language=ordos&reuse=1')[1]
        with patch.object(grammar,'analyze',side_effect=AssertionError('unchanged sentences rescanned')):
            second=self.call('/api/grammar-audit?lower=true&language=ordos&reuse=1&page=2&q=UNKNOWN')[1]
        self.assertEqual(first['total'],25);self.assertEqual(len(second['items']),5)
        with patch.object(grammar,'analyze',wraps=grammar.analyze) as analyze:
            self.assertEqual(self.call('/api/grammar-audit?lower=true&language=ordos')[0],200)
            self.assertEqual(analyze.call_count,25)
        tag=self.tag('UNKNOWN')
        self.assertEqual(self.call('/api/grammar-audit?lower=true&language=ordos&reuse=1')[1]['total'],0)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/grammar-audit?lower=true&language=ordos&reuse=1')[1]['total'],25)

    def test_definition_edits_keep_feature_identity_and_skip_unrelated_graph_checks(self):
        self.seed();tag=self.tag(aliases=['GENITIVE'])
        code,target=self.call('/api/lexeme-save',dict(headword='bound',body=dict(features=[tag['id']],usages=[dict(senses=[dict(short_gloss='家')])])))
        self.assertEqual(code,200,target)
        with patch.object(lexicon,'validate_links',side_effect=AssertionError('unchanged feature IDs rescanned')):
            self.assertEqual(self.call('/api/grammar-save',{**tag,'description':'新解释','aliases':['GENCASE']})[0],200)
            self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/grammar-tags?language=ordos')[1][0]['aliases'],['GENITIVE'])
        with patch.object(lexicon,'validate_links',wraps=lexicon.validate_links) as full:
            current=self.call('/api/grammar-tags?language=ordos')[1][0]
            self.assertEqual(self.call('/api/grammar-delete',{**current,'confirmed':True})[0],400)
            self.assertTrue(full.called)

    def test_external_commit_and_pinned_wal_reader_cannot_publish_stale_result(self):
        self.seed('#pass([], (([x],[BEFORE])), [])')
        with server.connect(audit=False) as db:db.execute('PRAGMA journal_mode=WAL')
        with server.connect(audit=False,observe_snapshot=True) as reader:
            reader.execute('BEGIN');before=grammar.audit(reader,dict(language='ordos',lower='true',reuse='1'))
            with closing(sqlite3.connect(server.DB)) as writer:
                row=writer.execute('SELECT id,body FROM entries').fetchone();body=json.loads(row[1]);body['words'][0]['gloss']='AFTER'
                writer.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(body),row[0]))
                writer.commit()
            # No analysis_state increment: detect the external commit independently.
            self.assertIsNone(grammar_audit_cache.load(reader,dict(language='ordos',lower='true',reuse='1')))
            grammar.audit(reader,dict(language='ordos',lower='true',reuse='1'))
            self.assertEqual(before['unknown'][0]['symbol'],'BEFORE')
        after=self.call('/api/grammar-audit?lower=true&language=ordos&reuse=1')[1]
        self.assertEqual(after['unknown'][0]['symbol'],'AFTER')

    def test_commit_between_observer_check_and_first_source_read_cannot_reuse(self):
        self.seed('#pass([], (([x],[BEFORE])), [])')
        with server.connect(audit=False) as db:db.execute('PRAGMA journal_mode=WAL')
        self.call('/api/grammar-audit?lower=true&language=ordos&reuse=1')
        with server.connect(audit=False,observe_snapshot=True) as reader:
            reader.execute('BEGIN');observer=grammar_audit_cache.CURRENT.get();original=observer.stable;calls=[]
            def race():
                stable=original();calls.append(True)
                if len(calls)==1:
                    with closing(sqlite3.connect(server.DB)) as writer:
                        writer.execute("UPDATE entries SET body=json_set(body,'$.words[0].gloss','AFTER')");writer.commit()
                return stable
            with patch.object(observer,'stable',race):self.assertIsNone(grammar_audit_cache.load(reader,dict(language='ordos',lower='true',reuse='1')))
            self.assertEqual(grammar.audit(reader,dict(language='ordos',lower='true',reuse='1'))['unknown'][0]['symbol'],'AFTER')

    def test_preview_writes_never_reuse_or_publish_and_usage_bodies_are_independent(self):
        self.seed('#pass([], (([x],[GEN])), [])');tag=self.tag()
        q=dict(language='ordos',lower='true',reuse='1',tag=tag['id'],issue='usage')
        with server.connect(audit=False,observe_snapshot=True) as db:
            db.execute('BEGIN')
            first=grammar.audit(db,q);first['items'][0]['body']['words'][0]['form']='changed in caller'
            second=grammar.audit(db,q);self.assertEqual(second['items'][0]['body']['words'][0]['form'],'x')
            db.execute('UPDATE entries SET revision=revision+1')
            self.assertIsNone(grammar_audit_cache.load(db,q))
            db.rollback();self.assertIsNone(grammar_audit_cache.key(db,q))
        self.assertIsNone(grammar_audit_cache.CURRENT.get())

    def test_background_reader_reuses_and_closes_observer_on_cancel(self):
        self.seed('#pass([], (([x],[UNKNOWN])), [])');q=dict(language='ordos',lower='true',reuse='1')
        def run():
            jid=long_tasks.submit(server.DB,'grammar-audit',q);long_tasks.JOBS[jid]['future'].result(timeout=10)
            return long_tasks.view(server.DB,jid)
        self.assertEqual(run()['state'],'done')
        with patch.object(grammar,'analyze',side_effect=AssertionError('worker rescanned unchanged source')):
            self.assertEqual(run()['state'],'done')
        original=grammar_audit_cache.Snapshot.close;closed=[]
        def close(observer):closed.append(observer);return original(observer)
        with patch.object(grammar_audit_cache.Snapshot,'close',close),patch.object(grammar,'audit',side_effect=long_tasks.Cancelled):
            self.assertEqual(run()['state'],'cancelled')
        self.assertTrue(closed);self.assertTrue(all(o.observer is None for o in closed))


class CountSemanticsTests(unittest.TestCase):
    def test_operation_counter_tracks_source_punctuation_and_bounds_repeated_values(self):
        counter=corpus_statistics.WordCounter()
        for form in ('','  ','#','##','-','，','a','a-b','𐀀','[a]','a #sub[x]'):
            for punct in (False,True):
                for original in (None,form,'other'):
                    w=dict(form=form,punctuation=punct,punctuation_form=original)
                    self.assertEqual(counter(w),corpus_statistics.is_word(w))
        for i in range(5000):counter(dict(form='unique'+str(i)))
        self.assertLessEqual(counter.bytes,4*1024**2)
        self.assertEqual(counter(dict(form='，')),False)
