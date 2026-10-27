import copy
import json
import unittest
from pathlib import Path

import server
import test_sentence_dictionary as sd
import language_exchange
import paradigms


def body():
    return dict(usages=[dict(id='verb',pos='动词',senses=[dict(id='go-meaning',short_gloss='去',definition='移动')])],
        variants=[dict(id='went',form='went'),dict(id='goes',form='goes')],
        paradigms=[dict(id='table',title='动词变形',usage_id='verb',dimensions=['时态','人称','数'],rows=[
            dict(id='past',labels=['过去','全部','全部'],state='filled',realizations=[dict(id='past-form',form_id='went',meanings=[dict(id='went-meaning',base_sense_id='go-meaning',short_gloss='去.PST',definition='过去的移动')])]),
            dict(id='present',labels=['现在','第三','单数'],state='filled',realizations=[dict(id='present-form',form_id='goes',meanings=[dict(id='goes-meaning',base_sense_id='go-meaning',short_gloss='去.PRS.3SG',definition='三单')])]),
            dict(id='missing',labels=['未定','无','无'],state='missing',realizations=[]),
            dict(id='unfilled',labels=['未定','未填','未填'],state='unfilled',realizations=[])])])


class ParadigmTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo','complete'):
        locals()[name]=getattr(sd.SentenceDictionaryTests,name)

    def entry(self):return self.api('lexeme-save',dict(headword='go',body=body()))
    def get(self,x):return self.api('lexeme?id='+x['id'])
    def change(self,x,label):
        x=self.get(x);x['body']['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['short_gloss']=label
        return self.api('lexeme-save',x)
    def link(self,src,x,sid='went-meaning',fid='went'):
        return self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',link_revision=0,
            lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id='verb',sense_id=sid,form_id=fid))
    def gloss(self,src):return self.detail(src)['body']['words'][0]['gloss']

    def test_normalization_identity_and_invalid_references(self):
        x=self.entry();self.assertEqual(len(x['body']['usages'][0]['senses']),1)
        self.assertEqual([s['id'] for u,s,f in paradigms.candidates(x['body'])],['go-meaning','went-meaning','goes-meaning'])
        self.assertEqual(x['body']['paradigms'][0]['rows'][2]['state'],'missing')
        for mutate in (
            lambda b:b['paradigms'][0].update(usage_id='absent'),
            lambda b:b['paradigms'][0]['rows'][0]['realizations'][0].update(form_id='absent'),
            lambda b:b['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0].update(base_sense_id='absent'),
            lambda b:b['paradigms'][0]['rows'][0].update(state='missing'),
            lambda b:b['paradigms'][0]['rows'][1]['realizations'][0]['meanings'][0].update(id='went-meaning')):
            b=body();mutate(b);status,r=self.call('/api/lexeme-save',dict(headword='bad',body=b));self.assertEqual(status,400,r)
        before=x['body']['paradigms'];x['body']['paradigms'][0]['rows'].reverse();x=self.api('lexeme-save',x)
        self.assertEqual(set(r['id'] for r in before[0]['rows']),set(r['id'] for r in x['body']['paradigms'][0]['rows']))

    def test_exact_auto_match_both_sources_keeps_form_and_no_base_cross_product(self):
        self.entry()
        for kind in ('corpus','independent'):self.source(kind,[('went','去.PST'),('goes','去.PRS.3SG'),('went','去'),('went','去.PRS.3SG')])
        p=self.api('lexeme-auto-preview?language=ordos');self.assertEqual(len(p['matches']),4)
        self.assertEqual({(m['form_id'],m['sense_id']) for m in p['matches']},{('went','went-meaning'),('goes','goes-meaning')})
        self.api('lexeme-auto-link',dict(token=p['token']));self.assertEqual(self.api('lexeme-auto-preview?language=ordos')['already_linked'],4)
        self.undo();self.assertEqual(len(self.api('lexeme-auto-preview?language=ordos')['matches']),4)
        self.undo(True)

    def test_missing_form_identifies_table_and_row_in_preview_and_save_without_writing(self):
        x=self.entry();before=copy.deepcopy(x)
        x['body']['variants']=[v for v in x['body']['variants'] if v['id']!='went']
        for path in ('morpheme-save-preview','lexeme-save'):
            status,result=self.call('/api/'+path,x)
            self.assertEqual(status,400,result)
            message=result['error']
            self.assertIn('动词变形',message)
            self.assertIn('过去 · 全部 · 全部',message)
            self.assertIn('重新选择或填写',message)
            self.assertEqual(self.get(before),before)

    def test_ambiguity_same_form_and_gloss_is_not_collapsed(self):
        x=self.entry();b=x['body'];duplicate=copy.deepcopy(b['paradigms'][0]['rows'][0]);duplicate['id']='past2';duplicate['realizations'][0]['id']='past-form2';duplicate['realizations'][0]['meanings'][0]['id']='went-meaning2';b['paradigms'][0]['rows'].append(duplicate);self.api('lexeme-save',x)
        self.source('corpus',[('went','去.PST')]);p=self.api('lexeme-auto-preview?language=ordos');self.assertEqual(len(p['matches']),0);self.assertEqual(len(p['ambiguous'][0]['candidates']),2)
        src=self.source('independent',[('went','')]);p=self.api('sentence-gloss-preview',self.args(src));self.assertFalse(p['rows'][0]['automatic']);self.assertEqual(len(p['rows'][0]['candidates']),2)

    def test_completion_both_sources_and_meaning_provider_without_writeback(self):
        x=self.entry();sources=[]
        for kind in ('corpus','independent'):
            src=self.source(kind,[('went',''),('free','')]);sources.append(src);p=self.complete(src);self.assertEqual(p['rows'][0]['candidates'][0]['sense_id'],'went-meaning');self.assertEqual(self.gloss(src),'去.PST')
        with server.connect(audit=False) as db:before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ('entries','dictionary_examples','corpus_units','unit_segments','gloss_bindings')}
        self.change(x,'移动.PST');self.assertEqual([self.gloss(s) for s in sources],['移动.PST']*2)
        with server.connect(audit=False) as db:
            for t,rows in before.items():self.assertEqual(rows,[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')],t)
        self.assertEqual(self.api('entries?language=ordos&q=移动&field=gloss&include_independent=true')['total'],2)
        with server.connect(audit=False) as db:tid=db.execute('SELECT text_id FROM entries WHERE id=?',(sources[0]['id'],)).fetchone()[0]
        self.assertIn('移动.PST',self.api('export?id='+tid))
        self.assertEqual(self.api('lexemes?language=ordos&q=过去的移动&counts=0')['total'],1)
        self.undo();self.assertEqual([self.gloss(s) for s in sources],['去.PST']*2);self.undo(True)

    def test_manual_link_override_unlink_and_reference_protection(self):
        x=self.entry();sources=[]
        for kind in ('corpus','independent'):
            src=self.source(kind,[('went','手写')]);sources.append(src);self.link(src,x);self.assertEqual(self.gloss(src),'去.PST')
        for field in ('paradigms','variants','usages'):
            bad=self.get(x);bad['body'][field]=[];code,r=self.call('/api/lexeme-save',bad);self.assertEqual(code,400,r)
        src=sources[0];d=self.detail(src);binding=d['body']['words'][0]['gloss_sources'][0]
        self.api('gloss-source-save',dict(**self.args(src),binding_id=binding['id'],binding_revision=binding['revision'],gloss_revision=d['body']['gloss_revision'],mode='override',value='本句'))
        self.change(x,'移动.PST');self.assertEqual([self.gloss(s) for s in sources],['本句','移动.PST'])
        d=self.detail(sources[1]);self.api('segmentation-link',dict(**self.args(sources[1]),remove_target=0));self.change(x,'再改.PST');self.assertEqual(self.gloss(sources[1]),'移动.PST')
        bad=self.get(x);s=sources[1];b=dict(**self.args(s),word=0,key='@word',lexeme_id=x['id'],lexeme_revision=bad['revision'],usage_id='verb',sense_id='went-meaning',form_id='goes',link_revision=0)
        self.assertEqual(self.call('/api/segmentation-link',b)[0],400)

    def test_language_templates_are_layout_only_independent_and_undoable(self):
        x=self.entry();lang=self.api('languages')[0];meta=json.loads(lang['metadata']);meta['paradigm_templates']=[x['body']['paradigms'][0]]
        self.api('save-language',dict(id=lang['id'],name=lang['name'],revision=lang['revision'],metadata=meta));template=json.loads(self.api('languages')[0]['metadata'])['paradigm_templates'][0]
        self.assertNotIn('realizations',template['rows'][0]);self.assertEqual(template['rows'][0]['state'],'unfilled')
        self.api('save-language',dict(name='other',metadata={}));self.assertNotIn('paradigm_templates',json.loads(self.api('languages')[-1]['metadata']))
        self.assertEqual(self.get(x)['body']['paradigms'][0]['rows'][0]['state'],'filled')

    def test_language_package_remaps_meanings_forms_and_bindings(self):
        x=self.entry();a=self.source('corpus',[('went','去.PST')]);b=self.source('independent',[('went','去.PST')]);self.link(a,x);self.link(b,x)
        p=self.api('language-package-export',{});path=language_exchange.staged(server.DB,p['token'],'export');token=language_exchange.stage(server.DB,path,'import')
        result=self.api('language-package-import',dict(token=token,name='Imported paradigms'));lid=result['language_id']
        imported=self.api('lexemes?language='+lid)['items'][0];table=imported['body']['paradigms'][0];f=table['rows'][0]['realizations'][0]
        self.assertNotEqual(f['form_id'],'went');self.assertNotEqual(f['meanings'][0]['id'],'went-meaning');self.assertEqual(len(self.api('entries?language='+lid+'&include_independent=true')['items']),2)
        imported['body']['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['short_gloss']='导入.PST';self.api('lexeme-save',{**imported,'_language':lid})
        self.assertEqual({r['words'][0]['gloss'] for r in self.api('entries?language='+lid+'&include_independent=true')['items']},{'导入.PST'})
        self.assertEqual([self.gloss(s) for s in (a,b)],['去.PST']*2)
        with server.connect(audit=False) as db:self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_base_meaning_edit_does_not_change_form_meaning_and_analysis_uses_live_gloss(self):
        self.api('grammar-save',dict(symbol='FUT'))
        x=self.entry();a=self.source('corpus',[('went','')]);b=self.source('independent',[('went','')])
        for src in (a,b):self.complete(src)
        x=self.get(x);x['body']['usages'][0]['senses'][0]['short_gloss']='离开';self.api('lexeme-save',x)
        self.assertEqual([self.gloss(s) for s in (a,b)],['去.PST']*2)
        self.change(x,'移动.FUT')
        run=self.api('analysis-run',dict(query=dict(conditions=[dict(field='tag',value='FUT',mode='exact')],scope={'source':'all'})))
        self.assertEqual(run['summary']['sentences'],2)

    def test_form_spelling_edit_syncs_selected_form_both_sources(self):
        x=self.entry();a=self.source('corpus',[('went','去.PST')]);b=self.source('independent',[('went','去.PST')])
        for src in (a,b):self.link(src,x)
        x=self.get(x);x['body']['variants'][0]['form']='went2';self.api('lexeme-save',x)
        self.assertEqual([self.detail(s)['body']['words'][0]['form'] for s in (a,b)],['went2']*2)
        self.undo();self.assertEqual([self.detail(s)['body']['words'][0]['form'] for s in (a,b)],['went']*2)

    def test_json_backup_restores_form_meaning_and_overrides(self):
        from restore_backup import restore
        x=self.entry();a=self.source('corpus',[('went','去.PST')]);b=self.source('independent',[('went','去.PST')])
        for src in (a,b):self.link(src,x)
        self.change(x,'移动.PST');backup=Path(self.temp.name)/'backup.json';backup.write_text(json.dumps(self.api('backup'),ensure_ascii=False),encoding='utf-8');dest=Path(self.temp.name)/'restore.sqlite3';restore(backup,dest)
        original=server.DB
        try:
            server.DB=dest;server.init();self.assertEqual([self.gloss(s) for s in (a,b)],['移动.PST']*2);self.change(x,'恢复.PST');self.assertEqual([self.gloss(s) for s in (a,b)],['恢复.PST']*2)
        finally:server.DB=original

    def test_quick_intake_adds_base_sense_without_discarding_table(self):
        x=self.entry();src=self.source('corpus',[('go','新义')]);b=dict(**self.args(src),word=0,key='@word',mode='sense',target_id=x['id'],usage_id='verb',form='go',gloss='新义',target_kind='lexeme')
        p=self.api('sentence-dictionary-preview',b);self.api('sentence-dictionary-apply',dict(**b,token=p['token']))
        fresh=self.get(x);self.assertEqual(len(fresh['body']['usages'][0]['senses']),2);self.assertEqual(fresh['body']['paradigms'],x['body']['paradigms']);self.assertEqual(self.gloss(src),'新义')

    def test_dictionary_replace_includes_form_meanings_and_undo(self):
        x=self.entry();a=self.source('corpus',[('went','去.PST')]);b=self.source('independent',[('went','去.PST')])
        for src in (a,b):self.link(src,x)
        args=dict(field='short_gloss',find='去.PST',replacement='移动.PST',scope='current',lexeme_id=x['id'])
        p=self.api('dictionary-replace-preview',args);self.assertEqual(len(p['changes']),1);self.assertFalse(p['blocked'])
        self.api('dictionary-replace-apply',dict(**args,token=p['token'],keys=[c['key'] for c in p['changes']],confirm_conflicts=True))
        self.assertEqual([self.gloss(s) for s in (a,b)],['移动.PST']*2)
        self.undo();self.assertEqual([self.gloss(s) for s in (a,b)],['去.PST']*2)

    def test_conversion_and_merge_preserve_table_and_bound_meaning(self):
        x=self.entry();a=self.source('corpus',[('went','去.PST')]);b=self.source('independent',[('went','去.PST')])
        for src in (a,b):self.link(src,x)
        peer=self.api('morpheme-save',dict(form='go',body=dict(gloss='故乡')))
        p=self.api('lexeme-to-morpheme-preview',dict(id=x['id'],revision=x['revision']))
        m=self.api('lexeme-to-morpheme',dict(id=x['id'],revision=x['revision'],token=p['token'],target_id=peer['id']))
        common=self.get(m);self.assertEqual(len(common['body']['paradigms']),1);self.assertEqual([self.gloss(s) for s in (a,b)],['去.PST']*2)
        self.undo();self.assertEqual(self.get(x)['body']['paradigms'],x['body']['paradigms'])
