import copy
import json
import unittest
import server
import test_morpheme_registry


class QuickEditTests(unittest.TestCase):
    for helper in ('setUp','tearDown','call','seed','entries','undo','fixture','assign'):
        locals()[helper]=getattr(test_morpheme_registry.MorphemeRegistryTests,helper)

    def api(self,path,body=None):
        if body is None and path.startswith('quick-edit-settings'):path=path.replace('?_language=','?language=') if '?' in path else path+'?language=ordos'
        code,result=self.call('/api/'+path,body)
        self.assertEqual(code,200,result)
        return result

    def test_settings_language_isolation_revision_and_undo(self):
        t=self.api('writing-save',dict(name='汉字',font='Junicode'))
        before=self.api('quick-edit-settings')
        after=self.api('quick-edit-settings',dict(revision=before['revision'],writing_types=[t['id']]))
        self.assertEqual(after['selected'],[t['id']])
        self.assertEqual(self.call('/api/quick-edit-settings',dict(revision=before['revision'],writing_types=[]))[0],400)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.api('quick-edit-settings')['selected'],[])
        self.assertEqual(self.undo('redo')[0],200)
        other=self.api('save-language',dict(name='其他',metadata={}))['id']
        settings=self.api('quick-edit-settings?_language='+other)
        self.assertEqual(settings['selected'],[])
        self.assertEqual(self.call('/api/quick-edit-settings',dict(_language=other,revision=settings['revision'],writing_types=[t['id']]))[0],400)

    def test_settings_exchange_and_writing_replacement(self):
        a=self.api('writing-save',dict(name='汉字',font='Junicode'))
        b=self.api('writing-save',dict(name='转写',font='Junicode'))
        settings=self.api('quick-edit-settings');self.api('quick-edit-settings',dict(revision=settings['revision'],writing_types=[a['id'],b['id']]))
        bundle=self.api('export-language?language=ordos')
        lid=self.api('save-language',dict(name='复制',metadata={}))['id']
        self.api('import-language',dict(_language=lid,bundle=bundle))
        imported=self.api('quick-edit-settings?_language='+lid)
        self.assertEqual(len(imported['selected']),2)
        self.assertFalse(set(imported['selected'])&{a['id'],b['id']})
        self.api('writing-delete',dict(id=a['id'],revision=a['revision'],replacement_id=b['id'],confirmed=True))
        self.assertEqual(self.api('quick-edit-settings')['selected'],[b['id']])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.api('quick-edit-settings')['selected'],[a['id'],b['id']])

    def test_blank_structure_rows_are_omitted_but_partial_rows_rejected(self):
        body=dict(word_structure=dict(memberships=[dict(id='empty-class')],analyses=[dict(id='empty-analysis',default=True,level='unspecified',components=[dict(id='empty-component',form=' ')])]))
        original=copy.deepcopy(body)
        saved=self.api('lexeme-save',dict(headword='test',body=body))
        self.assertEqual(saved['body']['word_structure'],dict(memberships=[],analyses=[]))
        self.assertEqual(body,original)
        for partial in (dict(memberships=[dict(notes='保留')]),dict(analyses=[dict(components=[dict(readings=['ma'])])])):
            self.assertEqual(self.call('/api/lexeme-save',dict(headword='partial',body=dict(word_structure=partial)))[0],400)

    def test_inherit_writings_on_assign_and_saved_response_revision(self):
        _,x=self.fixture();t=self.api('writing-save',dict(name='汉字',font='Junicode'))
        m=self.api('morpheme-save',dict(form='home',body=dict(writings=[dict(type_id=t['id'],text='家')],readings=['ha'])))
        code,result=self.assign(x,create=None,morpheme_id=m['id'],morpheme_revision=m['revision'])
        self.assertEqual(code,200,result)
        x=self.api('lexeme?id='+x['id'])
        self.assertEqual(x['body']['word_structure']['analyses'][0]['components'][0]['writings'],m['body']['writings'])
        x['body']['word_structure']['analyses'][1]['components'][0]['form']='unique'
        saved=self.api('lexeme-save',x)
        self.assertEqual(saved['revision'],self.api('lexeme?id='+x['id'])['revision'])
        self.assertEqual(self.api('morpheme-sync-writings',{})['components'],0)

    def test_repair_only_missing_writings_single_undo_step_and_follow_future_changes(self):
        _,x=self.fixture();t=self.api('writing-save',dict(name='汉字',font='Junicode'))
        m=self.api('morpheme-save',dict(form='home',body=dict(writings=[dict(type_id=t['id'],text='家')])))
        self.assertEqual(self.assign(x,create=None,morpheme_id=m['id'],morpheme_revision=m['revision'],components=[dict(analysis_id='a',component_id='c'),dict(analysis_id='b',component_id='d')])[0],200)
        # Reproduce data from versions that did not materialize inherited writings.
        with server.connect(audit=False) as db:
            body=json.loads(db.execute('SELECT body FROM lexemes WHERE id=?',(x['id'],)).fetchone()[0])
            body['word_structure']['analyses'][0]['components'][0]['writings']=[]
            body['word_structure']['analyses'][1]['components'][0]['writings']=[dict(type_id=t['id'],text='局部')]
            db.execute('UPDATE lexemes SET body=? WHERE id=?',(json.dumps(body),x['id']))
        before=self.api('entries')['items']
        repaired=self.api('morpheme-sync-writings',{});self.assertEqual((repaired['lexemes'],repaired['components']),(1,1))
        self.assertEqual(self.api('undo-state')['undo']['label'],'同步语素书写形式')
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.api('lexeme?id='+x['id'])['body']['word_structure']['analyses'][0]['components'][0]['writings'],[])
        self.assertEqual(self.undo('redo')[0],200)
        current=self.api('morpheme?id='+m['id']);current['body']['writings'][0]['text']='新家';self.api('morpheme-save',current)
        a,b=self.api('lexeme?id='+x['id'])['body']['word_structure']['analyses']
        self.assertEqual(a['components'][0]['writings'][0]['text'],'新家')
        self.assertEqual(b['components'][0]['writings'][0]['text'],'局部')
        self.assertEqual(self.api('entries')['items'],before)
        self.assertEqual(self.api('morpheme-sync-writings',{})['components'],0)

    def test_complete_reading_sizes_preserve_whole_homophone_groups(self):
        with server.connect(audit=False) as db:
            for i in range(57):
                for n in range(2):db.execute('INSERT INTO morphemes VALUES(?,?,?,?,?,1)',(f'{i}-{n}','ordos',f'form{i}-{n}',1,json.dumps(dict(readings=[f'r{i:02}']))))
        for size in (10,20,50,'all'):
            data=self.api('homophones?language=ordos&view=reading&page_size='+str(size))
            self.assertEqual(len(data['groups']),57 if size=='all' else size)
            self.assertTrue(all(len(g['items'])==2 for g in data['groups']))
            last=self.api('homophones?language=ordos&view=reading&page_size='+str(size)+'&page=999')
            self.assertEqual(last['page'],last['pages'])
        for bad in ('0','40','100','bad'):
            self.assertEqual(self.call('/api/homophones?view=reading&page_size='+bad)[0],400)


if __name__=='__main__':unittest.main()
