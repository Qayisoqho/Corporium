import base64
import json
import sqlite3
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
import test_server
import test_lexicon
import server
import long_tasks
import task_operations
import language_exchange
import excel_exchange


class WriteTasks(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    undo=test_lexicon.LexiconTests.undo

    def wait(self,jid):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            state=long_tasks.view(server.DB,jid)
            if state['state'] not in long_tasks.ACTIVE:
                long_tasks.JOBS[jid]['future'].result(timeout=5)
                return state
            time.sleep(.005)
        long_tasks.cancel(server.DB,jid)
        self.fail('Task timed out')

    def submit(self,operation,body,language='ordos'):
        code,r=self.call('/api/task-start',dict(kind='operation',request=dict(operation=operation,body=body,language=language)))
        self.assertEqual(code,200,r)
        return r['id']

    def execute(self,operation,body,language='ordos'):
        state=self.wait(self.submit(operation,body,language))
        self.assertEqual(state['state'],'done',state)
        return state['result']

    def snapshot(self):
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
            return {t[0]:sorted([tuple(r) for r in db.execute('SELECT * FROM "'+t[0]+'"')],key=repr) for t in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def seed(self,count=4):
        b=dict(title='source',content='\n'.join(f'#pass([ipa{i}], (([home],[家]),([home.],[家])), [old {i}])' for i in range(count)))
        code,r=self.call('/api/import',b);self.assertEqual(code,200,r);return r['id']

    def dictionary_source(self,kind):
        self.seed(3)
        operation='lexeme-save' if kind=='lexeme' else 'morpheme-save'
        b=dict(headword='home',body=dict(usages=[dict(senses=[dict(short_gloss='家')])])) if kind=='lexeme' else dict(form='home',body=dict(gloss='家'))
        code,row=self.call('/api/'+operation,b);self.assertEqual(code,200,row)
        code,x=self.call('/api/lexeme?id='+row['id']);self.assertEqual(code,200,x)
        u=x['body']['usages'][0]
        with server.connect(audit=False) as db:units=[r[0] for r in db.execute("SELECT id FROM corpus_units WHERE kind='word' AND position=0 AND active=1")]
        for uid in units:
            unit=self.call('/api/unit-dictionary?id='+uid)[1]
            code,result=self.call('/api/lexeme-link',dict(unit_id=uid,unit_revision=unit['revision'],entry_revision=unit['entry_revision'],revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id']))
            self.assertEqual(code,200,result)
        code,example=self.call('/api/example-save',dict(body=dict(ipa='independent',translation='keep',words=[dict(form='home',gloss='家')])));self.assertEqual(code,200,example)
        code,d=self.call('/api/segmentation?kind=independent&id='+example['id']);self.assertEqual(code,200,d)
        code,result=self.call('/api/segmentation-link',dict(kind='independent',id=example['id'],revision=d['revision'],word=0,key='@word',lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id']))
        self.assertEqual(code,200,result)
        return operation,row,example

    def check_dictionary_task(self,kind):
        operation,row,example=self.dictionary_source(kind)
        if kind=='lexeme':row['body']['usages'][0]['senses'][0]['short_gloss']='新义'
        else:row['body']['gloss']='新义'
        def stored():
            with server.connect(audit=False) as db:
                return {t:[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ('entries','dictionary_examples','corpus_units','unit_segments','gloss_bindings')}
        def effective(label):
            code,result=self.call('/api/entries');self.assertEqual(code,200,result)
            self.assertEqual([r['words'][0]['gloss'] for r in result['items']],[label]*3)
            self.assertEqual([r['words'][1]['gloss'] for r in result['items']],['家']*3)
            code,d=self.call('/api/annotations?kind=independent&id='+example['id']);self.assertEqual(code,200,d)
            self.assertEqual(d['body']['words'][0]['gloss'],label)
        before=stored();effective('家')
        self.execute(operation,row);effective('新义');self.assertEqual(stored(),before)
        self.assertEqual(self.undo()[0],200);effective('家');self.assertEqual(stored(),before)
        self.assertEqual(self.undo('redo')[0],200);effective('新义');self.assertEqual(stored(),before)

    def test_lexeme_save_task_syncs_and_undoes(self):self.check_dictionary_task('lexeme')
    def test_morpheme_save_task_syncs_and_undoes(self):self.check_dictionary_task('morpheme')

    def check_dictionary_cancel(self,kind):
        import gloss_inheritance
        operation,row,example=self.dictionary_source(kind)
        if kind=='lexeme':row['body']['usages'][0]['senses'][0]['short_gloss']='新义'
        else:row['body']['gloss']='新义'
        before=self.snapshot();original=gloss_inheritance.sync_meanings;observed=[]
        def stop(db,*args,**kwargs):
            result=original(db,*args,**kwargs)
            observed.extend(tuple(r) for r in db.execute("SELECT gloss FROM gloss_meanings WHERE target_id=?",(row['id'],)))
            job=long_tasks.CURRENT.get();long_tasks.cancel(job['project'],job['id']);long_tasks.checkpoint()
            return result
        with patch('gloss_inheritance.sync_meanings',stop):state=self.wait(self.submit(operation,row))
        self.assertEqual(state['state'],'cancelled',state)
        self.assertEqual(observed,[('新义',)]) # Cancel only after the actual normalized meaning write.
        self.assertEqual(before,self.snapshot())
        code,d=self.call('/api/annotations?kind=independent&id='+example['id']);self.assertEqual(code,200,d);self.assertEqual(d['body']['words'][0]['gloss'],'家')

    def test_dictionary_meaning_task_cancel_restores_every_table(self):self.check_dictionary_cancel('lexeme')
    def test_morpheme_meaning_task_cancel_restores_every_table(self):self.check_dictionary_cancel('morpheme')

    def cancel_after_dispatch(self,operation,body,language='ordos'):
        before=self.snapshot();dispatch=task_operations.dispatch;observed=[]
        folder=Path(self.temp.name)/'backups';files={p.name:p.read_bytes() for p in folder.glob('*') if p.is_file()}
        def abort(db,*args):
            result=dispatch(db,*args)
            observed.append(db.total_changes)
            job=long_tasks.CURRENT.get();long_tasks.cancel(job['project'],job['id'])
            return result
        with patch('task_operations.dispatch',abort):
            state=self.wait(self.submit(operation,body,language))
        self.assertEqual(state['state'],'cancelled',state)
        self.assertTrue(observed)
        self.assertEqual(self.snapshot(),before,operation)
        self.assertEqual({p.name:p.read_bytes() for p in folder.glob('*') if p.is_file()},files,operation)
        return observed[0]

    def test_backup_retention_waits_for_successful_commit(self):
        import backup_policy
        tid=self.seed();folder=Path(self.temp.name)/'backups';backup_policy.save_policy(folder,5)
        folder.mkdir(exist_ok=True)
        for i in range(5):(folder/f'20261013T010000-{i:08x}.json').write_text('{}')
        ids=[r['id'] for r in self.call('/api/entries?text='+tid)[1]['items']]
        body=dict(source_id=tid,ids=ids[:2],title='new')
        self.cancel_after_dispatch('split',body)
        self.assertEqual(len(backup_policy.candidates(folder)),5)
        self.execute('split',body);self.assertEqual(len(backup_policy.candidates(folder)),5)

    def test_import_commit_undo_redo_and_duplicate(self):
        b=dict(title='task import',content='\n'.join(f'#pass([{i}], (([home-n],[家-GEN]),), [])' for i in range(12)))
        generation=self.call('/api/undo-state')[1]['generation']
        r=self.execute('import',b);self.assertEqual(r['count'],12)
        state=self.call('/api/undo-state')[1];self.assertEqual(state['generation'],generation+1)
        with server.connect(audit=False) as db:self.assertGreater(db.execute('SELECT COUNT(*) FROM corpus_units').fetchone()[0],12)
        self.assertTrue(self.execute('import',b)['duplicate'])
        self.assertEqual(self.call('/api/undo-state')[1]['generation'],state['generation'])
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.call('/api/texts')[1],[])
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.call('/api/entries')[1]['total'],12)

    def test_cancel_during_actual_import_restores_every_table_and_redo(self):
        self.seed();self.assertEqual(self.undo()[0],200)
        before=self.snapshot();entered=threading.Event();release=threading.Event();sync=server.lexicon.sync_entry;calls=[]
        def stop(db,*args,**kwargs):
            result=sync(db,*args,**kwargs);calls.append(1)
            if len(calls)==3:
                entered.set();release.wait(5);long_tasks.checkpoint()
            return result
        with patch('lexicon.sync_entry',stop):
            jid=self.submit('import',dict(title='cancel',content='\n'.join(f'#pass([{i}], (([word],[tag]),), [])' for i in range(50))))
            try:
                self.assertTrue(entered.wait(5));self.assertEqual(len(calls),3)
                self.assertEqual(self.call('/api/new-text',dict(title='blocked'))[0],409)
                long_tasks.cancel(server.DB,jid)
            finally:release.set()
            self.assertEqual(self.wait(jid)['state'],'cancelled')
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.undo('redo')[0],200)

    def test_cancel_after_journal_generation_and_cache_invalidation(self):
        self.seed();before=self.snapshot();invalidate=server.analysis_workspace.invalidate;seen=[]
        def stop(db):
            invalidate(db);seen.append(db.execute('SELECT COUNT(*) FROM undo_steps').fetchone()[0])
            job=long_tasks.CURRENT.get();long_tasks.cancel(job['project'],job['id'])
        with patch('analysis_workspace.invalidate',stop):
            state=self.wait(self.submit('import',dict(title='cancel',content='#pass([], (([a],[A]),), [])')))
        self.assertEqual(state['state'],'cancelled',state);self.assertTrue(seen)
        self.assertEqual(self.snapshot(),before)

    def test_commit_gate_rejects_late_cancel_and_forget(self):
        entered=threading.Event();release=threading.Event();gate=long_tasks.committing
        def slow(db):
            gate(db);entered.set();release.wait(5)
        with patch('long_tasks.committing',slow):
            jid=self.submit('import',dict(title='commit',content='#pass([], (([a],[A]),), [])'))
            try:
                self.assertTrue(entered.wait(5));self.assertTrue(long_tasks.active(server.DB))
                self.assertEqual(long_tasks.cancel(server.DB,jid)['state'],'committing')
                self.assertFalse(long_tasks.JOBS[jid]['cancel'].is_set())
                self.assertEqual(self.call('/api/task-forget',dict(id=jid))[0],200)
                self.assertIn(jid,long_tasks.JOBS)
            finally:release.set()
            self.assertEqual(self.wait(jid)['state'],'done')
        self.assertEqual(self.call('/api/entries')[1]['total'],1)

    def test_sql_interruption_rolls_back_prior_writes(self):
        before=self.snapshot();entered=threading.Event();dispatch=task_operations.dispatch
        def query(db,*args):
            result=dispatch(db,*args);entered.set()
            db.execute('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
            return result
        with patch('task_operations.dispatch',query):
            jid=self.submit('import',dict(title='SQL cancel',content='#pass([], (([a],[A]),), [])'))
            self.assertTrue(entered.wait(5));long_tasks.cancel(server.DB,jid)
            self.assertEqual(self.wait(jid)['state'],'cancelled')
        self.assertEqual(self.snapshot(),before)

    def test_statistics_audit_and_result_equivalence(self):
        self.seed();before=self.snapshot()
        q=dict(language='ordos',source='all',lower='true')
        expected=server.grammar.audit
        with server.connect(audit=False) as db:gold=expected(db,q)
        r=self.wait(long_tasks.submit(server.DB,'grammar-audit',q));self.assertEqual(r['state'],'done',r);self.assertEqual(r['result'],gold)
        self.assertEqual(self.snapshot(),before)
        r=self.execute('analysis-run',dict(query=dict(kind='counts',scope={'mode':'language'})))
        self.assertEqual(r['summary']['sentences'],4);self.assertEqual(r['summary']['words'],8)
        result=self.wait(long_tasks.submit(server.DB,'analysis-result',dict(language='ordos',id=r['id'])))
        self.assertEqual(result['state'],'done',result);self.assertEqual(result['result'],self.call('/api/analysis-result?id='+r['id']+'&language=ordos')[1])
        self.cancel_after_dispatch('analysis-run',dict(query=dict(kind='counts',scope={'mode':'language'})))
        self.cancel_after_dispatch('analysis-run',dict(query=dict(conditions=[dict(field='form',value='home',mode='exact')],scope={})))

    def test_excel_multisheet_cancel_retry_and_stale_signature(self):
        raw=excel_exchange.workbook([('a',[['m','g','ipa'],['a','A','ɑ'],[],['b','B','b']]),('b',[['m','g','ipa'],['c','C','c']])])
        staged_before=set(language_exchange.STAGED)
        self.cancel_after_dispatch('excel-inspect',dict(data=base64.b64encode(raw).decode()))
        self.assertEqual(set(language_exchange.STAGED),staged_before)
        u=self.execute('excel-inspect',dict(data=base64.b64encode(raw).decode()))
        configs=[dict(index=i,title='text'+str(i),start=2,mappings=[dict(column=j,target=t) for j,t in enumerate(['form','gloss','ipa'],1)]) for i in range(2)]
        b=dict(token=u['token'],sheets=configs);p=self.execute('excel-preview',b);b['signature']=p['signature']
        self.assertGreater(self.cancel_after_dispatch('excel-import',b),0)
        result=self.execute('excel-import',b);self.assertEqual(result['count'],3)
        before=self.snapshot();state=self.wait(self.submit('excel-import',{**b,'signature':'stale'}))
        self.assertEqual(state['state'],'error');self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.call('/api/texts')[1],[])

    def test_batch_apply_cancel_retry_validation_and_single_undo(self):
        tid=self.seed();x=self.call('/api/lexeme-save',dict(headword='home',body=dict(notes='old',usages=[dict(pos='名词',senses=[dict(short_gloss='家')])])))[1]
        auto=self.call('/api/lexeme-auto-preview?language=ordos')[1]
        cases=[('lexeme-auto-link',dict(token=auto['token']))]
        for operation,args in [('text-replace',dict(text_id=tid,field='translation',find='old',replacement='new')),('dictionary-replace',dict(scope='language',field='notes',find='old',replacement='new')),('punctuation',dict(text_id=tid))]:
            p=self.execute(operation+'-preview',args)
            body={**args,'token':p['token']}
            if operation!='punctuation':body['keys']=[c['key'] for c in p['changes']]
            cases.append((operation+'-apply',body))
        cls=self.call('/api/dict-org-class-save',dict(name='自然'))[1]
        cases.append(('dict-org-assign',dict(classes=[cls['id']],items=[dict(id=x['id'],revision=x['revision'])])))
        for operation,body in cases:
            with self.subTest(operation=operation):
                if operation.endswith('-apply'):
                    prefix=operation.removesuffix('-apply');p=self.execute(prefix+'-preview',body);body={**body,'token':p['token']}
                    if prefix!='punctuation':body['keys']=[c['key'] for c in p['changes']]
                if operation=='dict-org-assign':body['items']=[dict(id=x['id'],revision=self.call('/api/lexeme?id='+x['id'])[1]['revision'])]
                self.assertGreater(self.cancel_after_dispatch(operation,body),0)
                generation=self.call('/api/undo-state')[1]['generation'];self.execute(operation,body)
                self.assertEqual(self.call('/api/undo-state')[1]['generation'],generation+1)
                self.assertEqual(self.undo()[0],200)

    def test_read_checks_and_statistics_cancel_in_real_loops(self):
        self.seed(90);before=self.snapshot();steps=long_tasks.steps
        for kind,request in [('grammar-audit',dict(source='all')),('statistics',dict(scope={'mode':'language'}))]:
            with self.subTest(kind=kind):
                calls=[]
                def abort(iterable):
                    for item in steps(iterable):
                        calls.append(1)
                        if len(calls)==12:
                            job=long_tasks.CURRENT.get();long_tasks.cancel(job['project'],job['id']);long_tasks.checkpoint()
                        yield item
                with patch('long_tasks.steps',abort):
                    result=self.wait(long_tasks.submit(server.DB,kind,dict(language='ordos',**request)))
                self.assertEqual(result['state'],'cancelled',result);self.assertEqual(self.snapshot(),before)

    def test_morpheme_assign_and_sentence_copy_split_cancel_retry(self):
        from test_morpheme_registry import MorphemeRegistryTests
        helper=MorphemeRegistryTests();helper.call=self.call
        # Reuse the component fixture through its normal API, preserving stable IDs.
        from test_component_links import ComponentLinkTests
        from test_lexicon import LexiconTests
        helper.seed=LexiconTests.seed.__get__(helper);helper.entries=LexiconTests.entries.__get__(helper)
        e,x=ComponentLinkTests.fixture(helper)
        body=dict(lexeme_id=x['id'],lexeme_revision=x['revision'],components=[dict(analysis_id='a',component_id='c',revision=0)],create=dict(form='home',body={'gloss':'家'}))
        self.cancel_after_dispatch('morpheme-assign',body);self.execute('morpheme-assign',body)
        self.assertEqual(self.undo()[0],200)
        tid=self.seed(3);ids=[r['id'] for r in self.call('/api/entries?text='+tid)[1]['items']]
        body=dict(source_id=tid,ids=ids[:2],title='split')
        self.cancel_after_dispatch('split',body);r=self.execute('split',body)
        self.assertEqual(self.call('/api/entries?text='+r['id'])[1]['total'],2)

    def test_json_import_remaps_and_cancels_without_residue(self):
        self.seed()
        with server.connect(audit=False) as db:bundle=language_exchange.export_bundle(db,'ordos')
        self.assertGreater(self.cancel_after_dispatch('import-language',dict(bundle=bundle)),0)
        result=self.execute('import-language',dict(bundle=bundle));self.assertEqual(result['count'],4)
        self.assertEqual(self.call('/api/entries')[1]['total'],8)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.call('/api/entries')[1]['total'],4)

    def test_package_media_cancel_error_cleanup_and_retry(self):
        import timeline,media_engine
        self.seed();source=Path(self.temp.name)/'tiny.wav'
        with wave.open(str(source),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000);f.writeframes(b'\0\0'*80)
        with server.connect(audit=False) as db:
            timeline.mutate(db,'ordos','create',dict(name='linked'),dict(name=source.name,path=str(source),storage='link',metadata=dict(fingerprint=media_engine.fingerprint(source),duration_ms=10)))
            export=language_exchange.prepare(db,server.DB,'ordos',include_media=True)
        token=language_exchange.stage(server.DB,language_exchange.staged(server.DB,export['token'],'export'),'import')
        body=dict(token=token,name='Imported');media=Path(self.temp.name)/'media'
        before=self.snapshot();checkpoint=long_tasks.checkpoint;copies=[]
        def abort_copy(progress=None,message=None):
            if message=='正在准备导入媒体…':
                copies.append(1)
                if len(copies)==2:
                    job=long_tasks.CURRENT.get();long_tasks.cancel(job['project'],job['id'])
            return checkpoint(progress,message)
        with patch('long_tasks.checkpoint',abort_copy):state=self.wait(self.submit('language-package-import',body))
        self.assertEqual(state['state'],'cancelled',state);self.assertEqual(self.snapshot(),before);self.assertEqual(list(media.iterdir()),[])
        self.cancel_after_dispatch('language-package-import',body)
        self.assertEqual(list(media.iterdir()),[])
        before=self.snapshot()
        with patch('lexicon.validate_changes',side_effect=ValueError('injected validation failure')):
            state=self.wait(self.submit('language-package-import',body))
        self.assertEqual(state['state'],'error',state);self.assertEqual(self.snapshot(),before);self.assertEqual(list(media.iterdir()),[])
        result=self.execute('language-package-import',body)
        self.assertNotEqual(result['language_id'],'ordos');self.assertEqual(len(list(media.iterdir())),1)
        self.assertEqual(self.call('/api/entries?language='+result['language_id'])[1]['total'],4)

    def test_operation_allowlist_scope_and_resource_rollback(self):
        self.seed();before=self.snapshot()
        for operation,body,lid in [('delete-text',{},'ordos'),('import',dict(title='bad',content='#pass([], (), [])'),'missing')]:
            state=self.wait(self.submit(operation,body,lid));self.assertEqual(state['state'],'error',state);self.assertEqual(self.snapshot(),before)
        dispatch=task_operations.dispatch
        def slow(*args):
            result=dispatch(*args)
            while True:time.sleep(.01);long_tasks.checkpoint()
        with patch('task_operations.dispatch',slow),patch('long_tasks.working_set',return_value=long_tasks.MEMORY_LIMIT+1):
            state=self.wait(self.submit('import',dict(title='memory',content='#pass([], (([a],[A]),), [])')))
        self.assertEqual(state['state'],'error');self.assertIn('保护上限',state['message']);self.assertEqual(self.snapshot(),before)


if __name__=='__main__':unittest.main()
