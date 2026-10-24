"""Longer relation lifecycle tests: copy, delete, exchange, undo and redo."""
import copy
import importlib
import json
import sqlite3
from pathlib import Path
import unittest
import server
import language_exchange
import test_server
import test_gloss_inheritance
import test_annotations
from restore_backup import restore


class RelationSequenceTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    for name in ('word','example','link','detail','mode','change','undo'):
        locals()[name]=getattr(test_gloss_inheritance.GlossInheritanceTests,name)

    def api(self,path,body=None):
        if body is None and 'language=' not in path:path+=('&' if '?' in path else '?')+'language=ordos'
        status,result=self.call('/api/'+path,body)
        self.assertEqual(status,200,(path,result))
        return result

    def seed(self):
        tid=self.api('import',dict(title='Lifecycle',content='#pass([root n free], (([root-n],[root-GEN]),([free],[free])), [source])'))['id']
        e=self.api('entries?text='+tid)['items'][0]
        ex=self.example([('root-n','root-GEN'),('free','free')])
        x=self.word('n',['GEN'])
        for kind,row in [('corpus',e),('independent',ex)]:self.link(row,x,'1:host',kind=kind)
        layer=test_annotations.AnnotationTests.layer(self)
        for kind,row in [('corpus',e),('independent',ex)]:test_annotations.AnnotationTests.annotate(self,kind,row,layer)
        cid=self.api('timeline-code-save',dict(name='Test code',metadata={}))['id']
        for kind,row in [('corpus',e),('independent',ex)]:
            d=self.api('code-detail?kind='+kind+'&id='+row['id'])
            self.api('code-save',dict(kind=kind,record_id=row['id'],token=d['token'],word_ids=[d['words'][0]['id']],code_id=cid,notes='code note'))
        return e,ex,x,layer

    def health(self):
        validators=[('lexicon','validate_links'),('lexicon','validate_unit_references'),*[(m,'validate') for m in ('dictionary_data','morpheme_registry','morphology','annotations','grammar','grammaticality','grammar_survey','timeline_hierarchy','timeline_text_order','code_switching','collaborators','homonyms','fieldwork_notes','object_media','dictionary_organization')]]
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(list(db.execute('PRAGMA foreign_key_check')),[])
            for module,method in validators:getattr(importlib.import_module(module),method)(db)

    def clone(self,e):
        row=self.detail(e)
        return self.api('duplicate-entry',dict(id=e['id'],text_id=e['text_id'],revision=row['revision'],order=[r['id'] for r in self.api('positions?id='+e['text_id'])],where='end'))

    def delete(self,kind,row,lid='ordos'):
        d=self.api('segmentation?kind='+kind+'&id='+row['id']+'&language='+lid)
        p=dict(id=row['id'],revision=d['revision'],confirmed=True,_language=lid)
        if kind=='corpus':p['text_id']=row['text_id']
        return self.api('delete-entry' if kind=='corpus' else 'example-delete',p)

    def transfer(self,kind,row,target_kind,target,mode='copy',indexes=(0,),position=0):
        a=self.api('word-transfer-snapshot?kind='+kind+'&id='+row['id'])
        b=self.api('word-transfer-snapshot?kind='+target_kind+'&id='+target['id'])
        return self.api('word-transfer',dict(source=dict(kind=kind,id=row['id'],token=a['transfer_token']),target=dict(kind=target_kind,id=target['id'],token=b['transfer_token']),slots=[a['words'][i]['id'] for i in indexes],mode=mode,confirmed=True,position=position))

    def signature(self,kind,row,lid='ordos'):
        d=self.api('annotations?kind='+kind+'&id='+row['id']+'&language='+lid)
        code=self.api('code-detail?kind='+kind+'&id='+row['id']+'&language='+lid)
        return dict(words=[(w['form'],w['gloss']) for w in d['body']['words']],cells=[(c['unit_id'],c['layer_id'],c['value']) for c in d['cells']],orphans=[(c['unit_id'],c['value']) for c in d['orphaned']],codes=[(s['word_ids'],s['text'],s['review'],s['notes']) for s in code['spans']])

    def imported(self,bundle,name='Imported',package=False):
        if package:
            p=Path(self.temp.name)/(name+'.json');p.write_text(json.dumps(bundle),encoding='utf-8')
            token=language_exchange.stage(server.DB,p,'import')
            lid=self.api('language-package-import',dict(token=token,name=name))['language_id']
        else:
            lid=self.api('save-language',dict(name=name,metadata={}))['id']
            self.api('import-language',dict(bundle=bundle,_language=lid))
        return lid,self.api('entries?language='+lid+'&include_independent=true')['items']

    def test_copy_delete_undo_redo_retains_distinct_links_layers_and_code_spans(self):
        e,ex,x,layer=self.seed();self.mode('corpus',e,'override','CUSTOM')
        original=self.signature('corpus',e);clone=self.clone(e);clone['text_id']=e['text_id'];cloned=self.signature('corpus',clone)
        self.assertEqual(original['words'],cloned['words']);self.assertNotEqual(original['cells'][0][0],cloned['cells'][0][0])
        self.delete('corpus',e);self.health();self.assertEqual(self.signature('corpus',clone),cloned)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.signature('corpus',e),original)
        self.assertEqual(self.undo()[0],200);self.health()
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.signature('corpus',clone),cloned)
        self.assertEqual(self.undo('redo')[0],200);self.health();self.assertEqual(self.signature('corpus',clone),cloned)
        self.change(x,'POSS');self.assertEqual(self.detail(clone)['body']['words'][0]['gloss'],'root-CUSTOM')
        self.assertEqual(self.detail(ex,'independent')['body']['words'][0]['gloss'],'root-POSS')

    def test_cross_source_copy_then_move_delete_and_history_roundtrip(self):
        e,ex,x,layer=self.seed();self.mode('corpus',e,'override','CUSTOM')
        empty=self.example([]);self.transfer('corpus',e,'independent',empty)
        first=self.signature('independent',empty);self.assertEqual(first['words'],[('root-n','root-CUSTOM')])
        self.transfer('independent',empty,'independent',ex,mode='move',position=2)
        moved=self.signature('independent',ex);self.assertEqual(moved['words'][-1],('root-n','root-CUSTOM'));self.assertEqual(self.signature('independent',empty)['words'],[])
        self.health();self.delete('independent',empty);self.health()
        for action in ('undo','undo','redo','redo'):
            self.assertEqual(self.undo(action)[0],200);self.health()
        self.assertEqual(self.signature('independent',ex),moved)

    def test_delete_both_sources_undo_backup_restore_redo(self):
        e,ex,x,layer=self.seed();before={k:self.signature(k,r) for k,r in [('corpus',e),('independent',ex)]}
        self.delete('corpus',e);self.delete('independent',ex);self.health()
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo()[0],200)
        path=Path(self.temp.name)/'history.json';path.write_text(json.dumps(self.api('backup')),encoding='utf-8')
        target=Path(self.temp.name)/'restored.sqlite3';restore(path,target);server.DB=target
        for k,r in [('corpus',e),('independent',ex)]:self.assertEqual(self.signature(k,r),before[k])
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.undo('redo')[0],200);self.health()
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo()[0],200);self.health()
        for k,r in [('corpus',e),('independent',ex)]:self.assertEqual(self.signature(k,r),before[k])

    def test_twice_imported_language_ids_are_disjoint_and_undo_does_not_touch_peers(self):
        e,ex,x,layer=self.seed();self.mode('independent',ex,'override','LOCAL')
        bundle=self.api('export-language?language=ordos');a,arows=self.imported(bundle,'A');b,brows=self.imported(bundle,'B',package=True)
        self.assertTrue({r['id'] for r in arows}.isdisjoint(r['id'] for r in brows))
        signatures={r['id']:self.signature(r['kind'],r,b) for r in brows}
        self.assertEqual(self.undo(language=a)[0],200);self.health()
        for r in brows:self.assertEqual(self.signature(r['kind'],r,b),signatures[r['id']])
        self.assertEqual(self.undo('redo',language=a)[0],200);self.health()
        self.change(x,'POSS')
        for lid,rows in [(a,arows),(b,brows)]:
            for r in rows:self.assertEqual(self.signature(r['kind'],r,lid)['words'][0][1],'root-GEN' if r['kind']=='corpus' else 'root-LOCAL')
        self.assertEqual(self.detail(e)['body']['words'][0]['gloss'],'root-POSS')

    def test_retired_word_annotations_and_codes_survive_exchange_copy_delete_history(self):
        e,ex,x,layer=self.seed()
        for kind,row in [('corpus',e),('independent',ex)]:
            d=self.api('annotations?kind='+kind+'&id='+row['id'])
            d['body']['words'].pop(0)
            self.api('inline-save',dict(kind=kind,id=row['id'],revision=d['revision'],body=d['body'],slot_ids=[w['id'] for w in d['words'][1:]],layers=d['layers'],before=d['cells'],cells=[c for c in d['cells'] if c['unit_id']!=d['words'][0]['id']],delete_confirmed=True))
            self.assertEqual(len(self.signature(kind,row)['orphans']),1)
        lid,rows=self.imported(self.api('export-language?language=ordos'))
        for row in rows:
            s=self.signature(row['kind'],row,lid);self.assertEqual(s['words'],[('free','free')]);self.assertEqual(len(s['orphans']),1);self.assertTrue(s['codes'][0][2])
        self.health();self.assertEqual(self.undo(language=lid)[0],200);self.assertEqual(self.undo('redo',language=lid)[0],200);self.health()

    def test_survey_copy_shared_sentence_delete_restore_and_exchange(self):
        e,ex,x,layer=self.seed()
        def survey(action,**body):return self.api('survey-'+action,dict(version=self.api('survey?language=ordos')['version'],**body))
        root=survey('save',title='Question',kind='question',body=dict(notes=[dict(text='research')]))['id']
        for kind,row in [('corpus',e),('independent',ex)]:survey('evidence',node_id=root,kind=kind,record_id=row['id'],body=dict(notes=[dict(text='local note')],judgment='uncertain'))
        clone=survey('copy',id=root,include_evidence=True)['id']
        self.delete('corpus',e);self.assertEqual(self.undo()[0],200)
        survey('delete',id=root,confirmed=True);self.health();self.assertEqual(self.undo()[0],200);self.health()
        lid,rows=self.imported(self.api('export-language?language=ordos'))
        with server.connect(audit=False) as db:
            refs=list(db.execute('SELECT record_id,kind,body FROM survey_evidence WHERE language_id=?',(lid,)))
            self.assertEqual(len(refs),4);self.assertEqual(len({r['record_id'] for r in refs}),2)
            self.assertEqual({r['record_id'] for r in refs},{r['id'] for r in rows})
            self.assertTrue(all(json.loads(r['body'])['notes']==[dict(text='local note')] for r in refs))
        self.assertEqual(self.undo(language=lid)[0],200);self.assertEqual(self.undo('redo',language=lid)[0],200);self.health()

    def test_merge_morphemes_keeps_local_overrides_through_undo_redo_and_exchange(self):
        e,ex,x,layer=self.seed()
        plan=self.api('lexeme-to-morpheme-preview',dict(id=x['id'],revision=x['revision']))
        source=self.api('lexeme-to-morpheme',dict(id=x['id'],revision=x['revision'],token=plan['token'],target_id='@new'))
        for kind,row in [('corpus',e),('independent',ex)]:self.mode(kind,row,'override','LOCAL')
        target=self.api('morpheme-save',dict(form='n',body=dict(gloss='DAT')))
        source=self.api('morpheme?id='+source['id'])
        self.api('morpheme-merge',dict(id=source['id'],revision=source['revision'],target_id=target['id'],target_revision=target['revision'],confirmed=True))
        for kind,row in [('corpus',e),('independent',ex)]:
            self.assertEqual(self.detail(row,kind)['body']['words'][0]['gloss'],'root-LOCAL')
            self.assertEqual(self.detail(row,kind)['body']['words'][0]['gloss_sources'][0]['mode'],'override')
        for action in ('undo','redo','undo','redo'):
            self.assertEqual(self.undo(action)[0],200);self.health()
            for kind,row in [('corpus',e),('independent',ex)]:self.assertEqual(self.detail(row,kind)['body']['words'][0]['gloss'],'root-LOCAL')
        lid,rows=self.imported(self.api('export-language?language=ordos'))
        for row in rows:self.assertEqual(self.signature(row['kind'],row,lid)['words'][0][1],'root-LOCAL')

    def test_duplicate_timeline_delete_original_exchange_then_undo(self):
        e,ex,x,layer=self.seed();sid=self.api('timeline-create',dict(name='Source'))['id']
        def change(sid,action,**kw):return self.api('timeline-'+action,dict(id=sid,revision=self.api('timeline-detail?id='+sid)['session']['revision'],**kw))
        track=self.api('timeline-detail?id='+sid)['tracks'][0]['id']
        change(sid,'interval',track_id=track,entry_id=e['id'],start_ms=0,end_ms=2000)
        parent=self.api('timeline-detail?id='+sid)['intervals'][0]['id']
        change(sid,'track',name='Code',kind='language',parent_id=track)
        child=next(t for t in self.api('timeline-detail?id='+sid)['tracks'] if t['kind']=='language')['id']
        code=self.api('code-detail?kind=corpus&id='+e['id']);span=code['spans'][0]
        change(sid,'interval',track_id=child,parent_id=parent,code_id=span['code_id'],start_ms=100,end_ms=900)
        code=self.api('code-detail?kind=corpus&id='+e['id']);interval=code['intervals'][0]
        self.api('code-link',dict(kind='corpus',record_id=e['id'],id=span['id'],token=code['token'],interval_id=interval['id'],interval_revision=interval['revision']))
        duplicate=change(sid,'duplicate')['id'];change(sid,'delete',confirmed=True);self.health()
        current=self.api('code-detail?kind=corpus&id='+e['id']);self.assertEqual(len(current['intervals']),1);self.assertEqual(current['intervals'][0]['span_id'],span['id'])
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo('redo')[0],200);self.health()
        lid,rows=self.imported(self.api('export-language?language=ordos'))
        row=next(r for r in rows if r['kind']=='corpus');new=self.api('code-detail?kind=corpus&id='+row['id']+'&language='+lid)
        self.assertEqual(len(new['intervals']),1);self.assertEqual(new['intervals'][0]['span_id'],new['spans'][0]['id']);self.assertNotEqual(new['spans'][0]['id'],span['id'])
        self.assertEqual(self.undo(language=lid)[0],200);self.assertEqual(self.undo('redo',language=lid)[0],200);self.health()

    def test_export_after_deleted_code_marked_sentence_preserves_missing_references(self):
        e,ex,x,layer=self.seed();self.delete('corpus',e)
        lid,rows=self.imported(self.api('export-language?language=ordos'))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['kind'],'independent');self.health()
        self.assertEqual(self.undo()[0],200);self.health()

    def test_corporium_package_copy_delete_and_reimport_with_overrides(self):
        e,ex,x,layer=self.seed();self.mode('corpus',e,'override','');self.mode('independent',ex,'override','LOCAL')
        exported=self.api('language-package-export',{})
        token=language_exchange.stage(server.DB,language_exchange.staged(server.DB,exported['token'],'export'),'import')
        imported=self.api('language-package-import',dict(token=token,name='Package'))['language_id']
        rows=self.api('entries?language='+imported+'&include_independent=true')['items']
        expected={'corpus':'root-','independent':'root-LOCAL'}
        for row in rows:self.assertEqual(self.signature(row['kind'],row,imported)['words'][0][1],expected[row['kind']])
        self.health();self.assertEqual(self.undo(language=imported)[0],200);self.assertEqual(self.undo('redo',language=imported)[0],200);self.health()
        state=next(l for l in self.api('languages') if l['id']==imported)
        plan=self.api('language-delete-preview',dict(id=imported,revision=state['revision'],_language=imported))
        self.assertEqual(plan['blockers'],[])
        self.api('delete-language',dict(id=imported,revision=plan['revision'],token=plan['token'],confirmed=True,_language=imported))
        self.assertEqual(self.detail(ex,'independent')['body']['words'][0]['gloss'],'root-LOCAL');self.health()
        token=language_exchange.stage(server.DB,language_exchange.staged(server.DB,exported['token'],'export'),'import')
        again=self.api('language-package-import',dict(token=token,name='Package again'))['language_id']
        for row in self.api('entries?language='+again+'&include_independent=true')['items']:self.assertEqual(self.signature(row['kind'],row,again)['words'][0][1],expected[row['kind']])

    def test_copy_blank_override_and_live_inheritance_do_not_share_cache_stamps(self):
        e,ex,x,layer=self.seed();self.mode('corpus',e,'override','')
        blank=self.clone(e);self.assertEqual(self.detail(blank)['body']['words'][0]['gloss'],'root-')
        self.mode('corpus',e,'inherit');self.change(x,'POSS');live=self.clone(e)
        self.assertEqual(self.detail(live)['body']['words'][0]['gloss'],'root-POSS')
        self.change(x,'DAT')
        self.assertEqual(self.detail(blank)['body']['words'][0]['gloss'],'root-');self.assertEqual(self.detail(live)['body']['words'][0]['gloss'],'root-DAT')
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.detail(live)['body']['words'][0]['gloss'],'root-POSS')
        self.assertEqual(self.undo('redo')[0],200);self.health()

    def test_late_copy_failure_rolls_back_all_related_rows_and_history(self):
        e,ex,x,layer=self.seed();self.mode('corpus',e,'override','LOCAL')
        def snapshot():
            with server.connect(audit=False) as db:
                return {t:[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ('entries','corpus_units','unit_segments','lexical_links','morphology_analyses','annotation_cells','gloss_bindings','code_spans','undo_steps','undo_scopes')}
        before=snapshot();d=self.detail(e)
        with server.connect(audit=False) as db:db.execute("CREATE TRIGGER fail_copy_cell BEFORE INSERT ON annotation_cells BEGIN SELECT RAISE(ABORT,'isolated late failure'); END")
        # Deliberate storage failure, rather than a normal request validation error.
        with self.assertRaisesRegex(sqlite3.IntegrityError,'isolated late failure'):
            self.call('/api/duplicate-entry',dict(id=e['id'],text_id=e['text_id'],revision=d['revision'],order=[e['id']],where='end'))
        self.assertEqual(before,snapshot());self.health()
        with server.connect(audit=False) as db:db.execute('DROP TRIGGER fail_copy_cell')
        clone=self.clone(e);self.assertEqual(self.detail(clone)['body']['words'][0]['gloss'],'root-LOCAL')

    def test_paradigm_override_copy_exchange_then_delete_meaning_is_rejected(self):
        import test_paradigm_inheritance
        x=self.api('lexeme-save',dict(headword='go',body=test_paradigm_inheritance.body()))
        tid=self.api('import',dict(title='Paradigm',content='#pass([], (([went],[1SG.ACC]),), [])'))['id']
        e=self.api('entries?text='+tid)['items'][0];ex=self.example([('went','1SG.ACC')])
        for kind,row in [('corpus',e),('independent',ex)]:
            d=self.detail(row,kind)
            self.api('segmentation-link',dict(kind=kind,id=row['id'],revision=d['revision'],word=0,key='@word',lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id='verb',sense_id='went-meaning',form_id='went'))
        self.mode('corpus',e,'override','LOCAL');clone=self.clone(e)
        self.assertEqual(self.detail(clone)['body']['words'][0]['gloss'],'LOCAL')
        lid,rows=self.imported(self.api('export-language?language=ordos'))
        new=self.api('lexemes?language='+lid)['items'][0]
        new['body']['usages'][0]['senses'][0]['short_gloss']='2SG';new=self.api('lexeme-save',{**new,'_language':lid})
        for row in rows:self.assertEqual(self.signature(row['kind'],row,lid)['words'][0][1],'2SG.ACC' if row['kind']=='independent' else 'LOCAL')
        before=self.api('export-language?language='+lid)
        new['body']['paradigms']=[]
        self.assertEqual(self.call('/api/lexeme-save',{**new,'_language':lid})[0],400)
        self.assertEqual(self.api('export-language?language='+lid),before);self.health()
        self.assertEqual(self.undo(language=lid)[0],200);self.assertEqual(self.undo('redo',language=lid)[0],200);self.health()

    def test_native_morpheme_merge_keeps_colliding_main_senses_and_blank_override(self):
        a=self.api('morpheme-save',dict(form='n',body=dict(gloss='GEN')))
        b=self.api('morpheme-save',dict(form='n',body=dict(gloss='DAT')))
        tid=self.api('import',dict(title='Native merge',content='#pass([], (([n],[GEN.SG]),([n],[GEN]),([n],[DAT])), [])'))['id']
        e=self.api('entries?text='+tid)['items'][0];ex=self.example([('n','GEN.SG'),('n','GEN'),('n','DAT')])
        for kind,row in [('corpus',e),('independent',ex)]:
            for i,target in enumerate((a,a,b)):self.link(row,target,'@word',word=i,kind=kind)
            d=self.detail(row,kind);s=d['body']['words'][1]['gloss_sources'][0]
            self.api('gloss-source-save',dict(kind=kind,id=row['id'],revision=d['revision'],binding_id=s['id'],binding_revision=s['revision'],gloss_revision=d['body']['gloss_revision'],mode='override',value=''))
        a=self.api('morpheme?id='+a['id']);b=self.api('morpheme?id='+b['id'])
        merged=self.api('morpheme-merge',dict(id=a['id'],revision=a['revision'],target_id=b['id'],target_revision=b['revision'],confirmed=True))
        for action in (None,'undo','redo'):
            if action:self.assertEqual(self.undo(action)[0],200)
            for kind,row in [('corpus',e),('independent',ex)]:
                words=self.detail(row,kind)['body']['words']
                self.assertEqual([w['gloss'] for w in words],['GEN.SG','','DAT'])
                self.assertEqual([w['gloss_sources'][0]['mode'] for w in words],['inherit','override','inherit'])
            self.health()
        merged=self.api('morpheme?id='+b['id']);merged['body']['senses'][0]['gloss']='POSS';self.api('morpheme-save',merged)
        for kind,row in [('corpus',e),('independent',ex)]:self.assertEqual([w['gloss'] for w in self.detail(row,kind)['body']['words']],['POSS.SG','','DAT'])
        lid,rows=self.imported(self.api('export-language?language=ordos'))
        for row in rows:self.assertEqual([w[1] for w in self.signature(row['kind'],row,lid)['words']],['POSS.SG','','DAT'])
        self.health()

    def test_direct_conversion_into_existing_morpheme_keeps_override_and_history(self):
        e,ex,x,layer=self.seed()
        for kind,row in [('corpus',e),('independent',ex)]:self.mode(kind,row,'override','LOCAL')
        target=self.api('morpheme-save',dict(form='n',body=dict(gloss='DAT')))
        plan=self.api('lexeme-to-morpheme-preview',dict(id=x['id'],revision=x['revision']))
        self.api('lexeme-to-morpheme',dict(id=x['id'],revision=x['revision'],token=plan['token'],target_id=target['id']))
        for action in (None,'undo','redo'):
            if action:self.assertEqual(self.undo(action)[0],200)
            for kind,row in [('corpus',e),('independent',ex)]:
                w=self.detail(row,kind)['body']['words'][0]
                self.assertEqual(w['gloss'],'root-LOCAL');self.assertEqual(w['gloss_sources'][0]['mode'],'override')
            self.health()

    def test_foreign_sentence_package_remaps_referenced_language_then_history(self):
        foreign=self.api('save-language',dict(name='Quoted language',metadata={}))['id']
        x=self.api('lexeme-save',dict(headword='quoted',body=dict(usages=[dict(senses=[dict(short_gloss='quote')])]),_language=foreign))
        tid=self.api('import',dict(title='Mixed',content='#pass([], (([quoted],[quote]),), [])'))['id']
        e=self.api('entries?text='+tid)['items'][0]
        self.api('save',{**e,'language_id':foreign,'notes':'quoted language'})
        self.link(e,x,'@word');self.mode('corpus',e,'override','LOCAL')
        exported=self.api('language-package-export',{})
        token=language_exchange.stage(server.DB,language_exchange.staged(server.DB,exported['token'],'export'),'import')
        lid=self.api('language-package-import',dict(token=token,name='Mixed copy'))['language_id']
        row=self.api('entries?language='+lid)['items'][0]
        self.assertNotEqual(row['language_id'],foreign);self.assertNotEqual(row['language_id'],lid)
        self.assertEqual(row['words'][0]['gloss'],'LOCAL');self.health()
        with server.connect(audit=False) as db:
            link=db.execute('SELECT l.lexeme_id,x.language_id FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id JOIN lexemes x ON x.id=l.lexeme_id WHERE u.entry_id=?',(row['id'],)).fetchone()
            self.assertNotEqual(link['lexeme_id'],x['id']);self.assertEqual(link['language_id'],row['language_id'])
        self.assertEqual(self.undo(language=lid)[0],200);self.assertEqual(self.undo('redo',language=lid)[0],200);self.health()
