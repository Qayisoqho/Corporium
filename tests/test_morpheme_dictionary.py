import json
import unittest
import test_lexicon
import test_component_links
import server
from pathlib import Path
from restore_backup import restore
import test_object_media

class MorphemeDictionaryTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    word=test_lexicon.LexiconTests.word
    undo=test_lexicon.LexiconTests.undo
    fixture=test_component_links.ComponentLinkTests.fixture
    audio=test_object_media.ObjectMediaTests.audio
    add_media=test_object_media.ObjectMediaTests.add

    def ok(self,path,body=None):
        code,value=self.call(path,body);self.assertEqual(code,200,value);return value

    def convert(self,x,target='@new',**fields):
        plan=self.ok('/api/lexeme-to-morpheme-preview',dict(id=x['id'],revision=x['revision']))
        return self.ok('/api/lexeme-to-morpheme',dict(id=x['id'],revision=x['revision'],token=plan['token'],target_id=target,**fields))

    def test_conversion_out_of_homonym_group_clears_remaining_word_number(self):
        a=self.ok('/api/lexeme-save',dict(headword='bank',body={}))
        plan=self.ok('/api/homonym-preview?form=bank&language=ordos')
        b=self.ok('/api/lexeme-save',dict(headword='bank',body={},homonym_confirmation=plan['token']))
        m=self.convert(b)
        self.assertIsNone(self.ok('/api/lexeme?id='+a['id'])['body']['homonym_number'])
        self.assertIsNone(m['display_number'])
        self.assertIsNone(self.ok('/api/lexeme?id='+m['id'])['body']['homonym_number'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.ok('/api/lexeme?id='+a['id'])['body']['homonym_number'],1)
        self.assertEqual(self.ok('/api/lexeme?id='+b['id'])['body']['homonym_number'],2)
        self.assertEqual(self.undo('redo')[0],200)
        self.assertIsNone(self.ok('/api/lexeme?id='+a['id'])['body']['homonym_number'])

    def test_native_direct_auto_matches_undo_and_color(self):
        e=self.seed('#pass([a], (([home-n],[家-GEN]),), [house])')
        m=self.ok('/api/morpheme-save',dict(form='n',body=dict(gloss='GEN',entry_type='affix',affix_function='inflection',affix_position='suffix')))
        candidates=self.ok('/api/lexemes?targets=all&q=n')['items']
        self.assertEqual(candidates[0]['target_kind'],'morpheme')
        self.assertEqual(self.ok('/api/lexemes')['total'],0)
        plan=self.ok('/api/lexeme-auto-preview?language=ordos')
        self.assertEqual(len(plan['matches']),1,plan)
        self.ok('/api/lexeme-auto-link',dict(token=plan['token']))
        self.assertEqual(self.ok('/api/lexeme-examples?id='+m['id'])['total'],1)
        colors=self.entries()[0]['words'][0]['morph_colors'];self.assertEqual(colors[-1]['tone'],'affix')
        self.assertEqual(self.call('/api/morpheme-delete',dict(id=m['id'],revision=m['revision']))[0],400)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.ok('/api/lexeme-examples?id='+m['id'])['total'],0)
        self.assertEqual(self.undo('redo')[0],200)

    def test_conversion_same_id_retains_meaning_independent_refs_and_undo(self):
        e=self.seed();x=self.word()
        u=self.ok('/api/unit-dictionary?id='+e['words'][0]['unit_id'])
        self.ok('/api/lexeme-link',dict(unit_id=u['id'],unit_revision=u['revision'],entry_revision=u['entry_revision'],lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=x['body']['usages'][0]['id'],sense_id=x['body']['usages'][0]['senses'][0]['id']))
        ex=self.ok('/api/example-save',dict(body=dict(words=[dict(form='home',gloss='家')],targets=[dict(lexeme_id=x['id'])])))
        m=self.convert(x,entry_type='root')
        self.assertEqual(m['id'],x['id']);self.assertEqual(m['body']['usages'],x['body']['usages'])
        self.assertEqual(self.ok('/api/lexeme?id='+m['id'])['target_kind'],'morpheme')
        self.assertEqual(self.ok('/api/lexeme-examples?id='+m['id'])['total'],1)
        self.assertEqual(len(self.ok('/api/dictionary-examples?id='+m['id'])),1)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.ok('/api/lexeme?id='+x['id'])['target_kind'],'lexeme')
        self.assertEqual(self.undo('redo')[0],200)
        m=self.ok('/api/morpheme?id='+m['id']);m['body']['gloss']='房屋'
        m=self.ok('/api/morpheme-save',m)
        self.assertEqual(m['body']['usages'][0]['senses'][0]['short_gloss'],'房屋')

    def test_homonym_choice_and_merge_retarget_distinct_meanings(self):
        x=self.word();peer=self.ok('/api/morpheme-save',dict(form='home',body=dict(gloss='故乡')))
        self.ok('/api/example-save',dict(body=dict(words=[dict(form='home',gloss='家')],targets=[dict(lexeme_id=x['id'],usage_id=x['body']['usages'][0]['id'],sense_id=x['body']['usages'][0]['senses'][0]['id'])])))
        plan=self.ok('/api/lexeme-to-morpheme-preview',x)
        self.assertEqual(self.call('/api/lexeme-to-morpheme',dict(id=x['id'],revision=x['revision'],token=plan['token']))[0],400)
        m=self.convert(x,peer['id']);self.assertEqual(m['body']['gloss'],'故乡')
        self.assertEqual(len(m['body']['usages']),len(x['body']['usages'])+1)
        self.assertEqual(len(self.ok('/api/dictionary-examples?id='+m['id'])),1)
        m['body']['notes']='edit after merge';m=self.ok('/api/morpheme-save',m)
        self.assertEqual(len(m['body']['usages']),len(x['body']['usages'])+1)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.ok('/api/dictionary-counts'),dict(lexemes=1,morphemes=1))

    def test_exchange_native_links_and_converted_structure(self):
        e,x=self.fixture();m=self.convert(x)
        native=self.ok('/api/morpheme-save',dict(form='home',body=dict(gloss='家')))
        ex=self.ok('/api/example-save',dict(body=dict(words=[dict(form='home',gloss='家')],targets=[dict(lexeme_id=native['id'],usage_id='@morpheme',sense_id='@main')])))
        bundle=self.ok('/api/export-language?language=ordos')
        other=self.ok('/api/save-language',dict(name='Copy',metadata={}))['id']
        self.ok('/api/import-language',dict(_language=other,bundle=bundle))
        items=self.ok('/api/morphemes?language='+other)['items'];self.assertEqual(len(items),2)
        for item in items:self.ok('/api/lexeme?id='+item['id']+'&language='+other)
        self.assertTrue(any(len(self.ok('/api/dictionary-examples?id='+i['id']+'&language='+other)) for i in items))

    def test_conversion_media_synonyms_structure_and_backup_history(self):
        e=self.seed();x=self.word()
        semantic=self.ok('/api/dict-org-class-save',dict(name='形态功能'))
        writing=self.ok('/api/writing-save',dict(name='本字',font='Junicode'))
        x['body']['semantic_classes']=[semantic['id']]
        x['body']['orthographies']=[dict(type_id=writing['id'],label='本字',text='家',font='Junicode')]
        x['body']['word_structure']={'analyses':[dict(id='analysis',title='共时',components=[dict(id='component',form='home',gloss='家')])]}
        x=self.ok('/api/lexeme-save',x)
        uid=e['words'][0]['morphemes'][0]['unit_id'];u=self.ok('/api/unit-dictionary?id='+uid)
        self.ok('/api/lexeme-link',dict(unit_id=uid,unit_revision=u['revision'],entry_revision=u['entry_revision'],lexeme_id=x['id'],lexeme_revision=x['revision'],component_selection=dict(analysis_id='analysis',component_id='component'),form_id=x['body']['variants'][0]['id']))
        y=self.ok('/api/lexeme-save',dict(headword='house',body=dict(usages=[dict(senses=[dict(short_gloss='住所')])],relation=dict(base_id=x['id'],type='derivation'))))
        self.ok('/api/synonym-save',dict(source=dict(kind='lexeme',id=x['id'],sense=x['body']['usages'][0]['senses'][0]['id']),target=dict(kind='lexeme',id=y['id'],sense=y['body']['usages'][0]['senses'][0]['id'])))
        code,media=self.add_media(x,self.audio(),dict(target_id=x['body']['variants'][0]['id']));self.assertEqual(code,200,media)
        peer=self.ok('/api/morpheme-save',dict(form=x['headword'],body=dict(gloss='故乡')))
        merged=self.convert(x,peer['id'])
        self.assertEqual(len(self.ok('/api/object-media?kind=morpheme&id='+merged['id'])['items']),1)
        self.assertEqual(self.ok('/api/lexeme?id='+y['id'])['body']['relation']['base_id'],merged['id'])
        link=self.ok('/api/unit-dictionary?id='+uid)['link'];self.assertFalse(link['component_review'])
        self.assertEqual(link['lexeme_id'],merged['id'])
        self.assertFalse(self.ok('/api/synonyms?kind=morpheme&id='+merged['id'])['links'][0]['ends'][0].get('missing'))
        backup=Path(self.temp.name)/'backup.json';backup.write_text(json.dumps(self.ok('/api/backup')),encoding='utf-8')
        restored=Path(self.temp.name)/'restored.sqlite3';restore(backup,restored);server.DB=restored
        self.assertEqual(self.ok('/api/lexeme?id='+merged['id'])['target_kind'],'morpheme')
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.ok('/api/lexeme?id='+x['id'])['target_kind'],'lexeme')
        self.assertEqual(len(self.ok('/api/object-media?kind=lexeme&id='+x['id'])['items']),1)
        self.assertEqual(self.undo('redo')[0],200)
        import project_backup,language_exchange
        with server.connect(audit=False) as db:package=project_backup.prepare(db,server.DB)
        snapshot=Path(self.temp.name)/'snapshot.sqlite3';project_backup.restore(language_exchange.staged(server.DB,package['token'],'project-backup'),snapshot)
        server.DB=snapshot
        self.assertEqual(self.ok('/api/unit-dictionary?id='+uid)['link']['lexeme_id'],merged['id'])
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo('redo')[0],200)
        bundle=self.ok('/api/export-language?language=ordos')
        other=self.ok('/api/save-language',dict(name='Complex copy',metadata={}))['id']
        self.ok('/api/import-language',dict(_language=other,bundle=bundle))
        copied=next(r for r in self.ok('/api/morphemes?language='+other)['items'] if r['form']==merged['form'])
        self.assertNotEqual(copied['body']['semantic_classes'],[semantic['id']])
        self.assertEqual(copied['body']['writings'][0]['text'],'家')
        self.assertNotEqual(copied['body']['writings'][0]['type_id'],writing['id'])
        self.assertEqual(len(self.ok('/api/object-media?kind=morpheme&id='+copied['id']+'&language='+other)['items']),1)
        for link in self.ok('/api/synonyms?kind=morpheme&id='+copied['id']+'&language='+other)['links']:
            self.assertFalse(any(e.get('missing') for e in link['ends']))

    def test_stale_preview_invalid_metadata_and_linked_sense_removal(self):
        x=self.word();plan=self.ok('/api/lexeme-to-morpheme-preview',x)
        x['body']['notes']='other window';x=self.ok('/api/lexeme-save',x)
        self.assertEqual(self.call('/api/lexeme-to-morpheme',dict(id=x['id'],revision=x['revision'],token=plan['token'],target_id='@new'))[0],400)
        m=self.ok('/api/morpheme-save',dict(form='a',body=dict(gloss='A',senses=[dict(id='extra',gloss='B')])) )
        ex=self.ok('/api/example-save',dict(body=dict(words=[dict(form='a',gloss='B')],targets=[dict(lexeme_id=m['id'],usage_id='@morpheme',sense_id='extra')])))
        body=dict(m['body']);body['senses']=[]
        self.assertEqual(self.call('/api/morpheme-save',dict(id=m['id'],revision=m['revision'],form='a',body=body))[0],400)
        self.assertEqual(self.ok('/api/morpheme?id='+m['id'])['revision'],m['revision'])
        self.assertEqual(self.call('/api/morpheme-save',dict(form='b',body=dict(entry_type='no-such-type')))[0],400)

if __name__=='__main__':unittest.main()
