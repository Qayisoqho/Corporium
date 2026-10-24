"""Cross-module lifecycle checks for media, synonyms, classifications and notes."""
import unittest
import language_exchange
import media_engine
import server
import test_object_media
import test_relation_sequences


class RelatedAssetSequenceTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','health','imported','undo','word'):
        locals()[name]=getattr(test_relation_sequences.RelationSequenceTests,name)

    def package(self,name):
        exported=self.api('language-package-export',{})
        token=language_exchange.stage(server.DB,language_exchange.staged(server.DB,exported['token'],'export'),'import')
        return self.api('language-package-import',dict(token=token,name=name))['language_id']

    def test_media_and_synonym_after_colliding_variant_merge_package_delete_history(self):
        a=self.api('morpheme-save',dict(form='na',body=dict(gloss='source',variants=[dict(id='same',form='nan')])) )
        b=self.api('morpheme-save',dict(form='ta',body=dict(gloss='target',variants=[dict(id='same',form='tan')])) )
        x=self.word('synonym',['source'])
        self.api('synonym-save',dict(source=dict(kind='morpheme',id=a['id'],sense='@main'),target=dict(kind='lexeme',id=x['id'],sense=x['body']['usages'][0]['senses'][0]['id'])))
        audio=test_object_media.ObjectMediaTests.audio(self);expected=audio.read_bytes()
        self.assertEqual(test_object_media.ObjectMediaTests.add(self,a,audio,dict(target_id='same'),kind='morpheme')[0],200)
        a=self.api('morpheme?id='+a['id']);b=self.api('morpheme?id='+b['id'])
        self.api('morpheme-merge',dict(id=a['id'],revision=a['revision'],target_id=b['id'],target_revision=b['revision'],confirmed=True))

        def check(mid,xid,lid):
            m=self.api('morpheme?id='+mid+'&language='+lid)
            item=self.api('object-media?kind=morpheme&id='+mid+'&language='+lid)['items'][0]
            variant=next(v for v in m['body']['variants'] if v['id']==item['body']['target_id'])
            self.assertEqual(variant['form'],'nan');self.assertNotEqual(item['body']['target_id'],'same')
            self.assertEqual(media_engine.resolve(server.DB,item['asset']).read_bytes(),expected)
            link=self.api('synonyms?kind=lexeme&id='+xid+'&language='+lid)['links'][0]
            self.assertFalse(any(e['missing'] for e in link['ends']))
            end=next(e for e in link['ends'] if e['kind']=='morpheme')
            self.assertEqual(end['id'],mid);self.assertEqual(end['label'],'source');self.health()
        check(b['id'],x['id'],'ordos')
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo('redo')[0],200);check(b['id'],x['id'],'ordos')
        lid=self.package('Media copy')
        m=self.api('morphemes?language='+lid)['items'][0];newx=self.api('lexemes?language='+lid)['items'][0]
        check(m['id'],newx['id'],lid)
        self.assertEqual(self.undo(language=lid)[0],200);self.assertEqual(self.undo('redo',language=lid)[0],200);check(m['id'],newx['id'],lid)
        m=self.api('morpheme?id='+m['id']+'&language='+lid)
        self.api('morpheme-delete',dict(id=m['id'],revision=m['revision'],confirmed=True,_language=lid))
        self.assertTrue(any(e['missing'] for e in self.api('synonyms?kind=lexeme&id='+newx['id']+'&language='+lid)['links'][0]['ends']))
        self.assertEqual(self.undo(language=lid)[0],200);check(m['id'],newx['id'],lid)
        self.assertEqual(self.undo('redo',language=lid)[0],200);self.health();check(b['id'],x['id'],'ordos')

    def test_notes_copy_replace_writing_delete_exchange_undo_redo(self):
        a=self.api('writing-save',dict(name='Source writing',font='IPAPANNEW'))
        b=self.api('writing-save',dict(name='Replacement writing',font='Junicode'))
        n=self.api('fieldwork-note-create',dict(title='Field notes',body=[dict(text='na',type_id=a['id'],italic=True)]))
        clone=self.api('fieldwork-note-copy',dict(id=n['id'],revision=n['revision']))
        self.api('writing-delete',{**a,'confirmed':True,'replacement_id':b['id']})
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo('redo')[0],200)
        n=self.api('fieldwork-notes?id='+n['id'])
        self.api('fieldwork-note-delete',dict(id=n['id'],revision=n['revision'],confirmed=True))
        lid,_=self.imported(self.api('export-language?language=ordos'))
        data=self.api('fieldwork-notes?language='+lid);self.assertEqual(len(data['items']),1)
        imported=self.api('fieldwork-notes?language='+lid+'&id='+data['items'][0]['id'])
        typ=next(v for v in data['writing_types'] if v['id']==imported['body'][0]['type_id'])
        self.assertEqual(typ['name'],'Replacement writing');self.assertNotEqual(typ['id'],b['id'])
        self.assertEqual(imported['body'][0]['text'],'na');self.assertTrue(imported['body'][0]['italic'])
        for lang in ('ordos',lid):
            self.assertEqual(self.undo(language=lang)[0],200);self.health()
            self.assertEqual(self.undo('redo',language=lang)[0],200);self.health()
        self.assertEqual(self.api('fieldwork-notes?language='+lid+'&id='+imported['id'])['body'],imported['body'])
        self.assertEqual(self.api('fieldwork-notes?id='+clone['id'])['body'][0]['type_id'],b['id'])

    def test_homonym_synonym_category_subtree_delete_exchange_and_history(self):
        root=self.api('dict-org-class-save',dict(name='Root category'))
        leaf=self.api('dict-org-class-save',dict(name='Leaf category',parent_id=root['id']))
        a=self.word('bank',['river']);plan=self.api('homonym-preview?form=bank')
        b=self.api('lexeme-save',dict(headword='bank',body=dict(usages=[dict(senses=[dict(short_gloss='finance')])]),homonym_confirmation=plan['token']))
        a=self.api('lexeme?id='+a['id'])
        for row in (a,b):
            row['body']['semantic_classes']=[leaf['id']];self.api('lexeme-save',row)
        self.api('synonym-save',dict(source=dict(kind='lexeme',id=a['id'],sense=a['body']['usages'][0]['senses'][0]['id']),target=dict(kind='lexeme',id=b['id'],sense=b['body']['usages'][0]['senses'][0]['id'])))
        self.api('dict-org-class-delete',{**root,'children':'subtree'})
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.undo()[0],200)
        lid,_=self.imported(self.api('export-language?language=ordos'))
        words=self.api('lexemes?language='+lid)['items'];classes=self.api('dictionary-organization?language='+lid)['classes']
        self.assertEqual(sorted(w['body']['homonym_number'] for w in words),[1,2])
        newleaf=next(c for c in classes if c['name']=='Leaf category')
        self.assertNotEqual(newleaf['id'],leaf['id'])
        for row in words:self.assertEqual(row['body']['semantic_classes'],[newleaf['id']])
        link=self.api('synonyms?kind=lexeme&id='+words[0]['id']+'&language='+lid)['links'][0]
        self.assertEqual({e['id'] for e in link['ends']},{w['id'] for w in words});self.assertFalse(any(e['missing'] for e in link['ends']))
        self.assertEqual(self.undo(language=lid)[0],200);self.assertEqual(self.undo('redo',language=lid)[0],200);self.health()
        selected=self.api('lexeme?id='+words[0]['id']+'&language='+lid)
        self.api('lexeme-delete',dict(id=selected['id'],revision=selected['revision'],confirmed=True,_language=lid))
        self.assertEqual(self.undo(language=lid)[0],200);self.health()
        self.assertEqual(self.api('lexeme?id='+selected['id']+'&language='+lid)['body']['homonym_number'],selected['body']['homonym_number'])
