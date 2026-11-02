import json
import copy
import base64
import io
import unittest
import zipfile
from pathlib import Path
import server
import annotations
import dictionary_layers
import test_sentence_dictionary
from restore_backup import restore

class DictionaryLayerTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo'):
        locals()[name]=getattr(test_sentence_dictionary.SentenceDictionaryTests,name)

    def api(self,path,body=None):
        if body is None and 'language=' not in path:path+=('&' if '?' in path else '?')+'language=ordos'
        status,result=self.call('/api/'+path,body);self.assertEqual(status,200,result);return result

    def layer(self,field='pos',**extra):
        result=self.api('layer-save',dict(name=field,font='Junicode',source='dictionary',dictionary_field=field,**extra))
        return next(l for l in self.api('layers') if l['id']==result['id'])

    def entry(self,**extra):
        body=dict(entry_type='root',tags=[dict(type='register',value='formal')],usages=[dict(id='noun',pos='N',senses=[dict(id='stone',short_gloss='stone')]),dict(id='verb',pos='V',senses=[dict(id='throw',short_gloss='throw',tags=[dict(type='register',value='spoken')])])])
        body.update(extra);return self.api('lexeme-save',dict(headword='mala',body=body))

    def link(self,src,x,key='@word',**extra):
        return self.api('segmentation-link',dict(**self.args(src),word=0,key=key,link_revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id='verb' if x.get('headword') else '@morpheme',sense_id='throw' if x.get('headword') else '@main',**extra))

    def projected(self,src,layer):
        d=self.api('annotations?kind='+src['kind']+'&id='+src['id'])
        return d,next(l for l in d['dictionary_layers'][d['words'][0]['id']] if l['id']==layer['id'])

    def test_asset_catalog_and_readonly_batch_endpoint(self):
        status,script=self.call('/dictionary-layers.js');self.assertEqual(status,200);self.assertIn('renderDictionaryLayer',script.decode() if isinstance(script,bytes) else script)
        fields=self.api('dictionary-layer-fields')['fields'];self.assertIn('tag:generation',[f['id'] for f in fields])
        layer=self.layer();x=self.entry();src=self.source('corpus',[('mala','old')]);self.link(src,x)
        from urllib.parse import quote
        batch=self.api('dictionary-layer-values?owners='+quote(json.dumps([src])))['items'][0]
        self.assertEqual(batch['values'][batch['words'][0]['id']][0]['value'],'V')

    def test_morpheme_segments_whole_priority_and_stale_link(self):
        layer=self.layer('short_gloss');x=self.entry();m=self.api('morpheme-save',dict(form='-na',body=dict(gloss='LOC')))
        for kind in ('corpus','independent'):
            src=self.source(kind,[('mala-na','stone-LOC')]);d=self.detail(src);keys=[unit['key'] for unit in d['body']['words'][0]['morphemes']]
            self.api('segmentation-link',dict(**self.args(src),word=0,key=keys[1],link_revision=0,lexeme_id=m['id'],lexeme_revision=m['revision'],usage_id='@morpheme',sense_id='@main'))
            self.assertEqual(self.projected(src,layer)[1]['value'],'— - LOC')
            self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',link_revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id='verb'))
            self.assertEqual(self.projected(src,layer)[1]['value'],'throw')
        src=self.source('corpus',[('mala','old')]);self.link(src,x)
        with server.connect(audit=False) as db:
            link=db.execute('SELECT id FROM lexical_links WHERE lexeme_id=? ORDER BY rowid DESC LIMIT 1',(x['id'],)).fetchone()[0]
            db.execute('INSERT INTO lexical_reviews VALUES(?,?)',(link,'Changed source'))
        self.assertEqual(self.projected(src,layer)[1]['segments'][0]['state'],'stale')

    def test_selected_classes_and_writing_definitions_update_without_occurrence_writes(self):
        semantic=self.api('dict-org-class-save',dict(name='Nature'))
        morph=self.api('class-save',dict(kind='morph',name='Class I',template=dict(title='Parts',slots=[])))
        x=self.entry(semantic_classes=[semantic['id']],word_structure=dict(memberships=[dict(class_id=morph['id'],usage_id='verb')]))
        layers=[self.layer('semantic_class'),self.layer('morph_class')];src=self.source('corpus',[('mala','old')]);self.link(src,x)
        self.assertEqual([self.projected(src,l)[1]['value'] for l in layers],['Nature','Class I'])
        writing=self.api('writing-save',dict(name='Script',font='Junicode'));layer=self.layer('writing:'+writing['id'])
        x=self.api('lexeme?id='+x['id']);x['body']['orthographies']=[dict(label='Script',type_id=writing['id'],font='Junicode',text='mala')];self.api('lexeme-save',x)
        self.api('writing-save',{**writing,'font':'serif'})
        self.assertEqual(self.projected(src,layer)[1]['font'],'serif')
        d=self.api('annotations?kind=corpus&id='+src['id']);self.assertEqual(d['cells'],[])
        with server.connect(audit=False) as db:
            body=json.loads(db.execute('SELECT body FROM entries WHERE id=?',(src['id'],)).fetchone()[0])
            self.assertFalse(any(l.get('derived') for w in body['words'] for l in w.get('extra_layers',[])))

    def test_both_sources_selected_usage_sense_types_and_live_update_without_cells(self):
        layers=[self.layer(f) for f in ('pos','short_gloss','entry_type','tag:register')];x=self.entry()
        for kind in ('corpus','independent'):
            src=self.source(kind,[('mala','old')]);self.link(src,x)
            for l,expected in zip(layers,['V','throw','root','formal / spoken']):
                d,value=self.projected(src,l);self.assertEqual(value['value'],expected);self.assertEqual(d['cells'],[])
                self.assertEqual(value['segments'][0]['refs'][0]['id'],x['id'])
            stored=self.api('backup')
            self.assertFalse(stored['annotation_cells'])
        x=self.api('lexeme?id='+x['id']);x['body']['usages'][1]['pos']='Changed'
        self.api('lexeme-save',x)
        self.assertEqual(self.projected(src,layers[0])[1]['value'],'Changed')
        self.undo();self.assertEqual(self.projected(src,layers[0])[1]['value'],'V')

    def test_manual_compatibility_and_readonly_enforced_on_server(self):
        src=self.source('corpus',[('mala','stone')]);layer=self.layer();d,value=self.projected(src,layer)
        self.assertEqual(value['segments'][0]['state'],'unlinked')
        payload=dict(kind=src['kind'],id=src['id'],revision=d['revision'],before=d['cells'],layers=d['layers'],cells=[dict(unit_id=d['words'][0]['id'],layer_id=layer['id'],value='forged')])
        self.assertEqual(self.call('/api/annotation-save',payload)[0],400)
        self.assertEqual(self.api('annotations?kind=corpus&id='+src['id'])['cells'],[])
        manual=self.api('layer-save',dict(name='Manual',font='Junicode'))
        manual=next(l for l in self.api('layers') if l['id']==manual['id']);self.assertEqual(manual['source'],'manual')
        d=self.api('annotations?kind=corpus&id='+src['id']);payload.update(revision=d['revision'],before=d['cells'],layers=d['layers'],cells=[dict(unit_id=d['words'][0]['id'],layer_id=manual['id'],value='manual')]);self.api('annotation-save',payload)
        self.assertEqual(self.call('/api/layer-save',{**manual,'source':'dictionary','dictionary_field':'pos'})[0],400)
        self.assertEqual(self.call('/api/layer-save',dict(name='Wrong',source='dictionary',dictionary_field='pos',anchor='ipa'))[0],400)

    def test_unlink_refreshes_projection_and_sentence_reference_is_not_word_link(self):
        layer=self.layer();x=self.entry();src=self.source('independent',[('mala','old')]);d=self.detail(src)
        self.api('example-save',dict(id=src['id'],revision=d['revision'],body={**d['body'],'targets':[dict(lexeme_id=x['id'])]}))
        self.assertEqual(self.projected(src,layer)[1]['segments'][0]['state'],'unlinked')
        src=self.source('corpus',[('mala','old')]);self.link(src,x)
        self.assertEqual(self.projected(src,layer)[1]['value'],'V')
        self.api('lexeme-unlink',dict(all=True,lexeme_id=x['id'],revision=x['revision'],confirmed=True))
        self.assertEqual(self.projected(src,layer)[1]['segments'][0]['state'],'unlinked')
        self.undo();self.assertEqual(self.projected(src,layer)[1]['value'],'V')

    def test_writing_font_search_exchange_and_backup_keep_live_definition(self):
        writing=self.api('writing-save',dict(name='Script',font='Junicode'))
        layer=self.layer('writing:'+writing['id']);x=self.entry(orthographies=[dict(label='Script',type_id=writing['id'],font='Junicode',text='WRITTEN')]);src=self.source('corpus',[('mala','old')]);self.link(src,x)
        self.assertEqual(self.projected(src,layer)[1]['value'],'WRITTEN')
        self.assertEqual(self.api('example-library?field=layer:'+layer['id']+'&q=WRITTEN')['total'],1)
        bundle=self.api('export-language');other=self.api('save-language',dict(name='Copy',metadata={}))['id'];self.api('import-language',dict(_language=other,bundle=bundle))
        copied=self.api('layers?lexical_language='+other)[0];types=self.api('writing-types?lexical_language='+other)['items'];self.assertEqual(copied['dictionary_field'],'writing:'+types[0]['id'])
        path=Path(self.temp.name)/'backup.json';path.write_text(json.dumps(self.api('backup')),encoding='utf8');dest=Path(self.temp.name)/'restored.sqlite3';restore(path,dest);server.DB=dest
        self.assertEqual(self.projected(src,layer)[1]['value'],'WRITTEN')

    def test_exports_snapshot_dictionary_values_and_no_annotation_cells(self):
        layer=self.layer('pos');x=self.entry();src=self.source('corpus',[('mala','old')]);self.link(src,x)
        with server.connect(audit=False) as db:text=db.execute('SELECT text_id FROM entries WHERE id=?',(src['id'],)).fetchone()[0]
        self.assertGreater(self.api('export-layer-status?id='+text)['count'],0)
        word=self.api('docx-export',dict(id=text));raw=base64.b64decode(word['data'])
        with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertIn('>V<',z.read('word/document.xml').decode())
        sheet=self.api('excel-export',dict(ids=[text]));raw=base64.b64decode(sheet['data'])
        with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertIn('>V<',z.read('xl/worksheets/sheet1.xml').decode())
        self.assertFalse(self.api('backup')['annotation_cells'])

    def test_usage_type_aliases_custom_type_rename_and_undo(self):
        layer=self.layer('tag:register');x=self.entry();src=self.source('corpus',[('mala','old')]);self.link(src,x)
        x=self.api('lexeme?id='+x['id']);x['body']['tags'][0]['type']='语域';x['body']['usages'][1]['senses'][0]['tags'][0]['type']='语域';self.api('lexeme-save',x)
        self.assertEqual(self.projected(src,layer)[1]['value'],'formal / spoken')
        fields=self.api('dictionary-layer-fields')['fields'];self.assertNotIn('tag:语域',[f['id'] for f in fields])
        c=next(c for c in self.api('classes') if c['kind']=='usage_tag' and c['name']=='语域')
        self.api('class-save',{**c,'name':'Style'})
        fresh=next(l for l in self.api('layers') if l['id']==layer['id']);self.assertEqual(fresh['dictionary_field'],'tag:Style')
        self.assertEqual(self.projected(src,fresh)[1]['value'],'formal / spoken')
        self.undo();self.assertEqual(self.projected(src,layer)[1]['value'],'formal / spoken')

    def test_writing_delete_replacement_and_missing_source(self):
        first=self.api('writing-save',dict(name='First',font='Junicode'));second=self.api('writing-save',dict(name='Second',font='serif'))
        layer=self.layer('writing:'+first['id']);x=self.entry(orthographies=[dict(label='First',type_id=first['id'],font='Junicode',text='script')]);src=self.source('corpus',[('mala','old')]);self.link(src,x)
        self.api('writing-delete',{**first,'replacement_id':second['id'],'confirmed':True})
        current=next(l for l in self.api('layers') if l['id']==layer['id']);self.assertEqual(current['dictionary_field'],'writing:'+second['id']);self.assertEqual(self.projected(src,current)[1]['value'],'script')
        x=self.api('lexeme?id='+x['id']);x['body']['orthographies']=[];self.api('lexeme-save',x)
        self.api('writing-delete',{**second,'confirmed':True})
        self.assertEqual(self.projected(src,current)[1]['segments'][0]['state'],'field_missing')
        self.api('layer-save',current)

    def test_inline_save_preserves_readonly_projection_without_storing_it(self):
        layer=self.layer();x=self.entry();src=self.source('corpus',[('mala','old')]);self.link(src,x)
        d=self.api('annotations?kind=corpus&id='+src['id']);body=copy.deepcopy(d['body']);body['ipa']='edited IPA'
        request=dict(kind='corpus',id=src['id'],revision=d['revision'],before=d['cells'],layers=d['layers'],cells=[],body=body,slot_ids=[w['id'] for w in d['words']])
        self.api('inline-save',request);fresh,value=self.projected(src,layer);self.assertEqual(value['value'],'V');self.assertEqual(fresh['body']['ipa'],'edited IPA')
        self.assertFalse(any(l.get('derived') for w in fresh['body']['words'] for l in w.get('extra_layers',[])))

    def test_analysis_materialization_uses_the_same_live_projection(self):
        import analysis_workspace
        layer=self.layer();x=self.entry();src=self.source('corpus',[('mala','old')]);self.link(src,x)
        with server.connect(audit=False) as db:
            records=dict(analysis_workspace.materialized_items(db,[dict(entry_id=src['id'])]));word=records[src['id']]['body']['words'][0]
            value=next(l for l in word['extra_layers'] if l['id']==layer['id']);self.assertEqual(value['value'],'V');self.assertTrue(value['unit_id'])
