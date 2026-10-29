import copy,json,unittest
from unittest.mock import patch
import server,paradigm_templates
import test_paradigms


class TemplateSyncTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo','complete','entry','get','link','gloss'):
        locals()[name]=getattr(test_paradigms.ParadigmTests,name)
    def setup_template(self):
        x=self.entry();t=copy.deepcopy(x['body']['paradigms'][0]);t['id']='template'
        for r in t['rows']:r['id']='template-'+r['id']
        l=self.api('languages')[0];m=json.loads(l['metadata']);m['paradigm_templates']=[t]
        self.api('save-language',dict(id=l['id'],revision=l['revision'],name=l['name'],metadata=m))
        x=self.get(x);x['body']['paradigms'][0]['template_id']='template';x=self.api('lexeme-save',x)
        return x

    def request(self,change,**more):
        l=self.api('languages')[0];m=json.loads(l['metadata']);change(m['paradigm_templates'])
        return dict(id=l['id'],revision=l['revision'],name=l['name'],metadata=m,**more)

    def submit(self,b,confirm=False):
        p=self.api('paradigm-template-preview',b)
        return self.api('save-language',dict(b,template_sync_token=p['token'],template_sync_confirmed=confirm)),p

    def test_sync_add_remove_empty_reorder_and_preserve_filled_ids(self):
        x=self.setup_template();before=copy.deepcopy(x['body']);old=x['body']['paradigms'][0]['rows'][0]
        def change(ts):
            t=ts[0];t['rows']=[t['rows'][1],t['rows'][0],dict(id='new-row',labels=['将来','全部','全部'],state='unfilled')]
        # Missing is meaningful, so removing it must be confirmed, even without a form.
        b=self.request(change);r,p=self.submit(b,True);self.assertTrue(p['deletions'])
        rows=self.get(x)['body']['paradigms'][0]['rows'];self.assertEqual([r['template_row_id'] for r in rows],['template-present','template-past','new-row'])
        self.assertEqual(rows[1]['id'],old['id']);self.assertEqual(rows[1]['realizations'],old['realizations']);self.assertEqual(rows[2]['state'],'unfilled')
        self.assertEqual(self.get(x)['body']['variants'],before['variants'])
        self.undo();self.assertEqual(self.get(x)['body'],before);self.undo(True);self.assertEqual(len(self.get(x)['body']['paradigms'][0]['rows']),3)

    def test_populated_deletion_requires_current_confirmation_and_keeps_sentences(self):
        x=self.setup_template();sources=[self.source(k,[('went','手写')]) for k in ('corpus','independent')]
        for src in sources:self.link(src,x)
        before=self.get(x);b=self.request(lambda ts:ts[0]['rows'].pop(0));p=self.api('paradigm-template-preview',b)
        self.assertEqual(self.call('/api/save-language',b)[0],400);self.assertEqual(self.get(x),before)
        self.assertEqual(self.call('/api/save-language',dict(b,template_sync_token=p['token']))[0],400)
        self.api('save-language',dict(b,template_sync_token=p['token'],template_sync_confirmed=True))
        self.assertNotIn('past',[r['id'] for r in self.get(x)['body']['paradigms'][0]['rows']])
        self.assertEqual([self.gloss(s) for s in sources],['去.PST']*2)
        with server.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM lexical_links WHERE lexeme_id=?',(x['id'],)).fetchone()[0],0)
        self.undo();self.assertEqual(self.get(x)['body'],before['body']);self.assertEqual([self.gloss(s) for s in sources],['去.PST']*2)
        self.undo(True);self.assertEqual([self.gloss(s) for s in sources],['去.PST']*2)

    def test_stale_confirmation_and_failed_sync_are_atomic(self):
        x=self.setup_template();b=self.request(lambda ts:ts[0]['rows'].pop(0));p=self.api('paradigm-template-preview',b)
        x=self.get(x);x['body']['notes']='Another window';self.api('lexeme-save',x)
        self.assertEqual(self.call('/api/save-language',dict(b,template_sync_token=p['token'],template_sync_confirmed=True))[0],400)
        p=self.api('paradigm-template-preview',b)
        with patch('paradigm_templates.paradigms.normalize',side_effect=ValueError('stop')):
            self.assertEqual(self.call('/api/save-language',dict(b,template_sync_token=p['token'],template_sync_confirmed=True))[0],400)
        self.assertEqual(len(self.get(x)['body']['paradigms'][0]['rows']),4)

    def test_draft_changes_are_reviewed_and_returned_without_saving_other_fields(self):
        x=self.setup_template();draft=copy.deepcopy(x['body']['paradigms']);draft[0]['rows'][3].update(state='missing')
        b=self.request(lambda ts:ts[0]['rows'].pop(),editor_paradigms=draft,editor_target_id=x['id'],editor_target_revision=x['revision'],editor_headword=x['headword'])
        p=self.api('paradigm-template-preview',b);self.assertTrue(any(r['draft'] for r in p['deletions']))
        r,p=self.submit(b,True);self.assertEqual(len(r['editor_paradigms'][0]['rows']),3);self.assertGreater(r['editor_target_revision'],x['revision'])

    def test_independent_rows_local_tags_and_other_languages_are_preserved(self):
        x=self.setup_template();x['body']['paradigms'][0]['rows'].append(dict(id='local',labels=['自建','一','二'],state='missing',realizations=[]))
        x=self.api('lexeme-save',x);independent=self.api('lexeme-save',dict(headword='other',body=test_paradigms.body()))
        b=self.request(lambda ts:ts[0]['rows'].append(dict(id='added',labels=['新增','一','二'],gloss_addition='SG')))
        r,p=self.submit(b);self.assertFalse(p['deletions'])
        table=self.get(x)['body']['paradigms'][0];self.assertEqual(table['rows'][-1]['id'],'local');self.assertEqual(table['rows'][-2]['gloss_addition'],'SG')
        self.assertEqual(self.get(independent)['body']['paradigms'][0]['rows'],independent['body']['paradigms'][0]['rows'])
        table['rows'][-2]['gloss_addition']='CUSTOM';current=self.get(x);current['body']['paradigms'][0]=table;self.api('lexeme-save',current)
        self.submit(self.request(lambda ts:ts[0]['rows'][-1].update(gloss_addition='PL')))
        self.assertEqual(self.get(x)['body']['paradigms'][0]['rows'][-2]['gloss_addition'],'CUSTOM')

    def test_delete_whole_template_confirmed_and_empty_rows_no_confirmation(self):
        x=self.setup_template();self.submit(self.request(lambda ts:ts.clear()),True)
        self.assertEqual(self.get(x)['body']['paradigms'],[]);self.assertEqual(len(self.get(x)['body']['variants']),2)
        self.undo();self.assertEqual(len(self.get(x)['body']['paradigms'][0]['rows']),4)
        b=self.request(lambda ts:ts[0]['rows'].pop());_,p=self.submit(b);self.assertEqual(p['deletions'],[])

    def test_same_template_in_multiple_tables_and_other_language_scope(self):
        x=self.setup_template();table=copy.deepcopy(x['body']['paradigms'][0]);table['id']='second-table'
        for row in table['rows']:
            row['id']='second-'+row['id']
            for f in row['realizations']:
                f['id']='second-'+f['id']
                for m in f['meanings']:m['id']='second-'+m['id']
        x['body']['paradigms'].append(table);x=self.api('lexeme-save',x)
        other=self.api('save-language',dict(name='Other',metadata={}))['id']
        foreign=self.api('lexeme-save',dict(headword='foreign',body=test_paradigms.body(),_language=other))
        self.submit(self.request(lambda ts:ts[0]['rows'].append(dict(id='new',labels=['新','一','二']))))
        self.assertEqual([len(t['rows']) for t in self.get(x)['body']['paradigms']],[5,5]);self.assertEqual(self.get(foreign)['body'],foreign['body'])

    def test_custom_blank_overrides_survive_confirmed_deletion_and_undo(self):
        x=self.setup_template();sources=[self.source(k,[('went','手写')]) for k in ('corpus','independent')]
        for src in sources:
            self.link(src,x);d=self.detail(src);binding=d['body']['words'][0]['gloss_sources'][0]
            self.api('gloss-source-save',dict(kind=src['kind'],id=src['id'],revision=d['revision'],binding_id=binding['id'],binding_revision=binding['revision'],gloss_revision=d['body']['gloss_revision'],mode='override',value=''))
        self.submit(self.request(lambda ts:ts[0]['rows'].pop(0)),True);self.assertEqual([self.gloss(s) for s in sources],['',''])
        self.undo();self.assertEqual([self.gloss(s) for s in sources],['',''])

    def test_dimension_and_label_changes_keep_row_meanings_and_local_metadata(self):
        x=self.setup_template();before=copy.deepcopy(x['body']);x['body']['paradigms'][0]['rows'][0]['template_row_id']='template-past';x=self.api('lexeme-save',x)
        def change(ts):
            ts[0]['dimensions']=['时间','主体'];ts[0]['title']='新标题'
            for row in ts[0]['rows']:row['labels']=row['labels'][:2]
        self.submit(self.request(change));table=self.get(x)['body']['paradigms'][0]
        self.assertEqual(table['title'],'新标题');self.assertEqual(table['dimensions'],['时间','主体']);self.assertEqual(table['rows'][0]['realizations'],before['paradigms'][0]['rows'][0]['realizations'])
        self.assertEqual(self.get(x)['body']['created_at'],before['created_at'])


