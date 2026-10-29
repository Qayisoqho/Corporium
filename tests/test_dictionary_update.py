import json
import unittest
import test_lexicon
import test_object_media
import server


class DictionaryBatchTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    undo=test_lexicon.LexiconTests.undo

    def api(self,path,body=None):
        if body is None and 'language=' not in path:path+=('&' if '?' in path else '?')+'language=ordos'
        status,result=self.call('/api/'+path,body);self.assertEqual(status,200,result);return result

    def setup_batch(self):
        cls=self.api('class-save',dict(kind='pos',name='动词'))
        x=self.api('lexeme-save',dict(headword='aba',body=dict(usages=[dict(id='u',pos='名词',senses=[dict(id='s',short_gloss='家',definition='保留的释义')])],orthographies=[dict(label='本字',text='保留书写')],variants=[dict(id='v',form='ab')])))
        y=self.api('lexeme-save',dict(headword='aca',body={}))
        b=dict(items=[dict(id=r['id'],revision=r['revision']) for r in (x,y)],operations=[dict(field='pos',value=dict(pos=cls['id']))])
        return x,y,b

    def test_preview_conflict_one_step_undo_redo_preserves_meaning_and_form(self):
        x,y,b=self.setup_batch();before=self.api('undo-state')
        p=self.api('dictionary-batch-preview',b)
        self.assertEqual(self.api('undo-state'),before)
        self.assertEqual(p['total'],2);self.assertEqual(p['changed'],2);self.assertEqual(len(p['conflicts']),1)
        self.assertEqual(self.call('/api/dictionary-batch-apply',dict(**b,token=p['token']))[0],400)
        r=self.api('dictionary-batch-apply',dict(**b,token=p['token'],overwrite=True));self.assertEqual(r['changed'],2)
        saved=self.api('lexeme?id='+x['id'])
        for key in ('orthographies','variants'):self.assertEqual(saved['body'][key],x['body'][key])
        self.assertEqual(saved['body']['usages'][0]['senses'],x['body']['usages'][0]['senses'])
        self.assertEqual(saved['body']['usages'][0]['id'],'u');self.assertEqual(saved['body']['usages'][0]['pos'],'动词')
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.api('lexeme?id='+x['id'])['body'],x['body']);self.assertEqual(self.api('lexeme?id='+y['id'])['body'],y['body'])
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.api('lexeme?id='+x['id'])['body']['usages'][0]['pos'],'动词')

    def test_stale_duplicate_cross_language_and_unsupported_fields_are_atomic(self):
        x,y,b=self.setup_batch();p=self.api('dictionary-batch-preview',b)
        self.api('lexeme-save',{**x,'body':{**x['body'],'notes':'其他窗口'}})
        self.assertEqual(self.call('/api/dictionary-batch-apply',dict(**b,token=p['token'],overwrite=True))[0],400)
        self.assertEqual(self.api('lexeme?id='+y['id'])['body']['usages'],[])
        for data in [dict(b,items=[b['items'][1]]*2),dict(b,items=[b['items'][1]],operations=[dict(field='definition',value='错误')]),dict(b,items=[b['items'][1]],_language='other')]:
            self.assertEqual(self.call('/api/dictionary-batch-preview',data)[0],400)

    def test_morph_class_replace_preview_preserves_parts_on_add(self):
        c=self.api('class-save',dict(kind='morph',name='A类'));d=self.api('class-save',dict(kind='morph',name='B类'))
        x=self.api('lexeme-save',dict(headword='a',body=dict(word_structure=dict(memberships=[dict(id='m',class_id=c['id'],parts=[dict(id='p',label='过去式',form='at')])]))))
        b=dict(items=[dict(id=x['id'],revision=x['revision'])],operations=[dict(field='morph_classes',mode='add',value=[d['id']])])
        p=self.api('dictionary-batch-preview',b);self.assertEqual(p['conflicts'],[]);self.api('dictionary-batch-apply',dict(b,token=p['token']))
        x=self.api('lexeme?id='+x['id']);self.assertEqual(x['body']['word_structure']['memberships'][0]['parts'][0]['form'],'at')
        b['items'][0]['revision']=x['revision'];b['operations'][0]['mode']='replace';p=self.api('dictionary-batch-preview',b)
        self.assertIn('主要部分',p['conflicts'][0]['fields'][0])

    def test_combined_class_tag_and_feature_edits_leave_usage_tags_intact(self):
        x=self.api('lexeme-save',dict(headword='a',body=dict(usages=[dict(pos='名词',tags=[dict(type='region',value='本用法')])],tags=[dict(type='region',value='西部')])))
        c=self.api('dict-org-class-save',dict(name='人物'));g=self.api('grammar-save',dict(symbol='HON'))
        b=dict(items=[dict(id=x['id'],revision=x['revision'])],operations=[dict(field='semantic_classes',mode='add',value=[c['id']]),dict(field='entry_type',value='root'),dict(field='tags',mode='add',value=[dict(type='register',value='文语')]),dict(field='features',mode='add',value=[g['id']])])
        p=self.api('dictionary-batch-preview',b);self.assertFalse(p['conflicts']);self.api('dictionary-batch-apply',dict(b,token=p['token']))
        saved=self.api('lexeme?id='+x['id']);self.assertEqual(saved['body']['usages'],x['body']['usages']);self.assertEqual(saved['body']['features'],[g['id']]);self.assertEqual(saved['body']['entry_type'],'root');self.assertEqual(saved['body']['semantic_classes'],[c['id']]);self.assertEqual(len(saved['body']['tags']),2)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.api('lexeme?id='+x['id'])['body'],x['body'])

    def test_tag_add_remove_match_legacy_type_and_preserve_existing_notes(self):
        x=self.api('lexeme-save',dict(headword='a',body=dict(tags=[dict(type='region',value='西部',note='既有依据')])) )
        b=dict(items=[dict(id=x['id'],revision=x['revision'])],operations=[dict(field='tags',mode='add',value=[dict(type='地域',value='西部')])])
        p=self.api('dictionary-batch-preview',b);self.assertEqual(p['changed'],0)
        b['operations'][0]['mode']='remove';p=self.api('dictionary-batch-preview',b);self.api('dictionary-batch-apply',dict(b,token=p['token']))
        self.assertEqual(self.api('lexeme?id='+x['id'])['body']['tags'],[]);self.assertEqual(self.undo()[0],200);self.assertEqual(self.api('lexeme?id='+x['id'])['body']['tags'][0]['note'],'既有依据')


class MorphemeMediaTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','undo','image','audio','add'):
        locals()[name]=getattr(test_object_media.ObjectMediaTests,name)

    def api(self,path,body=None):
        if body is None and 'language=' not in path:path+=('&' if '?' in path else '?')+'language=ordos'
        code,r=self.call('/api/'+path,body);self.assertEqual(code,200,r);return r

    def morpheme(self,form='ta'):
        return self.api('morpheme-save',dict(form=form,body=dict(gloss='复数',variants=[dict(id='variant-'+form,form=form+'n',variation='conditioned',conditions='元音后',condition_types=['phonological'],tags=[dict(type='region',value='西部')])])) )

    def test_morpheme_image_audio_target_delete_and_undo(self):
        m=self.morpheme();self.assertEqual(m['body']['variants'][0]['conditions'],'元音后')
        code,r=self.add(m,self.image(),kind='morpheme');self.assertEqual(code,200,r)
        code,r=self.add(m,self.audio(),dict(target_id=m['body']['variants'][0]['id']),kind='morpheme');self.assertEqual(code,200,r)
        data=self.api('object-media?kind=morpheme&id='+m['id']);self.assertEqual(len(data['items']),2)
        self.assertEqual(self.call('/api/morpheme-save',dict(m,body=dict(gloss='复数',variants=[])))[0],400)
        self.api('morpheme-delete',dict(id=m['id'],revision=m['revision']))
        with server.connect(audit=False) as db:self.assertFalse(db.execute("SELECT 1 FROM object_media WHERE record_id=?",(m['id'],)).fetchone())
        self.assertEqual(self.undo()[0],200);self.assertEqual(len(self.api('object-media?kind=morpheme&id='+m['id'])['items']),2)

    def test_merge_moves_variant_media_and_undo_restores_owners(self):
        source=self.morpheme();target=self.morpheme('ti');self.assertEqual(self.add(source,self.audio(),dict(target_id=source['body']['variants'][0]['id']),kind='morpheme')[0],200)
        self.api('morpheme-merge',dict(id=source['id'],revision=source['revision'],target_id=target['id'],target_revision=target['revision'],confirmed=True))
        merged=self.api('morpheme?id='+target['id']);self.assertEqual(len(merged['body']['variants']),2)
        self.assertEqual(self.api('object-media?kind=morpheme&id='+target['id'])['items'][0]['body']['target_id'],'variant-ta')
        self.assertEqual(self.undo()[0],200);self.assertEqual(len(self.api('object-media?kind=morpheme&id='+source['id'])['items']),1)

    def test_complete_backup_keeps_media_and_redo_after_undone_deletion(self):
        from pathlib import Path
        from restore_backup import restore
        import media_engine
        m=self.morpheme();self.assertEqual(self.add(m,self.image(),kind='morpheme')[0],200)
        self.api('morpheme-delete',dict(id=m['id'],revision=m['revision']));self.assertEqual(self.undo()[0],200)
        backup=self.api('backup');source=Path(self.temp.name)/'backup.json';source.write_text(json.dumps(backup),encoding='utf-8');destination=Path(self.temp.name)/'restored/corpus.sqlite3';destination.parent.mkdir();restore(source,destination)
        original=server.DB
        try:
            server.DB=destination;data=self.api('object-media?kind=morpheme&id='+m['id']);self.assertTrue(media_engine.resolve(server.DB,data['items'][0]['asset']).is_file());self.assertEqual(self.undo('redo')[0],200)
            with server.connect(audit=False) as db:self.assertFalse(db.execute('SELECT 1 FROM object_media WHERE record_id=?',(m['id'],)).fetchone())
        finally:server.DB=original

    def test_variant_conditions_validation_pagination_and_language_exchange(self):
        m=self.morpheme();m['body']['variants'][0]['conditions']=''
        m=self.api('morpheme-save',m);self.assertEqual(m['body']['variants'][0]['variation'],'conditioned');self.assertEqual(m['body']['variants'][0]['conditions'],'')
        for i in range(12):self.api('morpheme-save',dict(form='z'+str(i),body={}))
        data=self.api('morphemes?page_size=10');self.assertEqual(len(data['items']),10);self.assertEqual(data['pages'],2)
        self.assertEqual(self.add(m,self.image(),dict(target_id='variant-ta'),kind='morpheme')[0],200)
        bundle=self.api('export-language');other=self.api('save-language',dict(name='Other',metadata={}))['id']
        self.api('import-language',dict(bundle=bundle,_language=other))
        rows=self.api('morphemes?language='+other)['items'];found=next(r for r in rows if r['form']=='ta');self.assertNotEqual(found['body']['variants'][0]['id'],'variant-ta')
        data=self.api('object-media?kind=morpheme&id='+found['id']);self.assertEqual(data['items'][0]['body']['target_id'],found['body']['variants'][0]['id'])

    def test_variant_class_rename_delete_guards_and_search(self):
        cls=self.api('class-save',dict(kind='form',name='特殊变体'));custom=next(c for c in self.api('classes') if c['id']==cls['id'])
        tag=self.api('class-save',dict(kind='usage_tag',name='限制'));usage=next(c for c in self.api('classes') if c['id']==tag['id'])
        m=self.api('morpheme-save',dict(form='x',body=dict(variants=[dict(form='y',kind='特殊变体',tags=[dict(type='限制',value='特殊语境')])])) )
        for c in (custom,usage):
            self.assertEqual(self.call('/api/class-delete',c)[0],200);self.undo()
        custom=next(c for c in self.api('classes') if c['id']==custom['id']);usage=next(c for c in self.api('classes') if c['id']==usage['id'])
        self.api('class-save',dict(custom,name='特别变体'));self.api('class-save',dict(usage,name='使用限制'))
        saved=self.api('morpheme?id='+m['id']);self.assertEqual(saved['body']['variants'][0]['kind'],'特别变体');self.assertEqual(saved['body']['variants'][0]['tags'][0]['type'],'使用限制')
        self.assertEqual(self.api('morphemes?q=特殊语境')['total'],1)


class FieldworkSearchTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call

    def api(self,path,body=None):
        if body is None and 'language=' not in path:path+=('&' if '?' in path else '?')+'language=ordos'
        code,r=self.call('/api/'+path,body);self.assertEqual(code,200,r);return r

    def test_title_full_rich_content_unicode_paging_and_no_writes(self):
        for i in range(22):self.api('fieldwork-note-create',dict(title='标题 '+str(i),body=[dict(text='a'*200),dict(text='调查 e\u0301',bold=True),dict(text='vidence',italic=True)]))
        before=self.api('undo-state');r=self.api('fieldwork-search?q=%C3%A9vidence&page=2');self.assertEqual(r['total'],22);self.assertEqual(len(r['items']),2);self.assertEqual(r['items'][0]['fields'][0]['field'],'body');self.assertEqual(self.api('undo-state'),before)
        self.assertEqual(self.api('fieldwork-search?q=标题')['total'],22)
        other=self.api('save-language',dict(name='Other',metadata={}))['id'];self.assertEqual(self.api('fieldwork-search?q=标题&language='+other)['total'],0)
