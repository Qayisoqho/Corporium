import json
import unittest
from pathlib import Path
import test_component_links
import test_lexicon
import server
from restore_backup import restore


class MorphemeRegistryTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo
    fixture=test_component_links.ComponentLinkTests.fixture
    link=test_component_links.ComponentLinkTests.link

    def assign(self,x,**extra):
        b=dict(lexeme_id=x['id'],lexeme_revision=x['revision'],components=[dict(analysis_id='a',component_id='c',revision=0)],create=dict(form='home',body={'gloss':'家'}))
        b.update(extra)
        return self.call('/api/morpheme-assign',b)

    def test_save_plan_atomic_homonyms_and_counts(self):
        e,x=self.fixture()
        plan=self.call('/api/morpheme-save-preview',x)[1]
        code,saved=self.call('/api/lexeme-save',{**x,'morpheme_confirmation':plan['token']})
        self.assertEqual(code,200,saved)
        self.assertEqual(self.call('/api/dictionary-counts')[1],{'lexemes':1,'morphemes':2})
        links=self.call('/api/morpheme-components?id='+x['id'])[1]['items']
        self.assertEqual({i['link']['morpheme']['body']['gloss'] for i in links},{'家','另一解释'})
        for item in links:
            target=self.call('/api/morpheme?id='+item['link']['morpheme_id'])[1]
            self.assertTrue(any(c['lexeme_id']==saved['id'] and c['component_id']==item['component']['id'] for c in target['components']))
            self.assertFalse(item['link']['review'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/dictionary-counts')[1]['morphemes'],0)
        peer=self.call('/api/morpheme-save',{'form':'home','body':{'gloss':'同形'}})[1]
        x=self.call('/api/lexeme?id='+x['id'])[1]
        plan=self.call('/api/morpheme-save-preview',x)[1]
        self.assertEqual(self.call('/api/lexeme-save',{**x,'morpheme_confirmation':plan['token']})[0],400)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['revision'],x['revision'])
        choices=[{'analysis_id':i['analysis_id'],'component_id':i['component_id'],'morpheme_id':peer['id'] if n==0 else None} for n,i in enumerate(plan['items'])]
        code,saved=self.call('/api/lexeme-save',{**x,'morpheme_confirmation':plan['token'],'morpheme_choices':choices})
        self.assertEqual(code,200,saved)
        self.assertEqual(self.call('/api/dictionary-counts')[1]['morphemes'],2)

    def test_audit_component_review_and_pending_registry(self):
        e,x=self.fixture();self.assertEqual(self.link(e,x)[0],200)
        x['body']['word_structure']['analyses'][0]['components'][0]['gloss']='changed'
        x=self.call('/api/lexeme-save',x)[1]
        data=self.call('/api/grammar-audit?issue=pending')[1]
        self.assertTrue(any('组分' in i['message'] for i in data['items']),data)
        self.assertEqual(self.assign(x)[0],200)
        data=self.call('/api/grammar-audit?issue=pending')[1]
        self.assertTrue(any('组分已变化' in i['message'] for i in data['items']),data)
        self.assertFalse(any('尚未确认' in i['message'] or '待定' in i['message'] for i in data['items']))

    def test_independent_whole_word_link_and_last_unlink(self):
        _,x=self.fixture()
        code,e=self.call('/api/example-save',{'body':{'words':[{'form':'home','gloss':'家'}],'targets':[]}})
        self.assertEqual(code,200,e)
        d=self.call('/api/segmentation?kind=independent&id='+e['id'])[1]
        payload=dict(kind='independent',id=e['id'],revision=d['revision'],word=0,key='@word',lexeme_id=x['id'],lexeme_revision=x['revision'],status='pending',notes='check')
        self.assertEqual(self.call('/api/segmentation-link',payload)[0],200)
        d=self.call('/api/segmentation?kind=independent&id='+e['id'])[1]
        self.assertEqual(d['body']['targets'][0]['notes'],'check')
        self.assertEqual(self.call('/api/segmentation-link',dict(kind='independent',id=e['id'],revision=d['revision'],remove_target=0))[0],200)
        self.assertEqual(self.call('/api/segmentation?kind=independent&id='+e['id'])[1]['body']['targets'],[])

    def test_auto_save_metadata_and_stale_plan(self):
        _,x=self.fixture()
        c=x['body']['word_structure']['analyses'][0]['components'][0]
        c.update(notes='研究笔记',source='田野资料',segments=['ho','me'],role='root')
        plan=self.call('/api/morpheme-save-preview',x)[1]
        self.call('/api/morpheme-save',{'form':'home','body':{'gloss':'插入的同形语素'}})
        self.assertEqual(self.call('/api/lexeme-save',{**x,'morpheme_confirmation':plan['token']})[0],400)
        plan=self.call('/api/morpheme-save-preview',x)[1]
        choices=[dict(analysis_id=i['analysis_id'],component_id=i['component_id'],morpheme_id=None) for i in plan['items']]
        self.assertEqual(self.call('/api/lexeme-save',{**x,'morpheme_confirmation':plan['token'],'morpheme_choices':choices})[0],200)
        item=self.call('/api/morpheme-components?id='+x['id'])[1]['items'][0]
        data=item['link']['morpheme']['body']
        self.assertEqual((data['notes'],data['source'],data['segments']),('研究笔记','田野资料',['ho','me']))

    def test_pending_batch_existing_homonyms_and_cross_language(self):
        _,x=self.fixture()
        code,r=self.assign(x,components=[dict(analysis_id='a',component_id='c'),dict(analysis_id='b',component_id='d')]);self.assertEqual(code,200,r)
        m=self.call('/api/morpheme?id='+r['morpheme_id'])[1]
        self.assertNotIn('status',m['body']);self.assertEqual(len(m['components']),2)
        other=self.call('/api/morpheme-save',{'form':'home','body':{}})[1]
        self.assertEqual((m['number'],other['number']),(1,2))
        self.assertEqual(self.call('/api/morphemes?status=pending')[1]['total'],2)
        lid=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id']
        foreign=self.call('/api/morpheme-save',{'form':'home','body':{},'_language':lid})[1]
        self.assertEqual(foreign['number'],1)
        self.assertEqual(self.assign(x,create=None,morpheme_id=foreign['id'],morpheme_revision=foreign['revision'])[0],400)
        self.assertEqual(self.call('/api/morpheme-delete',{'id':m['id'],'revision':m['revision']})[0],400)

    def test_review_existing_sentence_link_unchanged_and_atomic_rejection(self):
        e,x=self.fixture();self.assertEqual(self.link(e,x)[0],200)
        uid=e['words'][0]['morphemes'][0]['unit_id'];before=self.call('/api/unit-dictionary?id='+uid)[1]['link']
        code,r=self.assign(x);self.assertEqual(code,200,r)
        self.assertEqual(before,self.call('/api/unit-dictionary?id='+uid)[1]['link'])
        x['body']['word_structure']['analyses'][0]['components'][0]['gloss']='changed'
        x=self.call('/api/lexeme-save',x)[1]
        m=self.call('/api/morpheme?id='+r['morpheme_id'])[1];self.assertFalse(m['components'][0]['review']);self.assertFalse(m['components'][0]['source_missing']);self.assertEqual(m['components'][0]['body']['snapshot']['component']['gloss'],'changed')
        code,_=self.assign(x,components=[dict(analysis_id='b',component_id='d'),dict(analysis_id='missing',component_id='c')]);self.assertEqual(code,400)
        self.assertEqual(self.call('/api/morphemes')[1]['total'],1)
        self.assertEqual(self.assign(x)[0],400) # stale assignment revision
        c=m['components'][0]
        self.assertEqual(self.assign(x,create=None,morpheme_id=m['id'],morpheme_revision=m['revision'],components=[dict(analysis_id='a',component_id='c',revision=c['revision'])],status='confirmed')[0],200)
        self.assertFalse(self.call('/api/morpheme?id='+m['id'])[1]['components'][0]['review'])

    def test_live_registry_evidence_tracks_edits_without_a_review_workflow(self):
        _,x=self.fixture();r=self.assign(x)[1]
        x['headword']='changed headword';analysis=x['body']['word_structure']['analyses'][0]
        analysis['title']='新分析名称';analysis['notes']='分析备注'
        analysis['components'][0].update(form='updated',readings=['up'],gloss='新释义',notes='新组分备注')
        code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x)
        current=self.call('/api/morpheme?id='+r['morpheme_id'])[1]['components'][0]
        self.assertFalse(current['review']);self.assertFalse(current['source_missing'])
        self.assertEqual(current['body']['snapshot']['component']['form'],'updated')
        self.assertEqual(current['body']['snapshot']['analysis']['title'],'新分析名称')
        with server.connect() as db:
            stored=json.loads(db.execute('SELECT body FROM morpheme_components WHERE id=?',(current['id'],)).fetchone()[0])
        self.assertEqual(stored['snapshot']['component']['form'],'home')
        self.assertEqual(self.undo()[0],200)
        reverted=self.call('/api/morpheme?id='+r['morpheme_id'])[1]['components'][0]
        self.assertFalse(reverted['review']);self.assertEqual(reverted['body']['snapshot']['component']['form'],'home')

    def test_merge_undo_preserves_evidence_and_source_metadata(self):
        _,x=self.fixture();r=self.assign(x)[1];a=self.call('/api/morpheme?id='+r['morpheme_id'])[1]
        b=self.call('/api/morpheme-save',{'form':'home','body':{'gloss':'住所','status':'confirmed'}})[1]
        payload=dict(id=a['id'],revision=a['revision'],target_id=b['id'],target_revision=b['revision'],confirmed=True)
        code,result=self.call('/api/morpheme-merge',payload);self.assertEqual(code,200,result)
        m=self.call('/api/morpheme?id='+b['id'])[1];self.assertEqual(len(m['components']),1);self.assertEqual(m['body']['gloss'],'住所');self.assertEqual(m['body']['merged_records'][0]['body']['gloss'],'家')
        self.assertEqual(self.call('/api/morpheme?id='+a['id'])[0],400)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.call('/api/morphemes')[1]['total'],2)
        self.assertEqual(len(self.call('/api/morpheme?id='+a['id'])[1]['components']),1)
        self.assertEqual(self.undo('redo')[0],200)
        c=self.call('/api/morpheme?id='+b['id'])[1]['components'][0]
        self.assertEqual(self.call('/api/morpheme-unassign',{'id':c['id'],'revision':c['revision']})[0],200)
        m=self.call('/api/morpheme?id='+b['id'])[1]
        self.assertEqual(self.call('/api/morpheme-delete',{'id':m['id'],'revision':m['revision']})[0],200)

    def test_exchange_backup_and_deleted_components(self):
        _,x=self.fixture();r=self.assign(x)[1]
        x['body']['word_structure']['analyses']=[];self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',{'name':'Copy','metadata':{}})[1]['id']
        code,result=self.call('/api/import-language',{'_language':other,'bundle':bundle});self.assertEqual(code,200,result)
        listing=self.call('/api/morphemes?language='+other)[1];self.assertEqual(listing['total'],1)
        mid=listing['items'][0]['id'];self.assertNotEqual(mid,r['morpheme_id'])
        m=self.call('/api/morpheme?id='+mid+'&language='+other)[1];self.assertFalse(m['components'][0]['review']);self.assertTrue(m['components'][0]['source_missing'])
        backup=self.call('/api/backup')[1];src=Path(self.temp.name)/'backup.json';src.write_text(json.dumps(backup),encoding='utf-8');dest=Path(self.temp.name)/'restored.sqlite3';restore(src,dest)
        import sqlite3
        db=sqlite3.connect(dest)
        try:self.assertEqual(db.execute('SELECT count(*) FROM morpheme_components').fetchone()[0],2)
        finally:db.close()

    def test_stale_merge_and_invalid_state(self):
        a=self.call('/api/morpheme-save',{'form':'a','body':{}})[1];b=self.call('/api/morpheme-save',{'form':'b','body':{}})[1]
        self.assertEqual(self.call('/api/morpheme-save',{**a,'body':{'status':'bad'}})[0],200)
        self.assertEqual(self.call('/api/morpheme-merge',dict(id=a['id'],revision=0,target_id=b['id'],target_revision=b['revision'],confirmed=True))[0],400)
        self.assertEqual(self.call('/api/morphemes')[1]['total'],2)

    def test_assignment_invalidates_merge_revision_and_referenced_language_change(self):
        _,x=self.fixture();a=self.call('/api/morpheme-save',{'form':'a','body':{}})[1];b=self.call('/api/morpheme-save',{'form':'b','body':{}})[1]
        self.assertEqual(self.assign(x,create=None,morpheme_id=a['id'],morpheme_revision=a['revision'])[0],200)
        self.assertEqual(self.call('/api/morpheme-merge',dict(id=a['id'],revision=a['revision'],target_id=b['id'],target_revision=b['revision'],confirmed=True))[0],400)
        self.assertEqual(self.call('/api/lexeme-delete',{'id':x['id'],'revision':x['revision']})[0],400)
        m=self.call('/api/morpheme?id='+a['id'])[1]
        self.assertEqual(m['revision'],a['revision']+1)
        bundle=self.call('/api/export-language?language=ordos')[1]
        lid=self.call('/api/save-language',{'name':'Copies','metadata':{}})[1]['id']
        self.assertEqual(self.call('/api/import-language',{'_language':lid,'bundle':bundle})[0],200)
        imported=self.call('/api/morphemes?language='+lid)[1]['items']
        self.assertEqual({(m['form'],m['number']) for m in imported},{('a',1),('b',1)})
