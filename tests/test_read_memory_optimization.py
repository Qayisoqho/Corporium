"""Contract checks for selective legacy snapshots and streaming full exports."""
import base64
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zlib

import analysis_payload
import analysis_workspace as analysis
import language_exchange
import lexicon
import gloss_inheritance
import long_tasks
import server
import test_analysis_workspace
import test_evidence_index


class PayloadReaderTests(unittest.TestCase):
    def test_chunk_boundaries_unicode_numbers_nested_objects_and_legacy_format(self):
        body=dict(hits=[dict(entry_id='é',word=1,value='𐀀\\\"\n',dimensions=dict(tag=['GEN'],text=['t']))]*3,
            labels={'value':{'é':'汉字'}},records={'é':{'body':{'words':[{'form':'a','gloss':'A'}]}}},
            languages=[{'id':'é'}],numbers=[-1.234e-20,1e30,True,False,None])
        source=json.dumps(body,ensure_ascii=True,separators=(',',':'))
        for size in range(1,35):
            reader=analysis_payload.Reader(source[i:i+size] for i in range(0,len(source),size))
            self.assertEqual(reader.value(),body);self.assertEqual(reader.peek(),'')
        packed=base64.b64encode(zlib.compress(source.encode())).decode()
        self.assertEqual(analysis_payload.read(packed,record_ids={'é'}),body)
        self.assertEqual(list(analysis_payload.items(packed,'hits')),[(None,h) for h in body['hits']])
        self.assertEqual(list(analysis_payload.items(packed,'records')),list(body['records'].items()))
        self.assertEqual(analysis_payload.occurrence(packed,2),(body['hits'][2],body['records']))
        reversed_payload=analysis.pack(dict(records=body['records'],hits=body['hits']))
        self.assertEqual(analysis_payload.occurrence(reversed_payload,0),(body['hits'][0],body['records']))
        with self.assertRaisesRegex(ValueError,'有效例证'):analysis_payload.occurrence(packed,3)

    def test_unselected_cards_are_validated_and_only_selected_cards_are_retained(self):
        cards={str(i):dict(body=dict(words=[dict(form=str(i),gloss='X')]),notes='n'*1000) for i in range(300)}
        value=dict(hits=[],records=cards,languages=[dict(name='保留')]);payload=analysis.pack(value)
        result=analysis_payload.read(payload,record_ids={'2','299'})
        self.assertEqual(dict(result['records']),{k:cards[k] for k in ('2','299')})
        self.assertEqual(result['records'].total,300);self.assertEqual(result['languages'],value['languages'])
        for source in ('{"hits":[],"records":{"x":{"a":1 "b":2}}}', '{"hits":[],"records":{"x":falsexxx}}','{"hits":[],"records":{}} garbage'):
            packed=base64.b64encode(zlib.compress(source.encode())).decode()
            with self.assertRaises((ValueError,json.JSONDecodeError)):analysis_payload.read(packed)
        with self.assertRaises(zlib.error):analysis_payload.read(payload[:-12])

    def test_repeated_dimensions_are_shared_only_inside_one_read(self):
        value=dict(hits=[dict(entry_id='a',word=i,dimensions={'tag':['GEN'],'text':['t']}) for i in range(100)])
        payload=analysis.pack(value);a=analysis_payload.read(payload);b=analysis_payload.read(payload)
        self.assertEqual(a,value);self.assertEqual(b,value)
        self.assertIs(a['hits'][0]['dimensions'],a['hits'][-1]['dimensions'])
        a['hits'][0]['dimensions']['tag'].append('local')
        self.assertEqual(b,value)
        varied=dict(hits=[dict(dimensions={'value':[v]}) for v in (1,1.0,True,'1',None,{'nested':['x']})])
        decoded=analysis_payload.read(analysis.pack(varied))
        self.assertEqual(json.dumps(decoded),json.dumps(varied))


