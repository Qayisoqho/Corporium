import undo_codec
import copy
import json
import unittest
import server
import test_dictionary_gloss_sync as legacy


class GlossInheritanceTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','undo','api','word','example','detail','link'):
        locals()[name]=getattr(legacy.DictionaryGlossSyncTests,name)

    def fixture(self,gloss='家.SG'):
        e=self.seed('#pass([], (([home],['+gloss+']),([free],[])), [])')
        ex=self.example([('home',gloss),('free','')]);x=self.word('home',['家'])
        for kind,row in [('corpus',e),('independent',ex)]:self.link(row,x,'@word',kind=kind)
        return e,ex,x

    def change(self,x,value):
        x=self.api('lexeme?id='+x['id']);x['body']['usages'][0]['senses'][0]['short_gloss']=value
        return self.api('lexeme-save',x)

    def mode(self,kind,row,mode,value=''):
        d=self.detail(row,kind);source=d['body']['words'][0]['gloss_sources'][0]
        return self.api('gloss-source-save',dict(kind=kind,id=row['id'],revision=d['revision'],binding_id=source['id'],binding_revision=source['revision'],gloss_revision=d['body']['gloss_revision'],mode=mode,value=value))

    def labels(self,e,ex):return [self.entries()[0]['words'][0]['gloss'],self.detail(ex,'independent')['body']['words'][0]['gloss']]

    def test_export_reuse_never_changes_inputs_and_tracks_meaning_writes(self):
        import gloss_inheritance as gloss
        e,ex,x=self.fixture('手写')
        with server.connect(audit=False) as db:
            row=db.execute("SELECT * FROM corpus_units WHERE entry_id=? AND kind='word' AND position=0 AND active=1",(e['id'],)).fetchone()
            original=dict(row);first=gloss.export_unit(db,row)
            self.assertEqual(first['gloss'],'家')
            self.assertEqual(gloss.export_unit(db,row),first)
            self.assertEqual(dict(row),original)
            cache=gloss.session(db);self.assertLessEqual(cache.export_bytes,4*1024**2)
            db.execute('UPDATE gloss_meanings SET gloss=?,revision=revision+1 WHERE target_id=?',('住所',x['id']))
            self.assertEqual(gloss.export_unit(db,row)['gloss'],'住所')
            self.assertEqual(dict(row),original)

    def test_inherit_now_and_keep_unlinked_blank(self):
        e,ex,x=self.fixture('手写')
        self.assertEqual(self.labels(e,ex),['家','家'])
        x=self.change(x,'住所')
        self.assertEqual(self.labels(e,ex),['住所','住所'])
        self.assertEqual(self.entries()[0]['words'][1]['gloss'],'')
        self.assertEqual(self.detail(ex,'independent')['body']['words'][1]['gloss'],'')

    def test_no_sentence_index_or_segment_writeback(self):
        e,ex,x=self.fixture()
        with server.connect(audit=False) as db:
            before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ('entries','dictionary_examples','corpus_units','unit_segments')}
        self.change(x,'住所')
        self.assertEqual(self.labels(e,ex),['住所.SG','住所.SG'])
        with server.connect(audit=False) as db:
            for t,rows in before.items():self.assertEqual(rows,[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')],t)
            delta=undo_codec.decode(db.execute('SELECT changes FROM undo_steps ORDER BY id DESC LIMIT 1').fetchone()[0])
            self.assertEqual({c['table'] for c in delta},{'lexemes','gloss_meanings'})

    def test_blank_override_and_return_to_inherit(self):
        e,ex,x=self.fixture()
        for kind,row in [('corpus',e),('independent',ex)]:self.mode(kind,row,'override','')
        x=self.change(x,'住所')
        self.assertEqual(self.labels(e,ex),['',''])
        for kind,row in [('corpus',e),('independent',ex)]:self.mode(kind,row,'inherit')
        self.assertEqual(self.labels(e,ex),['住所.SG','住所.SG'])

    def test_unlink_freezes_current_effective_gloss(self):
        e,ex,x=self.fixture();x=self.change(x,'住所')
        d=self.detail(e);uid=d['body']['words'][0]['unit_id'];u=self.api('unit-dictionary?id='+uid)
        self.api('lexeme-unlink',dict(id=u['link']['id'],revision=u['link']['revision']))
        d=self.detail(ex,'independent');self.api('segmentation-link',dict(kind='independent',id=ex['id'],revision=d['revision'],remove_target=0))
        self.change(x,'房屋')
        self.assertEqual(self.labels(e,ex),['住所.SG','住所.SG'])
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT count(*) FROM gloss_bindings').fetchone()[0],0)

    def test_search_and_export_read_current_gloss(self):
        e,ex,x=self.fixture();self.change(x,'住所')
        found=self.api('entries?language=ordos&q=住所&field=gloss&include_independent=true')
        self.assertEqual(found['total'],2)
        self.assertEqual(self.api('example-library?language=ordos&source=all&q=住所&field=gloss')['total'],2)
        self.assertIn('住所.SG',self.api('export?id='+e['text_id']))
        self.assertEqual(self.api('entries?language=ordos&q=家&field=gloss')['total'],0)

    def test_metadata_save_preserves_inheritance_and_identities(self):
        e,ex,x=self.fixture();x=self.change(x,'住所')
        old=self.entries()[0];body={**old,'notes':'new notes'};self.api('save',body)
        self.assertEqual(self.entries()[0]['words'][0]['unit_id'],old['words'][0]['unit_id'])
        d=self.detail(ex,'independent');b=copy.deepcopy(d['body']);b['notes']='new notes'
        self.api('example-save',dict(id=ex['id'],revision=d['revision'],body=b))
        self.change(x,'房屋');self.assertEqual(self.labels(e,ex),['房屋.SG','房屋.SG'])
        for kind,row in [('corpus',e),('independent',ex)]:self.assertEqual(self.detail(row,kind)['body']['words'][0]['gloss_sources'][0]['mode'],'inherit')

    def test_override_undo_redo_without_source_body_edits(self):
        e,ex,x=self.fixture();self.mode('corpus',e,'override','本句')
        self.assertEqual(self.labels(e,ex)[0],'本句')
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.labels(e,ex)[0],'家.SG')
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.labels(e,ex)[0],'本句')

    def test_migration_replaces_linked_only_and_is_idempotent(self):
        import gloss_inheritance
        e,ex,x=self.fixture()
        with server.connect(audit=False) as db:
            db.execute('DELETE FROM gloss_bindings');db.execute('DELETE FROM gloss_migrations')
            for kind,row in [('corpus',e),('independent',ex)]:
                table='entries' if kind=='corpus' else 'dictionary_examples'
                b=json.loads(db.execute('SELECT body FROM '+table+' WHERE id=?',(row['id'],)).fetchone()[0]);b['words'][0]['gloss']='手写'
                db.execute('UPDATE '+table+' SET body=? WHERE id=?',(json.dumps(b,ensure_ascii=False),row['id']))
                if kind=='corpus':server.lexicon.sync_entry(db,row['id'],preserve_complex=True,preserve_slots=True)
            before=json.loads(db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0])['words'][1]
            result=gloss_inheritance.migrate(db);n=db.total_changes
            self.assertEqual(gloss_inheritance.migrate(db),result);self.assertEqual(n,db.total_changes)
            after=json.loads(db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0])['words'][1]
            self.assertEqual(before,after)
        self.assertEqual(self.labels(e,ex),['家','家'])

    def test_typed_annotation_is_override_in_both_sources(self):
        e,ex,x=self.fixture();x=self.change(x,'住所')
        b=self.entries()[0];b['words'][0]['gloss']='本句';b.setdefault('notes','');self.api('save',b)
        d=self.detail(ex,'independent');d['body']['words'][0]['gloss']=''
        self.api('example-save',dict(id=ex['id'],revision=d['revision'],body=d['body']))
        self.change(x,'房屋');self.assertEqual(self.labels(e,ex),['本句',''])

    def test_stale_dictionary_snapshot_cannot_be_saved_as_override(self):
        e,ex,x=self.fixture();old=self.entries()[0];d=self.detail(ex,'independent')
        self.change(x,'住所');old['notes']='unsaved'
        self.assertEqual(self.call('/api/save',old)[0],400)
        self.assertEqual(self.call('/api/example-save',dict(id=ex['id'],revision=d['revision'],body=d['body']))[0],400)
        self.assertEqual(self.labels(e,ex),['住所.SG','住所.SG'])

    def test_analysis_and_frozen_snapshot(self):
        self.api('grammar-save',dict(symbol='POSS'))
        e,ex,x=self.fixture();x=self.change(x,'POSS')
        run=self.api('analysis-run',dict(query=dict(conditions=[dict(field='tag',value='POSS',mode='exact')],scope={'source':'all'})))
        self.assertEqual(run['summary']['sentences'],2)
        saved=self.api('analysis-save',dict(kind='snapshot',run_id=run['id'],name='frozen'))
        x=self.change(x,'房屋')
        frozen=self.api('analysis-result?language=ordos&snapshot=true&id='+saved['id'])
        self.assertTrue(all(item['record']['body']['words'][0]['gloss']=='POSS.SG' for item in frozen['items']))

    def test_language_exchange_keeps_override_and_live_reading(self):
        e,ex,x=self.fixture();x=self.change(x,'住所')
        self.mode('corpus',e,'override','特殊');self.mode('independent',ex,'override','')
        bundle=self.api('export-language?language=ordos')
        self.assertEqual(json.loads(bundle['texts'][0]['entries'][0]['body'])['words'][0]['gloss'],'特殊')
        lid=self.api('save-language',dict(name='Imported',metadata={}))['id']
        self.api('import-language',dict(_language=lid,bundle=bundle))
        rows=self.api('entries?language='+lid+'&include_independent=true')['items']
        self.assertEqual({r['kind']:r['words'][0]['gloss'] for r in rows},{'corpus':'特殊','independent':''})
        for r in rows:self.assertEqual(r['words'][0]['gloss_sources'][0]['mode'],'override')

    def test_unlinked_child_freezes_even_with_inherited_whole_word(self):
        e=self.seed('#pass([], (([home-n],[家-GEN])), [])');ex=self.example([('home-n','家-GEN')])
        whole=self.word('home-n',['家-GEN']);child=self.word('n',['POSS'])
        for kind,row in [('corpus',e),('independent',ex)]:
            self.link(row,whole,'@word',kind=kind);self.link(row,child,'1:host',kind=kind)
        self.assertEqual(self.labels(e,ex),['家-POSS','家-POSS'])
        d=self.detail(e);uid=d['body']['words'][0]['morphemes'][1]['unit_id'];u=self.api('unit-dictionary?id='+uid)
        self.api('lexeme-unlink',dict(id=u['link']['id'],revision=u['link']['revision']))
        d=self.detail(ex,'independent');index=next(i for i,t in enumerate(d['body']['targets']) if t['segmentation_ref']['key']=='1:host')
        self.api('segmentation-link',dict(kind='independent',id=ex['id'],revision=d['revision'],remove_target=index))
        self.change(child,'FUT');self.change(whole,'住所-DAT')
        self.assertEqual(self.labels(e,ex),['住所-POSS','住所-POSS'])
        for kind,row in [('corpus',e),('independent',ex)]:self.link(row,self.api('lexeme?id='+child['id']),'1:host',kind=kind)
        self.assertEqual(self.labels(e,ex),['住所-FUT','住所-FUT'])

    def test_group_provider_keeps_member_spans_consistent_after_whole_word(self):
        import gloss_inheritance
        e=self.seed('#pass([], (([we-go-la],[PST-go-PST])), [])');ex=self.example([('we-go-la','PST-go-PST')])
        whole=self.word('we-go-la',['PST-go-PST']);child=self.word('we…la',['家'])
        for kind,row in [('corpus',e),('independent',ex)]:
            d=self.detail(row,kind)
            self.api('segmentation-save',dict(kind=kind,id=row['id'],revision=d['revision'],word=0,action='save',type='circumfix',members=['0:host','2:host'],gloss='PST'))
            self.link(row,whole,'@word',kind=kind)
            key=self.detail(row,kind)['body']['words'][0]['morphemes'][0]['key'];self.link(row,child,key,kind=kind)
        with server.connect(audit=False) as db:
            db.execute('DELETE FROM gloss_migrations');gloss_inheritance.migrate(db)
        self.assertEqual(self.labels(e,ex),['家-go-家','家-go-家'])
        self.change(whole,'ANT-go-ANT');self.assertEqual(self.labels(e,ex),['家-go-家','家-go-家'])

    def test_copy_between_sources_preserves_explicit_override(self):
        e,ex,x=self.fixture();self.mode('corpus',e,'override','定制')
        s=self.api('word-transfer-snapshot?kind=corpus&id='+e['id']);t=self.api('word-transfer-snapshot?kind=independent&id='+ex['id'])
        self.api('word-transfer',dict(source=dict(kind='corpus',id=e['id'],token=s['transfer_token']),target=dict(kind='independent',id=ex['id'],token=t['transfer_token']),slots=[s['words'][0]['id']],mode='copy',confirmed=True,position=len(t['words'])))
        self.change(x,'住所')
        copied=self.detail(ex,'independent')['body']['words'][-1]
        self.assertEqual(copied['gloss'],'定制');self.assertEqual(copied['gloss_sources'][0]['mode'],'override')

    def test_form_save_after_live_meaning_change_keeps_inheritance(self):
        e,ex,x=self.fixture();x=self.change(x,'住所');x['headword']='house';self.api('lexeme-save',x)
        for kind,row in [('corpus',e),('independent',ex)]:
            word=self.detail(row,kind)['body']['words'][0]
            self.assertEqual((word['form'],word['gloss']),('house','住所.SG'))
            self.assertEqual(word['gloss_sources'][0]['mode'],'inherit')
        self.change(x,'房屋');self.assertEqual(self.labels(e,ex),['房屋.SG','房屋.SG'])

    def test_complete_backup_restore_and_reopen_preserve_both_overrides(self):
        from pathlib import Path
        from restore_backup import restore
        e,ex,x=self.fixture();self.mode('corpus',e,'override','特殊');self.mode('independent',ex,'override','')
        source=Path(self.temp.name)/'inheritance-backup.json';target=Path(self.temp.name)/'restored.sqlite3'
        source.write_text(json.dumps(self.api('backup'),ensure_ascii=False),encoding='utf-8');restore(source,target)
        old=server.DB
        try:
            server.DB=target;server.init();self.change(x,'住所')
            self.assertEqual(self.labels(e,ex),['特殊',''])
        finally:server.DB=old


if __name__=='__main__':unittest.main()
