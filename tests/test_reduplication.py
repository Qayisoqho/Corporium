import copy
import json
import unittest
from pathlib import Path
import corpus
import reduplication as red
import server
import test_segmentation
import test_inline_slots


class ReduplicationTests(unittest.TestCase):
    setUp=test_segmentation.SegmentationTests.setUp
    tearDown=test_segmentation.SegmentationTests.tearDown
    call=test_segmentation.SegmentationTests.call
    seed=test_segmentation.SegmentationTests.seed
    entries=test_segmentation.SegmentationTests.entries
    get=test_segmentation.SegmentationTests.get
    undo=test_segmentation.SegmentationTests.undo

    def draft(self,kind,e):
        d=self.call('/api/annotations?kind='+kind+'&id='+e['id'])[1]
        return dict(kind=kind,id=e['id'],revision=d['revision'],before=copy.deepcopy(d['cells']),layers=d['layers'],cells=d['cells'],body=d['body'],slot_ids=[w['id'] for w in d['words']])

    def example(self,kind='corpus',form='je~jepasu',gloss='RED~go'):
        if kind=='corpus':return self.seed('#pass([ipa], ((['+form+'],['+gloss+']),([x],[x])), [translation])')
        code,e=self.call('/api/example-save',dict(body=dict(ipa='ipa',translation='translation',words=[dict(form=form,gloss=gloss),dict(form='x',gloss='x')],targets=[])))
        self.assertEqual(code,200,e);return e

    def save(self,e,kind='corpus',**extra):
        d=self.get(e,kind)
        p=dict(kind=kind,id=e['id'],revision=d['revision'],action='redup-save',source=dict(word=0,key='r:0:host'),base=dict(word=0,key='r:1:host'),type='partial',notes='首音节重叠')
        p.update(extra);code,result=self.call('/api/segmentation-save',p);self.assertEqual(code,200,result)
        return self.get(e,kind)

    def test_boundaries_candidates_blank_gloss_and_no_automatic_link(self):
        for form,gloss in [('je~jepasu','RED~go'),('b<um>i~bili','<ACTFOC>IPFV~buy'),('go~go-s','RED~go-PL')]:
            b=corpus.analyze(dict(ipa='',translation='',words=[dict(form=form,gloss=gloss)]))
            self.assertFalse(b['warnings']);self.assertTrue(b['reduplication_info']['candidates']);self.assertNotIn('reduplications',b)
        e=self.example(gloss='');d=self.get(e)
        p=red.preview(dict(body=d['body'],action='redup-save',source=dict(word=0,key='r:0:host'),base=dict(word=0,key='r:1:host'),type='partial'))
        self.assertEqual(p['body']['words'][0]['gloss'],'');self.assertFalse(p['info']['relations'][0]['review'])
        self.assertIn('jepasu',[v['form'] for v in p['options']])

    def test_both_sources_save_reorder_edit_merge_and_undo(self):
        for kind in ('corpus','independent'):
            e=self.example(kind);d=self.save(e,kind);rel=d['body']['reduplications'][0]
            draft=self.draft(kind,e);draft['slot_ids'].reverse();draft['body']['words'].reverse()
            self.assertEqual(self.call('/api/inline-save',draft)[0],200)
            b=self.get(e,kind)['body'];self.assertEqual(b['reduplications'][0],rel);self.assertEqual(b['reduplication_info']['relations'][0]['source_word'],1)
            draft=self.draft(kind,e);draft['body']['words'][1]['gloss']='ITER~go'
            self.assertEqual(self.call('/api/inline-save',draft)[0],200);self.assertFalse(self.get(e,kind)['body']['reduplication_info']['relations'][0]['review'])
            draft=self.draft(kind,e);draft['body']['words'][0]['form']+=draft['body']['words'][1]['form'];draft['body']['words'][0]['gloss']+=draft['body']['words'][1]['gloss'];draft['body']['words'].pop();draft['slot_ids'].pop();draft['delete_confirmed']=True
            self.assertEqual(self.call('/api/inline-save',draft)[0],200)
            b=self.get(e,kind)['body'];self.assertEqual(b['reduplications'][0],rel);self.assertTrue(b['reduplication_info']['relations'][0]['review'])
            self.assertEqual(self.undo()[0],200);self.assertFalse(self.get(e,kind)['body']['reduplication_info']['relations'][0]['review'])

    def test_draft_save_cancel_delete_stale_and_bad_slot_identity(self):
        e=self.example();draft=self.draft('corpus',e)
        p=red.preview(dict(body=draft['body'],action='redup-save',source=dict(word=0,key='r:0:host'),base=dict(word=1,key='@word'),type='partial'))
        self.assertFalse(self.get(e)['body'].get('reduplications'))
        draft['body']=p['body'];self.assertEqual(self.call('/api/inline-save',draft)[0],200)
        self.assertEqual(self.call('/api/inline-save',draft)[0],400)
        d=self.get(e);rel=d['body']['reduplications'][0]
        bad=self.draft('corpus',e);bad['body']['words'][0]['redup_id']=bad['body']['words'][1]['redup_id'];self.assertEqual(self.call('/api/inline-save',bad)[0],400)
        code,r=self.call('/api/segmentation-save',dict(kind='corpus',id=e['id'],revision=d['revision'],action='redup-delete',relation_id=rel['id']))
        self.assertEqual(code,200,r);self.assertFalse(self.get(e)['body']['reduplications']);self.assertEqual(self.undo()[0],200)

    def test_cycle_overlap_duplicate_and_same_spelling(self):
        b=corpus.analyze(dict(ipa='',translation='',words=[dict(form='go',gloss='go') for _ in range(3)]))
        red.apply(b,dict(source=dict(word=0,key='@word'),base=dict(word=1,key='@word'),type='full'))
        valid=copy.deepcopy(b)
        for source,base in [(0,0),(1,0),(0,2)]:
            with self.assertRaises(ValueError):red.apply(copy.deepcopy(valid),dict(source=dict(word=source,key='@word'),base=dict(word=base,key='@word'),type='full'))
        red.apply(b,dict(source=dict(word=2,key='@word'),base=dict(word=1,key='@word'),type='full'))
        self.assertEqual(len(red.describe(b)['relations']),2)
        b['words'].reverse();self.assertEqual(red.describe(b)['relations'][0]['source_word'],2)

    def test_full_editor_preserves_or_reviews_without_guessing(self):
        e=self.example();self.save(e)
        d=self.entries()[0];d['translation']='changed';d['notes']=''
        self.assertEqual(self.call('/api/save',d)[0],200);self.assertFalse(self.get(e)['body']['reduplication_info']['relations'][0]['review'])
        d=self.entries()[0];d['words'][0]['form']='ja~jepasu';d['notes']=''
        self.assertEqual(self.call('/api/save',d)[0],200);self.assertTrue(self.get(e)['body']['reduplication_info']['relations'][0]['review'])

    def test_copy_sentence_and_word_subset(self):
        e=self.example();d=self.save(e);old=d['body']
        code,r=self.call('/api/duplicate-entry',dict(id=e['id'],text_id=e['text_id'],revision=d['revision'],order=[e['id']],where='end'))
        self.assertEqual(code,200,r);copied=self.get(r)['body']
        self.assertNotEqual(old['reduplications'][0]['source']['word_id'],copied['reduplications'][0]['source']['word_id']);self.assertFalse(copied['reduplication_info']['relations'][0]['review'])
        words=copy.deepcopy(old['words'][:1]);target=dict(words=[])
        red.transfer(old,words,target);target['words']=words
        self.assertFalse(red.describe(target)['relations'][0]['review'])
        cross=copy.deepcopy(old);red.apply(cross,dict(relation_id=cross['reduplications'][0]['id'],source=dict(word=0,key='r:0:host'),base=dict(word=1,key='@word'),type='partial'))
        words=copy.deepcopy(cross['words'][:1]);target=dict(words=[]);red.transfer(cross,words,target);target['words']=words
        self.assertTrue(red.describe(target)['relations'][0]['review'])

    def test_search_analysis_typst_excel_exchange_and_backup(self):
        import analysis_workspace,excel_exchange,base64,io
        from restore_backup import restore
        e=self.example();self.save(e,type='modified');ind=self.example('independent');self.save(ind,'independent',type='modified')
        for kind,row in [('corpus',e),('independent',ind)]:
            self.assertEqual(self.get(row,kind)['body']['reduplications'][0]['type'],'modified')
        for source in ('/api/entries?','/api/example-library?source=independent&'):
            code,res=self.call(source+'field=reduplication&q=jepasu');self.assertEqual(code,200,res);self.assertTrue(res['items'])
        with server.connect(audit=False) as db:
            q=analysis_workspace.normalize(dict(scope={'source':'all'},conditions=[dict(field='reduplication',value='jepasu')]))
            result=analysis_workspace.calculate(db,'ordos',q)
            self.assertEqual(len(result['hits']),2)
            x=excel_exchange.export(db,dict(ids=[e['text_id']]),'ordos');sheets=excel_exchange.read(io.BytesIO(base64.b64decode(x['data'])))
            self.assertIn('Reduplication',sheets[0]['rows'][1].values())
        text=self.call('/api/export?id='+e['text_id'])[1];parsed,errors=corpus.parse(text);self.assertFalse(errors);self.assertFalse(parsed[0]['reduplication_info']['relations'][0]['review'])
        self.assertEqual(parsed[0]['reduplications'][0]['type'],'modified')
        bundle=self.call('/api/export-language?language=ordos')[1];lid=self.call('/api/save-language',dict(name='Copied',metadata={}))[1]['id']
        code,r=self.call('/api/import-language',dict(bundle=bundle,_language=lid));self.assertEqual(code,200,r)
        rows=self.call('/api/entries?language='+lid)[1]['items'];self.assertFalse(rows[0]['reduplication_info']['relations'][0]['review'])
        self.assertEqual(rows[0]['reduplications'][0]['type'],'modified')
        file=server.DB.parent/'backup.json';file.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8');out=server.DB.parent/'restored.sqlite3';restore(file,out);server.DB=out
        self.assertFalse(self.get(e)['body']['reduplication_info']['relations'][0]['review'])
        self.assertEqual(self.get(e)['body']['reduplications'][0]['type'],'modified')

    def test_suffix_and_combined_stem_and_changed_group(self):
        b=corpus.analyze(dict(ipa='',translation='',words=[dict(form='root-suf~suf',gloss='root-SUF~RED')]))
        red.apply(b,dict(source=dict(word=0,key='r:2:host'),base=dict(word=0,key='r:1:host'),type='partial'))
        self.assertFalse(red.describe(b)['relations'][0]['review'])
        w=b['words'][0];w['morph_groups']=[dict(id='stem',type='stem',members=['r:0:host','r:1:host'],gloss='stem',snapshot={k:w[k] for k in ('form','gloss')})];corpus.analyze(b)
        red.apply(b,dict(relation_id=b['reduplications'][0]['id'],source=dict(word=0,key='r:2:host'),base=dict(word=0,key='group:stem'),type='partial'))
        self.assertFalse(red.describe(b)['relations'][0]['review']);w['morph_groups']=[];corpus.analyze(b);self.assertTrue(red.describe(b)['relations'][0]['review'])

    def test_transfer_api_across_sources_and_partial_move(self):
        import test_exchange_transfer
        e=self.example();self.save(e);ind=self.example('independent')
        snap=lambda kind,x:self.call('/api/word-transfer-snapshot?kind='+kind+'&id='+x['id'])[1]
        a=snap('corpus',e);b=snap('independent',ind)
        p=test_exchange_transfer.ExchangeTransferTests.payload(self,a,b,'copy')
        code,r=self.call('/api/word-transfer',p);self.assertEqual(code,200,r)
        d=self.get(ind,'independent');self.assertFalse(d['body']['reduplication_info']['relations'][0]['review'])
        self.assertNotEqual(d['body']['reduplications'][0]['source']['word_id'],a['body']['reduplications'][0]['source']['word_id'])
        # Move just one side of a cross-slot relation within the text.
        self.save(e,relation_id=a['body']['reduplications'][0]['id'],base=dict(word=1,key='@word'))
        target=self.call('/api/add',dict(text_id=e['text_id']))[1]
        a=snap('corpus',e);b=snap('corpus',target)
        p=test_exchange_transfer.ExchangeTransferTests.payload(self,a,b,'move')
        code,r=self.call('/api/word-transfer',p);self.assertEqual(code,200,r)
        for row in (e,target):self.assertTrue(self.get(row)['body']['reduplication_info']['relations'][0]['review'])
        self.assertEqual(self.undo()[0],200);self.assertFalse(self.get(e)['body']['reduplication_info']['relations'][0]['review'])

    def test_old_tilde_link_is_retained_never_redirected_to_new_segment(self):
        from unittest.mock import patch
        import segmentation
        splitter=segmentation.split_parts
        def old_split(value,*args):
            marker='\ue000';return [(p.replace(marker,'~'),offset,b) for p,offset,b in splitter(value.replace('~',marker))]
        with patch.object(segmentation,'split_parts',old_split):
            e=self.example();d=self.get(e)
            code,x=self.call('/api/lexeme-save',dict(headword='je~jepasu',body={'usages':[{'pos':'V','senses':[{'short_gloss':'RED~go'}]}]}));self.assertEqual(code,200,x)
            p=dict(kind='corpus',id=e['id'],revision=d['revision'],word=0,key='0:host',lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=x['body']['usages'][0]['id'],sense_id=x['body']['usages'][0]['senses'][0]['id'])
            self.assertEqual(self.call('/api/segmentation-link',p)[0],200)
            with server.connect(audit=False) as db:
                old_body=db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0]
                link=dict(db.execute('SELECT * FROM lexical_links').fetchone());db.execute('PRAGMA user_version=3');db.commit()
        server.init()
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0],old_body)
            self.assertEqual(dict(db.execute('SELECT * FROM lexical_links WHERE id=?',(link['id'],)).fetchone()),link)
            self.assertEqual(db.execute('SELECT active FROM corpus_units WHERE id=?',(link['unit_id'],)).fetchone()[0],0)
        now=self.get(e)['body']['words'][0];self.assertEqual(now['gloss'],'RED~go');self.assertEqual([m['key'] for m in now['morphemes']],['r:0:host','r:1:host'])

    def test_excel_roundtrip_relation_and_repeated_base_events(self):
        import excel_exchange,base64
        e=self.example();self.save(e)
        with server.connect() as db:
            x=excel_exchange.export(db,dict(ids=[e['text_id']]),'ordos')
            inspected=excel_exchange.inspect(db,server.DB,dict(data=x['data']),'ordos')
            p=dict(token=inspected['token'],sheets=[dict(index=0,title='Roundtrip',start=2,sentence_column=1,slot_column=2,mappings=[dict(column=i,target=t) for i,t in [(3,'form'),(4,'gloss'),(5,'ipa'),(6,'translation'),(7,'notes'),(8,'reduplication')]])])
            plan,_=excel_exchange.plan(db,server.DB,p,'ordos');b=corpus.analyze(plan[0]['sentences'][0]['body']);self.assertFalse(b['reduplication_info']['relations'][0]['review'])
        b=corpus.analyze(dict(ipa='',translation='',words=[dict(form='go~go~go',gloss='RED~RED~go')]))
        for key in ('r:0:host','r:1:host'):red.apply(b,dict(source=dict(word=0,key=key),base=dict(word=0,key='r:2:host'),type='full'))
        self.assertEqual(red.values(b,0),['go','go'])

    def test_legacy_inherited_gloss_resolves_on_original_span(self):
        import gloss_inheritance
        w=dict(form='je~jepasu-n',gloss='RED~old-GEN')
        rows=[dict(unit_key='0:host',mode='inherit',pattern='[null]',meaning_gloss='RED~new')]
        result=gloss_inheritance.render_word(w,rows)
        self.assertEqual(result['gloss'],'RED~new-GEN');self.assertNotIn('_legacy_tilde',result)
        self.assertEqual([m['gloss'] for m in result['morphemes']],['RED','new','GEN'])

    def test_empty_base_query_filters_relations_and_shared_reference_reads(self):
        import grammar_survey,analysis_workspace
        e=self.example();self.save(e);self.seed('#pass([], (([other],[other]),), [])')
        code,r=self.call('/api/entries?field=reduplication');self.assertEqual(code,200,r);self.assertEqual(r['total'],1)
        code,r=self.call('/api/example-library?field=reduplication');self.assertEqual(code,200,r);self.assertEqual(r['total'],1)
        with server.connect(audit=False) as db:
            d=grammar_survey.reference(db,'corpus',e['id'],'ordos');self.assertFalse(d['body']['reduplication_info']['relations'][0]['review'])
            q=analysis_workspace.normalize(dict(scope={'source':'all'},conditions=[dict(field='reduplication',value='')]))
            self.assertEqual(len(analysis_workspace.calculate(db,'ordos',q)['hits']),1)
        d=self.draft('corpus',e);d['body']['words'][0]['form']='new~base';self.assertEqual(self.call('/api/inline-save',d)[0],200)
        self.assertEqual(self.call('/api/entries?field=reduplication')[1]['total'],0)

    def test_whole_relation_move_removes_source_copy_and_independent_copy_is_fresh(self):
        import test_exchange_transfer
        e=self.example();self.save(e);target=self.call('/api/add',dict(text_id=e['text_id']))[1]
        snap=lambda x:self.call('/api/word-transfer-snapshot?kind=corpus&id='+x['id'])[1]
        a=snap(e);b=snap(target);p=test_exchange_transfer.ExchangeTransferTests.payload(self,a,b,'move')
        code,r=self.call('/api/word-transfer',p);self.assertEqual(code,200,r)
        self.assertFalse(self.get(e)['body'].get('reduplications'));self.assertFalse(self.get(target)['body']['reduplication_info']['relations'][0]['review'])
        original=self.example('independent');self.save(original,'independent');d=self.get(original,'independent')
        code,copied=self.call('/api/example-save',dict(body=d['body']));self.assertEqual(code,200,copied)
        self.assertNotEqual(copied['body']['reduplications'][0]['source']['word_id'],d['body']['reduplications'][0]['source']['word_id'])
        self.assertFalse(self.get(copied,'independent')['body']['reduplication_info']['relations'][0]['review'])


if __name__=='__main__':unittest.main()