class ScalarEvidenceTests(unittest.TestCase):
    setUp=test_evidence_index.EvidenceIntegrationTests.setUp
    tearDown=test_evidence_index.EvidenceIntegrationTests.tearDown
    rows=test_evidence_index.EvidenceIntegrationTests.rows
    compare=test_evidence_index.EvidenceIntegrationTests.compare

    def test_scalar_tuple_cache_keeps_field_presence_types_unicode_and_nul_boundaries(self):
        with server.connect(audit=False) as db:
            db.execute("INSERT INTO lexemes VALUES('target','ordos','entry','{}',1)")
            words=[dict(form='é',gloss='A\x00B'),dict(form='é\x00A',gloss='B'),
                dict(form='é',gloss='A\x00B',form_kind='content',gloss_kind='content'),
                dict(form='x',gloss='Y',form_kind=True,gloss_kind=1),dict(form='x',gloss='Y',form_kind='True',gloss_kind='1')]
            body=dict(words=words,targets=[dict(lexeme_id='target')])
            db.execute("INSERT INTO dictionary_examples VALUES('ex','ordos',?,1)",(json.dumps(body),))
            for query in ('é','é\x00A','A\x00B','B','content','是','True','1','missing'):
                for case in (True,False):self.compare(db,query,case)


class ReadMemoryIntegrationTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','word','link','undo','execute','page'):
        locals()[name]=getattr(test_analysis_workspace.AnalysisTests,name)

    def test_snapshot_paging_context_order_value_sort_and_drill_match_live_then_stay_frozen(self):
        self.seed('\n'.join('#pass([], (([left'+str(i%7)+'],[L]),([target],[T]),([right'+str(i%5)+'],[R])), [])' for i in range(67)))
        run=self.execute('form','target')
        code,snap=self.call('/api/analysis-save',dict(kind='snapshot',name='固定',run_id=run['id']));self.assertEqual(code,200,snap)
        for sort in ('source','left','right','value'):
            for page in (1,2,99):
                live=self.page(run,sort=sort,page=page,dimension='tag');frozen=self.page(snap,sort=sort,page=page,dimension='tag',snapshot='true')
                for key in ('items','total','page','pages','frequencies','frequency_pages','frequency_total'):self.assertEqual(frozen[key],live[key],(sort,page,key))
        live=self.page(run,dimension='value',value='target');frozen=self.page(snap,dimension='value',value='target',snapshot='true')
        self.assertEqual(live['items'],frozen['items'])
        entry=self.entries()[0];entry['words'][0]['form']='ZZZ';entry.setdefault('notes','')
        code,value=self.call('/api/save',entry);self.assertEqual(code,200,value)
        with patch.object(analysis,'materialize',side_effect=AssertionError('frozen cards read live data')):
            self.assertEqual(self.page(snap,snapshot='true',sort='right')['total'],67)

    def test_full_file_export_matches_existing_api_for_live_frozen_and_counts(self):
        self.seed('\n'.join('#pass([ipa], (([é],[N]),([x],[GEN])), [翻译])' for _ in range(3)))
        run=self.execute('form','')
        code,snap=self.call('/api/analysis-save',dict(kind='snapshot',name='固定',run_id=run['id']));self.assertEqual(code,200,snap)
        code,counts=self.call('/api/analysis-run',dict(query=dict(kind='counts')));self.assertEqual(code,200,counts)
        for item,frozen in ((run,False),(snap,True),(counts,False)):
            with server.connect(audit=False) as db:
                db.execute('BEGIN');args=dict(id=item['id'],snapshot=str(frozen).lower())
                expected=analysis.export_result(db,'ordos',args);file=analysis.export_file(db,server.DB,'ordos',args)
                path=language_exchange.staged(server.DB,file['token'],'analysis-json')
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')),expected)
                self.assertEqual(path.stat().st_size,file['size'])
                with self.assertRaises(ValueError):language_exchange.staged(server.DB,file['token'],'language-json')
                with self.assertRaises(ValueError):language_exchange.staged(Path(server.DB).with_name('another.sqlite3'),file['token'],'analysis-json')

    def test_stream_export_cancellation_cleans_partial_file_and_task_retry_succeeds(self):
        self.seed('#pass([], (([x],[N]),), [])');run=self.execute('form','')
        original=analysis.materialized_items;before=set(Path(language_exchange.STAGING.name).iterdir())
        def interrupted(*args,**kwargs):
            for card in original(*args,**kwargs):
                yield card
                raise long_tasks.Cancelled('cancelled')
        with server.connect(audit=False) as db,patch.object(analysis,'materialized_items',interrupted):
            with self.assertRaises(long_tasks.Cancelled):analysis.export_file(db,server.DB,'ordos',dict(id=run['id']))
        self.assertEqual(set(Path(language_exchange.STAGING.name).iterdir()),before)
        jid=long_tasks.submit(server.DB,'analysis-export',dict(language='ordos',id=run['id']))
        long_tasks.JOBS[jid]['future'].result(timeout=15);state=long_tasks.view(server.DB,jid)
        self.assertEqual(state['state'],'done',state)
        self.assertTrue(language_exchange.staged(server.DB,state['result']['token'],'analysis-json').exists())

    def test_staged_download_preserves_json_bytes_and_original_dated_filename(self):
        self.seed('#pass([], (([é],[汉字]),), [])');run=self.execute('form','')
        with server.connect(audit=False) as db:file=analysis.export_file(db,server.DB,'ordos',dict(id=run['id']))
        path=language_exchange.staged(server.DB,file['token'],'analysis-json');headers={};status=[]
        handler=object.__new__(server.Handler);handler.path='/api/task-download?kind=analysis-json&token='+file['token']+'&name=Corporium-analysis-2026-10-22.json'
        handler.wfile=io.BytesIO();handler.send_response=status.append;handler.send_header=lambda k,v:headers.update({k:v});handler.end_headers=lambda:None
        handler.get();self.assertEqual(status,[200]);self.assertEqual(handler.wfile.getvalue(),path.read_bytes())
        self.assertEqual(headers['Content-Type'],'application/json');self.assertEqual(headers['Content-Length'],str(path.stat().st_size))
        self.assertIn('Corporium-analysis-2026-10-22.json',headers['Content-Disposition'])

    def test_bulk_auto_matching_reuses_comparisons_and_batches_units_without_changing_occurrences(self):
        self.seed('\n'.join('#pass([], (([home],[家]),), [])' for _ in range(205)));self.word()
        with server.connect(audit=False) as db:
            statements=[];db.set_trace_callback(statements.append)
            with patch.object(lexicon,'auto_gloss_key',wraps=lexicon.auto_gloss_key) as gloss_key:plan=lexicon.auto_link_plan(db,'ordos')
        self.assertEqual(len(plan['matches']),205);self.assertEqual(len({m['unit_id'] for m in plan['matches']}),205)
        expected=hashlib.sha256(json.dumps({k:v for k,v in plan.items() if k!='token'},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(plan['token'],expected)
        # Four registered forms/meanings plus one repeated source pair.
        self.assertEqual(gloss_key.call_count,5)
        unit_reads=[s for s in statements if 'SELECT u.id,u.entry_id,u.revision,u.kind' in s]
        self.assertEqual(len(unit_reads),2)

    def test_empty_all_box_with_local_conditions_skips_external_evidence_only_when_unused(self):
        entry=self.seed('#pass([], (([home],[家]),), [])');word=self.word();self.link(entry['words'][0]['unit_id'],word)
        spec=dict(field='all',conditions=[dict(field='usages.senses.short_gloss',op='contains',value='家')])
        with server.connect(audit=False) as db:
            with patch.object(gloss_inheritance,'load',side_effect=AssertionError('local predicates rendered sentences')):
                result=lexicon.list_lexemes(db,'ordos',search=spec)
            self.assertEqual([r['id'] for r in result['items']],[word['id']])
            # A nonempty all-field term must still inspect evidence, even with
            # the same local condition; selecting an evidence field must also
            # retain its original dynamic-field validation.
            import dictionary_search
            self.assertTrue(dictionary_search.needs_examples(spec,'in evidence'))
            self.assertTrue(dictionary_search.needs_examples({**spec,'field':'examples.custom.title'},''))
            self.assertTrue(dictionary_search.needs_examples({**spec,'class_id':'category'},''))
