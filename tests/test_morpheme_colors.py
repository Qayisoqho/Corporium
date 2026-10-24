import unittest
import test_segmentation
import corpus
import morpheme_colors
import json
from urllib.parse import urlencode
import server
from restore_backup import restore
from contextlib import closing
import sqlite3


class MorphemeColorTests(unittest.TestCase):
    for helper in ('setUp','tearDown','call','seed','entries'):
        locals()[helper]=getattr(test_segmentation.SegmentationTests,helper)

    def api(self,path,body=None):
        code,result=self.call('/api/'+path,body);self.assertEqual(code,200,result);return result

    def test_raw_ranges_preserve_codepoint_offsets_scripts_and_escapes(self):
        for raw in ['𐐀á#sub[21]-ŋ','“ta<ŋ>ri-na”',r'a\[b\]-n','  foo#sub[x]  ']:
            text,mapping=morpheme_colors.plain_map(raw)
            self.assertEqual(text,corpus.clean(raw));self.assertEqual(len(mapping),len(text))
            self.assertTrue(all(0<=a<b<=len(raw) for a,b in mapping))

    def test_one_corpus_card_does_not_expand_unrelated_morpheme_bodies(self):
        self.api('import',dict(title='颜色',content='#pass([word], (([word],[note]),), [颜色])'))
        e=self.api('entries')['items'][0]
        x=self.api('lexeme-save',dict(headword='word',body=dict(entry_type='affix')))
        u=self.api('unit-dictionary?id='+e['words'][0]['unit_id'])
        self.api('lexeme-link',dict(unit_id=u['id'],unit_revision=u['revision'],entry_revision=u['entry_revision'],revision=0,lexeme_id=x['id'],lexeme_revision=x['revision']))
        with server.connect(audit=False) as db:
            db.executemany('INSERT INTO morphemes VALUES(?,?,?,?,?,1)',[(f'm{i}','ordos',f'unused{i}',1,'{"gloss":"unused"}') for i in range(50)])
            def unexpected(*args):raise AssertionError('unrelated native morphemes must not be projected')
            db.create_function('json_set',-1,unexpected)
            body=corpus.analyze(dict(ipa='',translation='',words=[dict(form='word',gloss='note')]))
            morpheme_colors.attach(db,body,'corpus',e['id'],'ordos')
            self.assertEqual(body['words'][0]['morph_colors'][0]['tone'],'affix')

    def test_corpus_and_independent_share_actual_affix_clitic_links(self):
        self.api('import',dict(title='颜色',content='#gloss([root-na=ke], (("root-na=ke", [root-PST=CL]),), [颜色])'))
        entry=self.api('entries')['items'][0]
        affix=self.api('lexeme-save',dict(headword='-na',body=dict(entry_type='affix')))
        clitic=self.api('lexeme-save',dict(headword='=ke',body=dict(entry_type='clitic')))
        def link(index,x):
            current=self.api('entries')['items'][0];uid=current['words'][0]['morphemes'][index]['unit_id'];u=self.api('unit-dictionary?id='+uid)
            self.api('lexeme-link',dict(unit_id=uid,unit_revision=u['revision'],entry_revision=u['entry_revision'],revision=0,lexeme_id=x['id'],lexeme_revision=x['revision']))
        link(1,affix);link(2,clitic)
        current=self.api('entries')['items'][0];colors=current['words'][0]['morph_colors']
        self.assertEqual([m['tone'] for m in colors],['base','affix','clitic'])
        self.assertEqual(colors[1]['form'],[[5,7]]);self.assertEqual(colors[1]['gloss'],[[5,8]])
        example=self.api('example-save',dict(body=dict(ipa='root-na=ke',words=[dict(form='root-na=ke',gloss='root-PST=CL')],translation='颜色')))
        d=self.api('segmentation?kind=independent&id='+example['id'])
        for key,x in [('1:host',affix),('2:host',clitic)]:
            self.api('segmentation-link',dict(kind='independent',id=example['id'],revision=d['revision'],word=0,key=key,lexeme_id=x['id'],lexeme_revision=x['revision']))
            d=self.api('segmentation?kind=independent&id='+example['id'])
        self.assertEqual([m['tone'] for m in d['body']['words'][0]['morph_colors']],['base','affix','clitic'])
        run=self.api('analysis-run',dict(query=dict(conditions=[dict(field='form',value='root-na=ke',mode='exact')],scope={})))
        result=self.api('analysis-result?language=ordos&id='+run['id'])
        self.assertFalse(result['stale'])
        for item in result['items']:
            self.assertEqual([m['tone'] for m in item['record']['body']['words'][0]['morph_colors']],['base','affix','clitic'])

    def test_infix_and_group_ranges_have_corresponding_gloss_fragments(self):
        body=corpus.analyze(dict(ipa='',translation='',words=[dict(form='ta<ŋ>ri-na',gloss='打<neg#sub[POT]>过-PST')]))
        w=body['words'][0];infix=next(m for m in w['morphemes'] if m['kind']=='infix')
        _,mapping=morpheme_colors.plain_map(w['gloss']);self.assertEqual(morpheme_colors.ranges(infix['gloss_fragments'],mapping),[[2,14]])

    def test_only_saved_dictionary_type_controls_color(self):
        roles=['affix','clitic','infix','circumfix','connector','multipart']
        for entry_type in [*roles,'morpheme','unspecified','lexeme','root','stem','expression']:
            for kind in ('simple','infix','circumfix','unspecified'):
                for boundary in ('-','=','+',''):
                    for headword in ('na','-na','=na','na-','na…ta'):
                        with self.subTest(entry_type=entry_type,kind=kind,boundary=boundary,headword=headword):
                            self.assertEqual(morpheme_colors.tone(dict(kind=kind,boundary=boundary),dict(entry_type=entry_type,headword=headword)),entry_type if entry_type in roles else 'base')
        self.assertEqual(morpheme_colors.tone(dict(kind='infix',boundary='='),None),'base')

    def test_changing_linked_entry_type_refreshes_both_sources_and_undo(self):
        self.api('import',dict(title='词缀配色',content='#pass([], (([root=na],[root=npst]),), [])'))
        entry=self.api('entries')['items'][0]
        x=self.api('lexeme-save',dict(headword='-nAA',body=dict(entry_type='clitic',usages=[dict(senses=[dict(short_gloss='npst')])])))
        uid=entry['words'][0]['morphemes'][1]['unit_id'];u=self.api('unit-dictionary?id='+uid)
        self.api('lexeme-link',dict(unit_id=uid,unit_revision=u['revision'],entry_revision=u['entry_revision'],revision=0,lexeme_id=x['id'],lexeme_revision=x['revision']))
        example=self.api('example-save',dict(body=dict(ipa='root=na',words=[dict(form='root=na',gloss='root=npst')],translation='')))
        d=self.api('segmentation?kind=independent&id='+example['id'])
        self.api('segmentation-link',dict(kind='independent',id=example['id'],revision=d['revision'],word=0,key='1:host',lexeme_id=x['id'],lexeme_revision=x['revision']))
        def check(expected):
            for kind,rid in [('corpus',entry['id']),('independent',example['id'])]:
                w=self.api('segmentation?kind='+kind+'&id='+rid)['body']['words'][0]
                self.assertEqual(w['morph_colors'][1]['tone'],expected)
                self.assertTrue(w['morph_colors'][1]['linked'])
                self.assertEqual(w['morph_colors'][1]['form'],[[5,7]])
                self.assertEqual(w['morph_colors'][1]['gloss'],[[5,9]])
            self.assertEqual(self.api('entries')['items'][0]['words'][0]['morph_colors'][1]['tone'],expected)
        check('clitic')
        self.api('lexeme-save',dict(id=x['id'],revision=x['revision'],headword=x['headword'],body={**x['body'],'entry_type':'affix'}))
        check('affix')
        self.api('undo',dict(generation=self.api('undo-state')['generation']))
        check('clitic')
        self.api('redo',dict(generation=self.api('undo-state')['generation']))
        check('affix')

    def test_npst_name_alone_does_not_substitute_for_a_saved_link(self):
        self.api('import',dict(title='未关联词缀',content='#pass([], (([root-nAA],[root-npst]),), [])'))
        x=self.api('lexeme-save',dict(headword='-nAA',body=dict(entry_type='unspecified',usages=[dict(senses=[dict(short_gloss='npst')])])))
        w=self.api('entries')['items'][0]['words'][0]
        self.assertEqual(w['morph_colors'][1]['tone'],'base')
        self.assertFalse(w['morph_colors'][1]['linked'])
        uid=w['morphemes'][1]['unit_id'];u=self.api('unit-dictionary?id='+uid)
        self.api('lexeme-link',dict(unit_id=uid,unit_revision=u['revision'],entry_revision=u['entry_revision'],revision=0,lexeme_id=x['id'],lexeme_revision=x['revision']))
        color=self.api('entries')['items'][0]['words'][0]['morph_colors'][1]
        self.assertTrue(color['linked']);self.assertEqual(color['tone'],'base')
        self.api('lexeme-save',dict(id=x['id'],revision=x['revision'],headword=x['headword'],body={**x['body'],'entry_type':'affix'}))
        self.assertEqual(self.api('entries')['items'][0]['words'][0]['morph_colors'][1]['tone'],'affix')

    def test_every_color_type_can_be_saved_and_used_across_different_separators(self):
        roles=['morpheme','affix','clitic','infix','circumfix','connector','multipart','unspecified']
        form,gloss='root-a=b+c','root-A=B+C'
        self.api('import',dict(title='严格类型配色',content='#pass([], ((['+form+'],['+gloss+']),), [])'))
        x=self.api('lexeme-save',dict(headword='-a-',body=dict(entry_type='unspecified')))
        for index in range(1,4):
            w=self.api('entries')['items'][0]['words'][0];uid=w['morphemes'][index]['unit_id'];u=self.api('unit-dictionary?id='+uid)
            self.api('lexeme-link',dict(unit_id=uid,unit_revision=u['revision'],entry_revision=u['entry_revision'],revision=0,lexeme_id=x['id'],lexeme_revision=x['revision']))
        example=self.api('example-save',dict(body=dict(ipa=form,words=[dict(form=form,gloss=gloss)],translation='')))
        for index in range(1,4):
            d=self.api('segmentation?kind=independent&id='+example['id'])
            self.api('segmentation-link',dict(kind='independent',id=example['id'],revision=d['revision'],word=0,key=str(index)+':host',lexeme_id=x['id'],lexeme_revision=x['revision']))
        for role in roles:
            with self.subTest(role=role):
                x=self.api('lexeme-save',dict(id=x['id'],revision=x['revision'],headword=x['headword'],body={**x['body'],'entry_type':role}))
                self.assertEqual(x['body']['entry_type'],role)
                expected='base' if role in ('morpheme','unspecified') else role
                for w in [self.api('entries')['items'][0]['words'][0],self.api('segmentation?kind=independent&id='+example['id'])['body']['words'][0]]:
                    self.assertEqual([c['tone'] for c in w['morph_colors']],['base',expected,expected,expected])
                    self.assertTrue(all(c['linked'] for c in w['morph_colors'][1:]))
        self.assertEqual(self.api('lexeme?id='+x['id'])['body']['entry_type'],'unspecified')

    def test_new_types_support_chinese_search_batch_undo_and_exchange(self):
        labels=dict(morpheme='普通语素',affix='词缀',clitic='附着成分',infix='中缀',circumfix='环缀',connector='连接成分',multipart='其他多部分语素')
        words=[]
        for kind,label in labels.items():
            x=self.api('lexeme-save',dict(headword='form-'+kind,body=dict(entry_type=kind)));words.append(x)
            spec=dict(conditions=[dict(field='entry_type',op='exact',value=label)])
            result=self.api('lexemes?'+urlencode(dict(language='ordos',search=json.dumps(spec))))
            self.assertEqual([r['id'] for r in result['items']],[x['id']])
        b=dict(items=[dict(id=x['id'],revision=x['revision']) for x in words[:2]],operations=[dict(field='entry_type',value='connector')])
        p=self.api('dictionary-batch-preview',b)
        self.assertEqual(len(p['conflicts']),2)
        self.assertEqual(self.call('/api/dictionary-batch-apply',{**b,'token':p['token']})[0],400)
        self.api('dictionary-batch-apply',{**b,'token':p['token'],'overwrite':True})
        for x in words[:2]:self.assertEqual(self.api('lexeme?id='+x['id'])['body']['entry_type'],'connector')
        self.api('undo',dict(generation=self.api('undo-state')['generation']))
        for x in words[:2]:self.assertEqual(self.api('lexeme?id='+x['id'])['body']['entry_type'],x['body']['entry_type'])
        bundle=self.api('export-language?language=ordos');other=self.api('save-language',dict(name='类型交换',metadata={}))['id']
        self.api('import-language',dict(bundle=bundle,_language=other))
        copied=self.api('lexemes?language='+other)['items']
        self.assertEqual({x['headword']:x['body']['entry_type'] for x in copied},{x['headword']:x['body']['entry_type'] for x in words})
        source=server.DB.parent/'types-backup.json';dest=server.DB.parent/'restored-types.sqlite3'
        source.write_text(json.dumps(self.api('backup')),encoding='utf-8');restore(source,dest)
        with closing(sqlite3.connect(dest)) as db:
            self.assertEqual({json.loads(r[0])['entry_type'] for r in db.execute("SELECT body FROM lexemes WHERE language_id='ordos'")},set(labels))


if __name__=='__main__':unittest.main()
