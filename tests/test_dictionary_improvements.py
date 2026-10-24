import unittest
import test_morpheme_registry
import grammar

class DictionaryImprovements(unittest.TestCase):
    for helper in ('setUp','tearDown','call','seed','entries','undo','fixture','link','assign'):
        locals()[helper]=getattr(test_morpheme_registry.MorphemeRegistryTests,helper)

    def word(self,name):
        return self.call('/api/lexeme-save',dict(headword=name,body=dict(usages=[dict(pos='名词',senses=[dict(short_gloss=name),dict(short_gloss='other')])])))[1]

    def test_sense_synonyms_bidirectional_undo_and_exchange(self):
        a=self.word('one');b=self.word('two')
        refs=[dict(kind='lexeme',id=x['id'],sense=x['body']['usages'][0]['senses'][0]['id']) for x in (a,b)]
        code,result=self.call('/api/synonym-save',dict(source=refs[0],target=refs[1]));self.assertEqual(code,200,result)
        backup=self.call('/api/backup')[1]
        self.assertEqual(len(backup['synonym_links']),1)
        import json,sqlite3
        from pathlib import Path
        from restore_backup import restore
        path=Path(self.temp.name)/'synonym-backup.json';path.write_text(json.dumps(backup),encoding='utf-8')
        restored=path.with_suffix('.sqlite3');restore(path,restored)
        from contextlib import closing
        with closing(sqlite3.connect(restored)) as db:self.assertEqual(db.execute('SELECT count(*) FROM synonym_links').fetchone()[0],1)
        for x in (a,b):self.assertEqual(len(self.call('/api/synonyms?language=ordos&kind=lexeme&id='+x['id'])[1]['links']),1)
        self.assertEqual(self.undo()[0],200)
        self.assertFalse(self.call('/api/synonyms?language=ordos&kind=lexeme&id='+a['id'])[1]['links'])
        self.undo('redo')
        self.assertEqual(self.call('/api/synonym-save',dict(source=refs[0],target=refs[0]))[0],400)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',dict(name='Copy',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/import-language',dict(_language=other,bundle=bundle))[0],200)
        result=self.call('/api/synonym-search?language='+other+'&kind=lexeme&q=one')[1]['items'][0]
        links=self.call('/api/synonyms?language='+other+'&kind=lexeme&id='+result['id'])[1]['links']
        self.assertEqual(len(links),1);self.assertFalse(any(r['missing'] for r in links[0]['ends']))
        self.assertNotEqual(result['id'],a['id'])
        self.assertEqual(self.call('/api/synonym-save',dict(_language=other,source=refs[0],target=refs[1]))[0],400)

    def test_morpheme_senses_synonyms_and_singleton_numbers(self):
        a=self.call('/api/morpheme-save',dict(form='a',body=dict(gloss='main',senses=[dict(gloss='second')])))[1]
        self.assertIsNone(a['display_number'])
        b=self.call('/api/morpheme-save',dict(form='a',body=dict(gloss='other')))[1]
        self.assertEqual(self.call('/api/morpheme?id='+a['id'])[1]['display_number'],1)
        source=dict(kind='morpheme',id=a['id'],sense=a['body']['senses'][0]['id']);target=dict(kind='morpheme',id=b['id'],sense='@main')
        self.assertEqual(self.call('/api/synonym-save',dict(source=source,target=target))[0],200)
        self.assertEqual(len(self.call('/api/synonyms?language=ordos&kind=morpheme&id='+b['id'])[1]['links']),1)
        self.assertEqual(self.call('/api/morpheme-delete',dict(id=b['id'],revision=b['revision']))[0],200)
        self.assertIsNone(self.call('/api/morpheme?id='+a['id'])[1]['display_number'])
        links=self.call('/api/synonyms?language=ordos&kind=morpheme&id='+a['id'])[1]['links']
        self.assertTrue(any(r['missing'] for r in links[0]['ends']))

    def test_explicit_morpheme_selection_and_unchanged_resave(self):
        _,x=self.fixture()
        m=self.call('/api/morpheme-save',dict(form='different-form',body=dict(gloss='chosen')))[1]
        assignments=[dict(analysis_id='a',component_id='c',morpheme_id=m['id'])]
        plan=self.call('/api/morpheme-save-preview',{**x,'assignments':assignments})[1]
        code,x=self.call('/api/lexeme-save',{**x,'morpheme_confirmation':plan['token'],'morpheme_assignments':assignments});self.assertEqual(code,200,x)
        item=next(r for r in self.call('/api/morpheme-components?id='+x['id'])[1]['items'] if r['component']['id']=='c')
        self.assertEqual(item['link']['morpheme_id'],m['id']);self.assertFalse(item['link']['review'])
        self.assertFalse(self.call('/api/morpheme-save-preview',x)[1]['items'])
        plan=self.call('/api/morpheme-save-preview',x)[1]
        self.assertEqual(self.call('/api/lexeme-save',{**x,'morpheme_confirmation':plan['token']})[0],200)
        self.assertFalse(self.call('/api/morpheme-components?id='+x['id'])[1]['items'][0]['link']['review'])

    def test_registered_script_tag_is_one_token(self):
        code,result=self.call('/api/grammar-save',dict(symbol='neg#sub[POT]',description='test'))
        self.assertEqual(code,200,result)
        tags=self.call('/api/grammar-tags?language=ordos')[1]
        lookup=grammar.index(tags)
        self.assertEqual(list(grammar.tokens('neg#sub[POT]-NOM','ordos',lookup)),['neg#sub[POT]'])
        self.assertEqual(list(grammar.tokens('neg#sub[POT]-NOM','ordos',lookup,candidates=True)),['neg#sub[POT]','NOM'])

    def test_merge_preserves_synonym_sense_identity(self):
        a=self.call('/api/morpheme-save',dict(form='a',body=dict(gloss='source meaning')))[1]
        b=self.call('/api/morpheme-save',dict(form='b',body=dict(gloss='target meaning')))[1]
        x=self.word('synonym')
        self.call('/api/synonym-save',dict(source=dict(kind='morpheme',id=a['id'],sense='@main'),target=dict(kind='lexeme',id=x['id'],sense=x['body']['usages'][0]['senses'][0]['id'])))
        code,result=self.call('/api/morpheme-merge',dict(id=a['id'],revision=a['revision'],target_id=b['id'],target_revision=b['revision'],confirmed=True))
        self.assertEqual(code,200,result)
        self.assertEqual(result['body']['gloss'],'target meaning')
        self.assertEqual(result['body']['senses'][0]['gloss'],'source meaning')
        links=self.call('/api/synonyms?language=ordos&kind=lexeme&id='+x['id'])[1]['links']
        self.assertFalse(any(r['missing'] for r in links[0]['ends']))

    def test_bulk_only_unique_skips_ambiguous_and_stale(self):
        from test_phonology import inventory
        cfg=inventory();cfg['tones'].append(dict(id='ambiguous',label='另调',matches=['21']))
        for reading in ('ma55','ma21','not-found'):
            self.call('/api/morpheme-save',dict(form=reading,body=dict(readings=[reading])))
        token=self.call('/api/homophone-phonology?language=ordos')[1]['token']
        cfg=self.call('/api/homophone-phonology-save',dict(action='settings',token=token,**cfg))[1]
        self.assertEqual(self.call('/api/homophone-phonology-save',dict(action='confirm_unique',token=cfg['token'],readings=['ma21']))[0],400)
        self.assertEqual(self.call('/api/homophone-phonology-save',dict(action='confirm_unique',token=cfg['token'],all=True))[0],200)
        saved=self.call('/api/homophone-phonology?language=ordos')[1]
        self.assertEqual(set(saved['assignments']),{'ma55'})
