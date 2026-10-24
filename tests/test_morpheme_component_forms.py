import copy
import json
import unittest
from pathlib import Path

import server
import test_morpheme_sync
from restore_backup import restore


class ComponentFormTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','undo','api'):
        locals()[name] = getattr(test_morpheme_sync.MorphemeSyncTests, name)

    def fixture(self):
        m = self.api('morpheme-save', dict(form='-n', body=dict(gloss='GEN',readings=['n'],
                     variants=[dict(form='-ne',pronunciation='ne',variation='conditioned'),
                               dict(form='-ne',pronunciation='ni',variation='conditioned')])))
        x = self.api('lexeme-save', dict(headword='root',body=dict(word_structure=dict(analyses=[dict(
            id='analysis',components=[dict(id='c'+str(i),form='-n' if i==0 else '-ne',gloss='GEN',
                                         readings=['n'] if i==0 else ['ne']) for i in range(4)])]))))
        return m,x

    def components(self,x):
        return self.api('lexeme?id='+x['id'])['body']['word_structure']['analyses'][0]['components']

    def assign_form(self,m,x,index,form_id):
        m=self.api('morpheme?id='+m['id']);x=self.api('lexeme?id='+x['id'])
        previous=self.api('morpheme-components?id='+x['id'])['items'][index]['link']
        self.api('morpheme-assign',dict(morpheme_id=m['id'],morpheme_revision=m['revision'],
            form_id=form_id,lexeme_id=x['id'],lexeme_revision=x['revision'],
            components=[dict(analysis_id='analysis',component_id='c'+str(index),
                             revision=previous['revision'] if previous else 0)]))

    def test_conditioned_variants_can_be_saved_without_distribution_and_replace_can_clear_it(self):
        m,x=self.fixture()
        for kind,row,field in [('morpheme',m,'form'),('lexeme',x,'headword')]:
            row=copy.deepcopy(row)
            if kind=='lexeme':row['body']['variants']=[dict(form='roots',variation='conditioned')]
            saved=self.api(kind+'-save',row)
            self.assertEqual(saved['body']['variants'][0]['conditions'],'')
            saved['body']['variants'][0]['conditions']='after vowels'
            saved=self.api(kind+'-save',saved)
            if kind=='lexeme':
                saved['body']['variants'][0]['conditions']=''
                actual=self.api(kind+'-save',saved)
                self.assertEqual(actual['body']['variants'][0]['conditions'],'')
                continue
            args=dict(kind=kind,scope='current',field='all',find='after vowels',replacement='',mode='exact',
                      **{kind+'_id':saved['id']})
            p=self.api('dictionary-replace-preview',args);self.assertEqual(p['blocked'],[])
            self.api('dictionary-replace-apply',dict(**args,token=p['token'],keys=[c['key'] for c in p['changes']],confirm_conflicts=True))
            actual=self.api(kind+'?id='+saved['id'])
            self.assertEqual(actual['body']['variants'][0]['variation'],'conditioned')
            self.assertEqual(actual['body']['variants'][0]['conditions'],'')

    def test_base_and_same_spelling_variants_sync_separately_and_undo_redo(self):
        m,x=self.fixture();fids=[v['id'] for v in m['body']['variants']]
        for index,form_id in enumerate([None,*fids]):self.assign_form(m,x,index,form_id)
        m=self.api('morpheme?id='+m['id']);before=copy.deepcopy(self.components(x))
        m['body']['variants'][0].update(form='-nea',pronunciation='nɛ')
        self.api('morpheme-save',m)
        changed=self.components(x)
        self.assertEqual([c['form'] for c in changed],['-n','-nea','-ne','-ne'])
        self.assertEqual([c['readings'] for c in changed],[['n'],['nɛ'],['ni'],['ne']])
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.components(x),before)
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.components(x),changed)
        m=self.api('morpheme?id='+m['id']);m['form']='-na';m['body']['gloss']='POSS'
        self.api('morpheme-save',m)
        self.assertEqual([c['form'] for c in self.components(x)],['-na','-nea','-ne','-ne'])
        self.assertEqual([c['gloss'] for c in self.components(x)],['POSS','POSS','POSS','GEN'])
        actual=self.api('morpheme-components?id='+x['id'])['items']
        self.assertEqual([r['link']['form_id'] if r['link'] else None for r in actual],[None,*fids,None])

    def test_multiple_form_choices_in_normal_quick_save_pipeline_preserve_ids_on_reopen(self):
        m,x=self.fixture();fids=[v['id'] for v in m['body']['variants']]
        assignments=[dict(analysis_id='analysis',component_id='c'+str(i),morpheme_id=m['id'],form_id=fid)
                     for i,fid in enumerate([None,*fids])]
        preview=self.api('morpheme-save-preview',dict(**x,assignments=assignments))
        saved=self.api('lexeme-save',dict(**x,morpheme_assignments=assignments,morpheme_confirmation=preview['token']))
        self.assertEqual(saved['revision'],self.api('lexeme?id='+x['id'])['revision'])
        links=self.api('morpheme-components?id='+x['id'])['items']
        self.assertEqual([r['link']['form_id'] for r in links[:3]],[None,*fids])
        self.assertEqual([c['readings'] for c in self.components(x)[:3]],[['n'],['ne'],['ni']])
        # A normal subsequent save without changed assignments keeps the selection.
        p=self.api('morpheme-save-preview',saved)
        saved=self.api('lexeme-save',dict(**saved,morpheme_confirmation=p['token']))
        self.assertEqual(self.api('morpheme-components?id='+x['id'])['items'][2]['link']['form_id'],fids[1])

    def test_invalid_form_stale_and_deleting_a_bound_variant_are_atomic(self):
        m,x=self.fixture();form_id=m['body']['variants'][0]['id']
        before=self.components(x);state=self.api('undo-state')
        b=dict(morpheme_id=m['id'],morpheme_revision=m['revision'],form_id='missing',
               lexeme_id=x['id'],lexeme_revision=x['revision'],components=[dict(analysis_id='analysis',component_id='c1')])
        self.assertEqual(self.call('/api/morpheme-assign',b)[0],400)
        self.assertEqual(self.components(x),before);self.assertEqual(self.api('undo-state'),state)
        self.assign_form(m,x,1,form_id)
        m=self.api('morpheme?id='+m['id']);old=copy.deepcopy(m);m['body']['variants']=m['body']['variants'][1:]
        self.assertEqual(self.call('/api/morpheme-save',m)[0],400)
        self.assertEqual(self.api('morpheme?id='+m['id'])['body'],old['body'])
        self.assertEqual(self.call('/api/morpheme-assign',dict(b,form_id=form_id))[0],400)

    def test_variant_find_replace_updates_only_its_components_and_local_overrides_survive(self):
        m,x=self.fixture();fids=[v['id'] for v in m['body']['variants']]
        self.assign_form(m,x,1,fids[0]);self.assign_form(m,x,2,fids[1])
        fresh=self.api('lexeme?id='+x['id']);fresh['body']['word_structure']['analyses'][0]['components'][2]['form']='local'
        self.api('lexeme-save',fresh)
        args=dict(kind='morpheme',scope='current',morpheme_id=m['id'],field='variant',find='-ne',replacement='-nei',mode='exact')
        preview=self.api('dictionary-replace-preview',args)
        key=next(c['key'] for c in preview['changes'] if c['path']==['body','variants',0,'form'])
        before=self.components(x)
        self.api('dictionary-replace-apply',dict(**args,token=preview['token'],keys=[key],confirm_conflicts=True))
        self.assertEqual([c['form'] for c in self.components(x)],['-n','-nei','local','-ne'])
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.components(x),before)

    def test_language_exchange_and_backup_restore_keep_the_variant_reference(self):
        m,x=self.fixture();fid=m['body']['variants'][1]['id'];self.assign_form(m,x,2,fid)
        bundle=self.api('export-language?language=ordos');lid=self.api('save-language',dict(name='copy',metadata={}))['id']
        self.api('import-language',dict(_language=lid,bundle=bundle))
        mx=self.api('morphemes?language='+lid)['items'][0];xx=self.api('lexemes?language='+lid)['items'][0]
        link=self.api('morpheme-components?language='+lid+'&id='+xx['id'])['items'][2]['link']
        self.assertNotEqual(link['form_id'],fid);self.assertEqual(link['form_id'],mx['body']['variants'][1]['id'])
        backup=Path(self.temp.name)/'backup.json';backup.write_text(json.dumps(self.api('backup')),encoding='utf-8')
        target=Path(self.temp.name)/'restored.sqlite3';restore(backup,target);original=server.DB
        try:
            server.DB=target
            self.assertEqual(self.api('morpheme-components?id='+x['id'])['items'][2]['link']['form_id'],fid)
            current=self.api('morpheme?id='+m['id']);current['body']['variants'][1]['form']='-nu'
            self.api('morpheme-save',current);self.assertEqual(self.components(x)[2]['form'],'-nu')
            self.assertEqual(self.undo()[0],200);self.assertEqual(self.components(x)[2]['form'],'-ne')
        finally:server.DB=original

    def test_merge_remaps_colliding_variant_ids_without_losing_the_selected_form(self):
        m,x=self.fixture();fid=m['body']['variants'][0]['id'];self.assign_form(m,x,1,fid)
        target=self.api('morpheme-save',dict(form='-k',body=dict(variants=[dict(id=fid,form='-ke')])))
        m=self.api('morpheme?id='+m['id'])
        result=self.api('morpheme-merge',dict(id=m['id'],revision=m['revision'],target_id=target['id'],target_revision=target['revision'],confirmed=True))
        link=self.api('morpheme-components?id='+x['id'])['items'][1]['link']
        self.assertNotEqual(link['form_id'],fid)
        self.assertEqual(next(v['form'] for v in result['body']['variants'] if v['id']==link['form_id']),'-ne')
        result['body']['variants'][1]['form']='-new'
        self.api('morpheme-save',result);self.assertEqual(self.components(x)[1]['form'],'-new')
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.api('morpheme-components?id='+x['id'])['items'][1]['link']['form_id'],fid)
