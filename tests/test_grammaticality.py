import json
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch
import test_server,test_lexicon
import server,grammaticality,corpus,lexicon,journal,sqlite3,copy
import base64,excel_exchange
from restore_backup import restore


class GrammaticalityTests(unittest.TestCase):
    for name in ('setUp','tearDown','call'):
        locals()[name]=getattr(test_server.APITests,name)
    for name in ('seed','entries','undo'):
        locals()[name]=getattr(test_lexicon.LexiconTests,name)

    def data(self,kind,e):return self.call('/api/annotations?kind='+kind+'&id='+e['id'])[1]
    def mark(self,kind,e,value,language='ordos'):
        d=self.data(kind,e);code,r=self.call('/api/grammaticality-save',dict(kind=kind,id=e['id'],revision=d['revision'],grammaticality=value,_language=language));self.assertEqual(code,200,r);return self.data(kind,e)
    def independent(self):
        code,r=self.call('/api/example-save',dict(body=dict(ipa='ind',translation='free',words=[dict(form='dog',gloss='dog')],targets=[])))
        self.assertEqual(code,200,r);return r
    def type(self,language='ordos',**changes):
        cat=self.call('/api/grammaticality-types?language='+language)[1]
        code,r=self.call('/api/grammaticality-type-save',{**dict(revision=cat['revision'],name='存疑程度高',symbol='??',_language=language),**changes});self.assertEqual(code,200,r);return r

    def test_only_independent_search_and_text_save_rejected(self):
        e=self.seed();i=self.independent();self.assertNotIn('grammaticality',e)
        cat=self.call('/api/grammaticality-types?language=ordos')[1];self.assertEqual([r['symbol'] for r in cat['items']],['*','?'])
        self.assertEqual(self.call('/api/entries?include_independent=true&grammaticality=legal')[1]['total'],1)
        code,r=self.call('/api/grammaticality-save',dict(kind='corpus',id=e['id'],revision=e['revision'],grammaticality='questionable'))
        self.assertEqual(code,400,r);self.assertIn('独立例句',r['error'])
        self.mark('independent',i,'questionable')
        self.assertEqual(self.call('/api/example-library?grammaticality=ordos/questionable')[1]['total'],1)
        self.assertEqual(self.call('/api/example-library?grammaticality=other/questionable')[1]['total'],0)
        self.assertEqual(self.call('/api/example-library?source=corpus&grammaticality=legal')[1]['total'],0)
        self.assertEqual(self.call('/api/example-library?grammaticality=legal')[1]['total'],0)
        self.mark('independent',i,'');self.assertEqual(self.call('/api/example-library?grammaticality=legal')[1]['total'],1)
        self.assertNotIn('grammaticality',self.data('corpus',e)['body'])

    def test_catalog_rename_no_sentence_write_disable_delete_and_undo(self):
        self.seed();e=self.independent();t=self.type();self.mark('independent',e,t['id'])
        with server.connect(audit=False) as db:before=db.execute('SELECT body,revision FROM dictionary_examples WHERE id=?',(e['id'],)).fetchone();before=tuple(before)
        self.type(id=t['id'],name='很不自然',symbol='#')
        with server.connect(audit=False) as db:self.assertEqual(tuple(db.execute('SELECT body,revision FROM dictionary_examples WHERE id=?',(e['id'],)).fetchone()),before)
        self.type(id=t['id'],name='很不自然',symbol='#',enabled=False)
        i=self.independent();d=self.data('independent',i)
        self.assertEqual(self.call('/api/grammaticality-save',dict(kind='independent',id=i['id'],revision=d['revision'],grammaticality=t['id']))[0],400)
        cat=self.call('/api/grammaticality-types?language=ordos')[1]
        self.assertEqual(self.call('/api/grammaticality-type-delete',dict(id=t['id'],revision=cat['revision'],confirmed=True))[0],400)
        self.mark('independent',e,'');cat=self.call('/api/grammaticality-types?language=ordos')[1]
        self.assertEqual(self.call('/api/grammaticality-type-delete',dict(id=t['id'],revision=cat['revision'],confirmed=True))[0],200)
        self.assertEqual(self.undo()[0],200);self.assertIn(t['id'],[r['id'] for r in self.call('/api/grammaticality-types?language=ordos')[1]['items']])

    def test_quick_save_atomic_stale_language_unknown_and_undo(self):
        self.seed();e=self.independent();t=self.type();other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        d=self.data('independent',e)
        for value in (True,123,{},'missing'):
            self.assertEqual(self.call('/api/grammaticality-save',dict(kind='independent',id=e['id'],revision=d['revision'],grammaticality=value))[0],400)
        self.assertEqual(self.call('/api/grammaticality-save',dict(kind='independent',id=e['id'],revision=d['revision'],grammaticality=t['id'],_language=other))[0],400)
        with patch.object(lexicon,'validate_links',side_effect=AssertionError('unrelated graph scan')):self.mark('independent',e,t['id'])
        self.assertEqual(self.call('/api/grammaticality-save',dict(kind='independent',id=e['id'],revision=d['revision'],grammaticality=''))[0],400)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.data('independent',e)['body'].get('grammaticality',''),'')
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.data('independent',e)['body']['grammaticality'],t['id'])
        self.assertEqual(self.call('/api/grammaticality-types?language='+other)[1]['items'],[dict(r) for r in grammaticality.DEFAULTS])

    def test_all_editor_paths_keep_independent_and_strip_corpus(self):
        e=self.seed();i=self.independent()
        for kind,record in [('corpus',e),('independent',i)]:
            d=self.mark(kind,record,'questionable') if kind=='independent' else self.data(kind,record)
            body=dict(d['body']);body.pop('grammaticality',None);body['notes']='edited'
            if kind=='corpus':body.update(grammaticality='missing',grammaticality_display={'id':'missing'},grammaticality_definition={})
            payload=dict(kind=kind,id=record['id'],revision=d['revision'],before=d['cells'],layers=d['layers'],cells=[],body=body)
            code,r=self.call('/api/inline-save',payload);self.assertEqual(code,200,r)
            actual=self.data(kind,record)['body'];self.assertEqual(actual.get('grammaticality'),'questionable' if kind=='independent' else None)
            d=self.data(kind,record);body=dict(d['body']);body['grammaticality']=''
            payload.update(revision=d['revision'],before=d['cells'],slot_ids=[w['id'] for w in d['words']],body=body)
            code,r=self.call('/api/inline-save',payload);self.assertEqual(code,200,r)
            self.assertEqual(self.data(kind,record)['body'].get('grammaticality'),'' if kind=='independent' else None)
        d=self.data('corpus',e);body={**d['body'],'id':e['id'],'revision':d['revision'],'notes':'saved','grammaticality':'ungrammatical'}
        self.assertEqual(self.call('/api/save',body)[0],200);self.assertNotIn('grammaticality',self.data('corpus',e)['body'])
        d=self.mark('independent',i,'ungrammatical');body=dict(d['body']);body.pop('grammaticality')
        self.assertEqual(self.call('/api/example-save',dict(id=i['id'],revision=d['revision'],body=body))[0],200);self.assertEqual(self.data('independent',i)['body']['grammaticality'],'ungrammatical')
        with server.connect(audit=False) as db:
            for row in db.execute('SELECT body FROM entries'):
                self.assertFalse(set(grammaticality.CORPUS_FIELDS)&json.loads(row[0]).keys())

    def test_analysis_conditions_distribution_and_json_only_independent(self):
        e=self.seed();i=self.independent();self.mark('independent',i,'ungrammatical')
        code,r=self.call('/api/analysis-run',dict(query=dict(conditions=[dict(field='grammaticality',value='*')],scope={'source':'all'})));self.assertEqual(code,200,r);self.assertEqual(r['summary']['sentences'],1)
        page=self.call('/api/analysis-result?language=ordos&id='+r['id']+'&dimension=grammaticality')[1];self.assertEqual(page['items'][0]['value'],'不合语法');self.assertEqual(page['items'][0]['word'],-1)
        ex=self.call('/api/analysis-export?language=ordos&id='+r['id'])[1];self.assertEqual(ex['records']['independent:'+i['id']]['body']['grammaticality'],'ungrammatical')
        self.assertEqual(ex['records']['independent:'+i['id']]['body']['grammaticality_display']['symbol'],'*')
        stats=self.call('/api/analysis-run',dict(query=dict(kind='counts',scope=dict(mode='language'))))[1]['summary']
        self.assertEqual({r['name']:r['sentences'] for r in stats['grammaticality']},{'不合语法':1});self.assertEqual(stats['sentences'],2)
        run=self.call('/api/analysis-run',dict(query=dict(conditions=[dict(field='form',value='')],scope={'source':'all'} )))[1]
        page=self.call('/api/analysis-result?language=ordos&id='+run['id']+'&dimension=grammaticality')[1]
        self.assertEqual([r['value'] for r in page['frequencies']],['不合语法']);self.assertEqual(sum(r['sentences'] for r in page['frequencies']),1)
        ex=self.call('/api/analysis-export?language=ordos&id='+run['id'])[1]
        self.assertFalse(set(grammaticality.CORPUS_FIELDS)&ex['records'][e['id']]['body'].keys())
        code,r=self.call('/api/analysis-run',dict(query=dict(conditions=[dict(field='form',value=''),dict(field='grammaticality',value='*',relation='sentence')],scope={'source':'all'})))
        self.assertEqual(code,200,r);self.assertEqual(r['summary']['sentences'],1)

    def test_typst_ignores_old_corpus_mark_and_export_has_no_mark(self):
        e=self.seed();raw=self.call('/api/export?id='+e['text_id'])[1]
        legacy='// corporium-grammaticality: '+json.dumps(dict(id='old',definition=dict(id='old',name='旧类型',symbol='!')))+'\n'+raw
        parsed,errors=corpus.parse(legacy);self.assertFalse(errors);self.assertNotIn('grammaticality',parsed[0]);self.assertEqual(parsed[0]['ipa'],e['ipa'])
        self.assertNotIn('corporium-grammaticality',corpus.export_entry({**parsed[0],'grammaticality':'old'}))
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        code,r=self.call('/api/import',dict(title='Copy',content=legacy,_language=other));self.assertEqual(code,200,r)
        self.assertNotIn('grammaticality',self.call('/api/entries?language='+other)[1]['items'][0])
        self.assertNotIn('old',[r['id'] for r in self.call('/api/grammaticality-types?language='+other)[1]['items']])

    def test_backup_language_exchange_preserves_catalog_and_shared_attribute(self):
        e=self.seed();i=self.independent();t=self.type();self.mark('independent',i,t['id'])
        bundle=self.call('/api/export-language?language=ordos')[1];legacy=json.loads(bundle['texts'][0]['entries'][0]['body']);legacy['grammaticality']='missing';bundle['texts'][0]['entries'][0]['body']=json.dumps(legacy);other=self.call('/api/save-language',dict(name='Copy',metadata={}))[1]['id']
        code,r=self.call('/api/import-language',dict(_language=other,bundle=bundle));self.assertEqual(code,200,r)
        self.assertEqual(self.call('/api/example-library?language='+other+'&grammaticality='+t['id'])[1]['total'],1)
        backup=self.call('/api/backup')[1];old_body=json.loads(backup['entries'][0]['body']);old_body['grammaticality']='old';backup['entries'][0]['body']=json.dumps(old_body);p=Path(self.temp.name)/'backup.json';p.write_text(json.dumps(backup),encoding='utf-8');dest=Path(self.temp.name)/'restored.sqlite3';restore(p,dest);server.DB=dest
        self.assertNotIn('grammaticality',self.data('corpus',e)['body']);self.assertEqual(self.data('independent',i)['body']['grammaticality'],t['id'])
        self.assertEqual(self.call('/api/grammaticality-types?language=ordos')[1]['items'][-1]['symbol'],'??')
        with server.connect(audit=False) as db:self.assertFalse(grammaticality.corpus_rows_needed(db))

    def test_invalid_catalog_and_direct_language_edit_reference_protection(self):
        self.seed();e=self.independent();t=self.type();self.mark('independent',e,t['id'])
        language=next(l for l in self.call('/api/languages')[1] if l['id']=='ordos');meta=json.loads(language['metadata']);meta['grammaticality_types']=[]
        self.assertEqual(self.call('/api/save-language',{**language,'metadata':meta})[0],400)
        for rows in ([dict(id='x',name='合法',symbol='!')],[dict(id='x',name='x',symbol='')],[dict(id='x',name='x',symbol='!'),dict(id='y',name='y',symbol='!')]):
            with self.assertRaises(ValueError):grammaticality.clean(rows)

    def test_new_sentence_drafts_and_survey_local_judgment_stay_independent(self):
        e=self.seed()
        for kind in ('corpus','independent'):
            code,r=self.call('/api/sentence-create',dict(kind=kind,text_id=e['text_id'],body=dict(ipa='',translation='',notes='',words=[dict(form='a',gloss='x')],grammaticality='questionable'),slot_ids=['new:test'],before=[],layers=[],cells=[]))
            self.assertEqual(code,200,r);self.assertEqual(self.data(kind,r)['body'].get('grammaticality'),'questionable' if kind=='independent' else None)
        i=r
        def survey(action,**body):
            body['version']=self.call('/api/survey?language=ordos')[1]['version'];code,r=self.call('/api/survey-'+action,body);self.assertEqual(code,200,r);return r
        node=survey('save',kind='section',title='Context',body={})['id']
        survey('evidence',node_id=node,kind='independent',record_id=i['id'],body=dict(judgment='只在此语境自然'))
        before=self.call('/api/survey-detail?language=ordos&id='+node)[1]['items'][0]['body']
        self.mark('independent',i,'ungrammatical')
        detail=self.call('/api/survey-detail?language=ordos&id='+node)[1]['items'][0]
        self.assertEqual(detail['body'],before);self.assertEqual(detail['record']['body']['grammaticality'],'ungrammatical')

    def test_frozen_snapshot_keeps_definition_after_live_catalog_rename(self):
        self.seed();e=self.independent();self.mark('independent',e,'ungrammatical')
        run=self.call('/api/analysis-run',dict(query=dict(conditions=[dict(field='grammaticality',value='*')],scope={'source':'all'})))[1]
        code,saved=self.call('/api/analysis-save',dict(kind='snapshot',name='Before',run_id=run['id']));self.assertEqual(code,200,saved)
        self.type(id='ungrammatical',name='不可接受',symbol='!')
        result=self.call('/api/analysis-result?language=ordos&id='+saved['id']+'&snapshot=true')[1]
        self.assertEqual(result['items'][0]['record']['body']['grammaticality_display']['symbol'],'*')
        self.assertEqual(self.call('/api/grammaticality-types?language=ordos')[1]['items'][0]['symbol'],'!')

    def test_excel_corpus_has_no_judgment_column_or_mapping(self):
        e=self.seed();exported=self.call('/api/excel-export',dict(ids=[e['text_id']]))[1]
        p=Path(self.temp.name)/'sentences.xlsx';p.write_bytes(base64.b64decode(exported['data']))
        sheets=excel_exchange.read(p);self.assertNotIn('Grammaticality',sheets[0]['rows'][1].values())
        upload=self.call('/api/excel-inspect',dict(data=exported['data']))[1]
        cfg=dict(index=0,title='Again',start=2,id_column=1,mappings=[dict(column=3,target='form'),dict(column=4,target='gloss'),dict(column=7,target='grammaticality')])
        payload=dict(token=upload['token'],sheets=[cfg]);self.assertEqual(self.call('/api/excel-preview',payload)[0],400)
        cfg['mappings'].pop();code,plan=self.call('/api/excel-preview',payload);self.assertEqual(code,200,plan)
        self.assertNotIn('grammaticality',plan['texts'][0]['examples'][0]['body'])

    def test_startup_migration_backs_up_only_changes_text_fields_and_is_idempotent(self):
        e=self.seed();i=self.independent();self.mark('independent',i,'questionable')
        with server.connect(audit=False) as db:
            body=json.loads(db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0]);body.update(grammaticality='old',grammaticality_definition={'id':'old'},grammaticality_display={'symbol':'!'})
            db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(body),e['id']))
            before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in journal.TABLES if t!='entries'}
        server.init()
        with server.connect(audit=False) as db:
            self.assertFalse(grammaticality.corpus_rows_needed(db));self.assertEqual(json.loads(db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0]),grammaticality.strip_corpus(dict(body)))
            self.assertEqual(before,{t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before})
        backups=list((server.DB.parent/'backups').glob('*.sqlite3'));self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups[0])) as old:self.assertEqual(json.loads(old.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0])['grammaticality'],'old')
        server.init();self.assertEqual(list((server.DB.parent/'backups').glob('*.sqlite3')),backups)
        self.assertEqual(self.data('independent',i)['body']['grammaticality'],'questionable')

    def test_legacy_undo_and_redo_do_not_restore_corpus_field(self):
        e=self.seed();self.assertEqual(self.call('/api/save',{**e,'notes':'edited'})[0],200)
        with server.connect(audit=False) as db:
            row=db.execute('SELECT id,changes FROM undo_steps ORDER BY id DESC LIMIT 1').fetchone();changes=journal.decode_changes(row['changes'])
            for c in changes:
                if c['table']!='entries':continue
                for side in ('before','after'):
                    if c[side]:
                        body=json.loads(c[side]['body']);body['grammaticality']='old';c[side]['body']=json.dumps(body)
            db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(json.dumps(changes),row['id']))
        for direction,notes in [('undo',''),('redo','edited')]:
            self.assertEqual(self.undo(direction)[0],200);body=self.data('corpus',e)['body'];self.assertEqual(body.get('notes',''),notes);self.assertNotIn('grammaticality',body)

    def test_old_frozen_text_card_is_cleaned_on_read_and_both_exports(self):
        import analysis_workspace
        e=self.seed();run=self.call('/api/analysis-run',dict(query=dict(conditions=[dict(field='form',value='')],scope={'source':'all'} )))[1]
        saved=self.call('/api/analysis-save',dict(kind='snapshot',name='Old',run_id=run['id']))[1]
        with server.connect(audit=False) as db:
            row=db.execute('SELECT payload FROM analysis_saved WHERE id=?',(saved['id'],)).fetchone();result=analysis_workspace.unpack(row['payload']);result['records'][e['id']]['body'].update(grammaticality='old',grammaticality_display={'symbol':'!'})
            db.execute('UPDATE analysis_saved SET payload=? WHERE id=?',(analysis_workspace.pack(result),saved['id']))
        page=self.call('/api/analysis-result?language=ordos&id='+saved['id']+'&snapshot=true')[1]
        self.assertNotIn('grammaticality',page['items'][0]['record']['body'])
        ex=self.call('/api/analysis-export?language=ordos&id='+saved['id']+'&snapshot=true')[1];self.assertNotIn('grammaticality',ex['records'][e['id']]['body'])
        with server.connect(audit=False) as db:
            from unittest.mock import patch
            with patch('language_exchange.stage',side_effect=lambda dbpath,path,kind:str(path)):
                staged=analysis_workspace.export_file(db,server.DB,'ordos',dict(id=saved['id'],snapshot='true'))
            p=Path(staged['token']);exported=json.loads(p.read_text(encoding='utf-8'));p.unlink()
        self.assertNotIn('grammaticality',exported['records'][e['id']]['body'])

    def test_type_order_and_old_exchange_do_not_override_new_language_settings(self):
        self.seed();t=self.type(position=1)
        self.assertEqual(self.call('/api/grammaticality-types?language=ordos')[1]['items'][0]['id'],t['id'])
        bundle=self.call('/api/export-language?language=ordos')[1]
        meta=json.loads(bundle['language']['metadata']);meta.pop(grammaticality.KEY);bundle['language']['metadata']=json.dumps(meta)
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id'];self.type(language=other,id='ungrammatical',name='不可接受',symbol='!')
        code,r=self.call('/api/import-language',dict(_language=other,bundle=bundle));self.assertEqual(code,200,r)
        self.assertEqual(self.call('/api/grammaticality-types?language='+other)[1]['items'][0]['symbol'],'!')


if __name__=='__main__':unittest.main()
