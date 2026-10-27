import copy
import json
import unittest
from pathlib import Path

import server
import paradigms
import language_exchange
import test_paradigms as old


def body():
    b=old.body();b['usages'][0]['senses'][0]['short_gloss']='1SG'
    t=b['paradigms'][0];t['default_base_sense_id']='go-meaning'
    for row,extra in zip(t['rows'],('ACC','GEN')):
        row['gloss_addition']=extra
        row['realizations'][0]['meanings'][0].update(gloss_mode='inherit',gloss_addition=extra,short_gloss='stale input must not persist')
    return b


class ParadigmInheritanceTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo','complete','get','link','gloss'):
        locals()[name]=getattr(old.ParadigmTests,name)

    def entry(self):return self.api('lexeme-save',dict(headword='go',body=body()))
    def edit_base(self,x,value):
        x=self.get(x);x['body']['usages'][0]['senses'][0]['short_gloss']=value
        return self.api('lexeme-save',x)

    def test_normalize_projection_and_independent_compatibility(self):
        x=self.entry();b=x['body'];m=b['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]
        self.assertEqual(m['short_gloss'],'');self.assertEqual(m['gloss_addition'],'ACC')
        frozen=copy.deepcopy(b);self.assertEqual(paradigms.usages(b)[0]['senses'][1]['short_gloss'],'1SG.ACC')
        self.assertEqual(paradigms.project(b)['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['short_gloss'],'1SG.ACC')
        self.assertEqual(b,frozen)
        m.pop('gloss_mode');m['short_gloss']='独立';x=self.api('lexeme-save',x);self.edit_base(x,'2SG')
        self.assertEqual(paradigms.usages(self.get(x)['body'])[0]['senses'][1]['short_gloss'],'独立')

    def test_composition_boundaries_decorations_and_deduplication(self):
        self.assertEqual(paradigms.compose('1SG','NOM.SG.NOM'),'1SG.NOM.SG')
        self.assertEqual(paradigms.compose('go.NOM','nom.SG'),'go.NOM.SG')
        self.assertEqual(paradigms.compose('1#sub[POT]','ACC'),'1#sub[POT].ACC')
        self.assertEqual(paradigms.compose('go-PST',''),'go-PST')
        for base,extra in (('','NOM'),('go-PST','NOM'),('go..PST','NOM'),('1SG','ACC-NOM'),('1SG','ACC..NOM'),('1SG','ACC GEN')):
            with self.subTest(base=base,extra=extra),self.assertRaises(ValueError):paradigms.compose(base,extra)
        for mode in ('invalid',None):
            b=body();b['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['gloss_mode']=mode
            self.assertEqual(self.call('/api/lexeme-save',dict(headword='bad',body=b))[0],400)

    def test_both_sources_completion_live_base_no_occurrence_writes_and_cache_refresh(self):
        self.api('grammar-save',dict(symbol='ACC'))
        x=self.entry();sources=[self.source(k,[('went','')]) for k in ('corpus','independent')]
        for src in sources:self.complete(src);self.assertEqual(self.gloss(src),'1SG.ACC')
        self.assertEqual(self.api('entries?language=ordos&q=1SG.ACC&field=gloss&include_independent=true')['total'],2)
        with server.connect(audit=False) as db:
            before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ('entries','dictionary_examples','corpus_units','unit_segments','gloss_bindings')}
        self.edit_base(x,'2SG')
        with server.connect(audit=False) as db:
            for t,rows in before.items():self.assertEqual(rows,[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')],t)
        self.assertEqual([self.gloss(s) for s in sources],['2SG.ACC']*2)
        self.assertEqual(self.api('entries?language=ordos&q=2SG.ACC&field=gloss&include_independent=true')['total'],2)
        run=self.api('analysis-run',dict(query=dict(conditions=[dict(field='tag',value='ACC',mode='exact')],scope={'source':'all'})))
        self.assertEqual(run['summary']['sentences'],2)
        exported=self.api('analysis-export?id='+run['id']+'&language=ordos')
        self.assertEqual({r['body']['words'][0]['gloss'] for r in exported['records'].values()},{'2SG.ACC'})
        self.assertEqual(self.api('example-library?language=ordos&source=all&q=2SG.ACC&field=gloss')['total'],2)
        with server.connect(audit=False) as db:tid=db.execute('SELECT text_id FROM entries WHERE id=?',(sources[0]['id'],)).fetchone()[0]
        self.assertIn('2SG.ACC',self.api('export?id='+tid))
        self.undo();self.assertEqual([self.gloss(s) for s in sources],['1SG.ACC']*2)
        self.undo(True);self.assertEqual([self.gloss(s) for s in sources],['2SG.ACC']*2)

    def test_auto_match_specific_forms_and_complete_composed_gloss(self):
        self.entry()
        for kind in ('corpus','independent'):self.source(kind,[('went','1SG.ACC'),('goes','1SG.GEN'),('went','1SG.GEN'),('went','ACC')])
        p=self.api('lexeme-auto-preview?language=ordos');self.assertEqual(len(p['matches']),4)
        self.assertEqual({(m['form_id'],m['sense_id']) for m in p['matches']},{('went','went-meaning'),('goes','goes-meaning')})
        self.api('lexeme-auto-link',dict(token=p['token']))

    def test_override_and_unlink_freeze_composed_value(self):
        x=self.entry();sources=[self.source(k,[('went','old')]) for k in ('corpus','independent')]
        for src in sources:self.link(src,x)
        for src in sources:
            d=self.detail(src);binding=d['body']['words'][0]['gloss_sources'][0]
            self.api('gloss-source-save',dict(**self.args(src),binding_id=binding['id'],binding_revision=binding['revision'],gloss_revision=d['body']['gloss_revision'],mode='override',value='本句'))
        self.edit_base(x,'2SG');self.assertEqual([self.gloss(s) for s in sources],['本句']*2)
        for src in sources:
            d=self.detail(src);binding=d['body']['words'][0]['gloss_sources'][0]
            self.api('gloss-source-save',dict(**self.args(src),binding_id=binding['id'],binding_revision=binding['revision'],gloss_revision=d['body']['gloss_revision'],mode='inherit'))
            if src['kind']=='corpus':
                uid=self.detail(src)['body']['words'][0]['unit_id'];u=self.api('unit-dictionary?id='+uid)
                self.api('lexeme-unlink',dict(id=u['link']['id'],revision=u['link']['revision']))
            else:self.api('segmentation-link',dict(**self.args(src),remove_target=0))
        self.edit_base(x,'3SG');self.assertEqual([self.gloss(s) for s in sources],['2SG.ACC']*2)

    def test_missing_base_and_default_references_rejected_even_when_unlinked(self):
        x=self.entry()
        for mutate in (lambda b:b['usages'][0].update(senses=[]),lambda b:b['paradigms'][0].update(default_base_sense_id='missing'),lambda b:b['usages'][0]['senses'][0].update(short_gloss='go-PST'),lambda b:b['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0].update(base_sense_id='')):
            bad=copy.deepcopy(x);mutate(bad['body']);self.assertEqual(self.call('/api/lexeme-save',bad)[0],400)
        self.assertEqual(self.get(x)['revision'],x['revision'])

    def test_dictionary_search_and_replace_use_final_value_freezing_only_edited_form(self):
        x=self.entry();src=self.source('corpus',[('went','')]);self.complete(src)
        self.assertEqual(self.api('lexemes?language=ordos&q=1SG.ACC&counts=0')['total'],1)
        args=dict(field='short_gloss',find='1SG.ACC',replacement='独立.ACC',scope='current',lexeme_id=x['id'])
        p=self.api('dictionary-replace-preview',args);self.assertEqual(len(p['changes']),1);self.assertFalse(p['blocked'])
        self.api('dictionary-replace-apply',dict(**args,token=p['token'],keys=[c['key'] for c in p['changes']],confirm_conflicts=True))
        self.edit_base(x,'2SG');self.assertEqual(self.gloss(src),'独立.ACC')
        values=[s['short_gloss'] for s in paradigms.usages(self.get(x)['body'])[0]['senses']]
        self.assertEqual(values,['2SG','独立.ACC','2SG.GEN'])

    def test_template_presets_copy_layout_without_sense_ids_or_meanings(self):
        x=self.entry();lang=self.api('languages')[0];meta=json.loads(lang['metadata']);meta['paradigm_templates']=[x['body']['paradigms'][0]]
        self.api('save-language',dict(id=lang['id'],name=lang['name'],revision=lang['revision'],metadata=meta))
        template=json.loads(self.api('languages')[0]['metadata'])['paradigm_templates'][0]
        self.assertNotIn('default_base_sense_id',template);self.assertEqual(template['rows'][0]['gloss_addition'],'ACC');self.assertNotIn('realizations',template['rows'][0])
        template['rows'][0]['gloss_addition']='DAT';self.assertEqual(self.get(x)['body']['paradigms'][0]['rows'][0]['gloss_addition'],'ACC')

    def test_language_exchange_remaps_base_reference_and_live_inheritance(self):
        x=self.entry();a=self.source('corpus',[('went','')]);b=self.source('independent',[('went','')])
        for src in (a,b):self.complete(src)
        p=self.api('language-package-export',{});path=language_exchange.staged(server.DB,p['token'],'export');token=language_exchange.stage(server.DB,path,'import')
        lid=self.api('language-package-import',dict(token=token,name='Inherited'))['language_id']
        imported=self.api('lexemes?language='+lid)['items'][0];t=imported['body']['paradigms'][0];base=imported['body']['usages'][0]['senses'][0]
        self.assertNotEqual(base['id'],'go-meaning');self.assertEqual(t['default_base_sense_id'],base['id']);self.assertEqual(t['rows'][0]['realizations'][0]['meanings'][0]['base_sense_id'],base['id'])
        base['short_gloss']='3SG';self.api('lexeme-save',{**imported,'_language':lid})
        self.assertEqual({r['words'][0]['gloss'] for r in self.api('entries?language='+lid+'&include_independent=true')['items']},{'3SG.ACC'})
        self.assertEqual([self.gloss(s) for s in (a,b)],['1SG.ACC']*2)

    def test_json_backup_restore_keeps_derived_values(self):
        from restore_backup import restore
        x=self.entry();src=self.source('independent',[('went','')]);self.complete(src)
        backup=Path(self.temp.name)/'backup.json';backup.write_text(json.dumps(self.api('backup'),ensure_ascii=False),encoding='utf-8');dest=Path(self.temp.name)/'restore.sqlite3';restore(backup,dest)
        original=server.DB
        try:
            server.DB=dest;server.init();self.edit_base(x,'2SG');self.assertEqual(self.gloss(src),'2SG.ACC')
        finally:server.DB=original

    def test_conversion_to_morpheme_keeps_base_identity_and_composition(self):
        x=self.entry();sources=[self.source(k,[('went','')]) for k in ('corpus','independent')]
        for src in sources:self.complete(src)
        p=self.api('lexeme-to-morpheme-preview',dict(id=x['id'],revision=x['revision']))
        m=self.api('lexeme-to-morpheme',dict(id=x['id'],revision=x['revision'],token=p['token'],target_id='@new'))
        fresh=self.get(m);self.assertEqual([self.gloss(s) for s in sources],['1SG.ACC']*2)
        self.assertEqual(paradigms.usages(fresh['body'])[0]['senses'][1]['short_gloss'],'1SG.ACC')
        self.undo();self.assertEqual(self.get(x)['body']['paradigms'],x['body']['paradigms'])


class ParadigmMigrationTests(unittest.TestCase):
    def test_common_base_is_added_without_altering_citation_sense_and_plan_is_idempotent(self):
        from tools.migrate_paradigm_inheritance import plan
        b=old.body();b['usages'][0]['senses'][0]['short_gloss']='1sg.nom'
        for row,label in zip(b['paradigms'][0]['rows'],('1sg.acc','1sg.gen')):
            row['realizations'][0]['meanings'][0].update(short_gloss=label,base_sense_id='')
        before=copy.deepcopy(b);out,report=plan(dict(id='x',headword='word',body=b))
        self.assertEqual(b,before);self.assertEqual(len(report['changes']),2);self.assertEqual(len(report['added_bases']),1)
        self.assertEqual(out['usages'][0]['senses'][0],b['usages'][0]['senses'][0]);self.assertEqual(out['usages'][0]['senses'][1]['short_gloss'],'1sg')
        self.assertEqual({s['short_gloss'] for s in paradigms.usages(out)[0]['senses']},{'1sg','1sg.nom','1sg.acc','1sg.gen'})
        again,report=plan(dict(id='x',headword='word',body=out));self.assertEqual(out,again);self.assertEqual(report['changes'],[])

    def test_multiple_unmapped_base_senses_are_not_guessed(self):
        from tools.migrate_paradigm_inheritance import plan
        b=old.body();b['usages'][0]['senses'].append(dict(id='other',short_gloss='去',definition='其他'))
        b['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['base_sense_id']=''
        out,report=plan(dict(id='x',headword='word',body=b));self.assertEqual(len(report['skipped']),1)
        self.assertEqual(out['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0]['short_gloss'],'去.PST')

    def test_complex_gloss_is_not_split_into_different_scope(self):
        from tools.migrate_paradigm_inheritance import plan
        b=old.body();b['usages'][0]['senses'][0]['short_gloss']='go-PST'
        out,report=plan(dict(id='x',headword='word',body=b));self.assertEqual(out,b);self.assertEqual(report['changes'],[])
