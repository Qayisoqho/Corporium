import json
import sqlite3
import unittest
from pathlib import Path
import server
import annotations
import dictionary_data
import ui_localization
from restore_backup import restore
import test_server
import test_lexicon
import test_dictionary_manager
import test_annotations


class DisplaySpacingTests(unittest.TestCase):
    setUp = test_server.APITests.setUp
    tearDown = test_server.APITests.tearDown
    call = test_server.APITests.call
    seed = test_lexicon.LexiconTests.seed
    word = test_lexicon.LexiconTests.word
    undo = test_lexicon.LexiconTests.undo
    example = test_dictionary_manager.DictionaryManagerTests.example
    annotate = test_annotations.AnnotationTests.annotate

    entries = test_lexicon.LexiconTests.entries

    def layer(self, **extra):
        status, saved = self.call('/api/layer-save', dict(name='Tier', font='Junicode', **extra))
        self.assertEqual(status, 200, saved)
        return next(l for l in self.call('/api/layers?language=ordos')[1] if l['id']==saved['id'])

    def test_spacing_asset_is_served_before_management_controls(self):
        status,source=self.call('/line-spacing.js')
        self.assertEqual(status,200);self.assertIn('CorporiumLineSpacing',source.decode() if isinstance(source,bytes) else source)
        status,page=self.call('/')
        if isinstance(page,bytes):page=page.decode()
        self.assertLess(page.index('/line-spacing.js'),page.index('/dictionary-manager.js'))

    def writing(self, **extra):
        status, saved = self.call('/api/writing-save', dict(name='Script', font='Junicode', **extra))
        self.assertEqual(status, 200, saved)
        return saved

    def test_internal_tier_spacing_roundtrip_validation_and_undo(self):
        layer=self.layer(line_spacing=-25)
        self.assertEqual(layer['line_spacing'],-25)
        status,saved=self.call('/api/layer-save',{**layer,'line_spacing':37.5});self.assertEqual(status,200,saved)
        current=lambda:self.call('/api/layers?language=ordos')[1][0]
        self.assertEqual(current()['line_spacing'],37.5)
        self.assertEqual(self.undo()[0],200);self.assertEqual(current()['line_spacing'],-25)
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(current()['line_spacing'],37.5)
        for value in (-301,301,True,'12',float('inf')):
            status,saved=self.call('/api/layer-save',{**current(),'line_spacing':value});self.assertEqual(status,400,saved)
        status,saved=self.call('/api/layer-save',{**current(),'name':'Renamed'});self.assertEqual(status,200,saved)
        self.assertEqual(current()['line_spacing'],37.5)
        status,saved=self.call('/api/layer-save',{**current(),'line_spacing':None});self.assertEqual(status,200,saved)
        self.assertIsNone(current()['line_spacing'])

    def test_default_null_explicit_zero_and_partial_updates_are_distinct(self):
        for action, record in [('layer', self.layer()), ('writing', self.writing())]:
            self.assertIsNone(record['space_before']); self.assertIsNone(record['space_after'])
            status, saved = self.call('/api/'+action+'-save', {**record, 'space_before':0, 'space_after':37.5})
            self.assertEqual(status, 200, saved)
            if action=='layer': saved=self.call('/api/layers?language=ordos')[1][0]
            self.assertEqual(saved['space_before'],0);self.assertEqual(saved['space_after'],37.5)
            request={k:v for k,v in saved.items() if not k.startswith('space_')}
            request['name']='Renamed'
            status, saved=self.call('/api/'+action+'-save',request);self.assertEqual(status,200,saved)
            if action=='layer': saved=self.call('/api/layers?language=ordos')[1][0]
            self.assertEqual(saved['space_after'],37.5)
            status, saved=self.call('/api/'+action+'-save',{**saved,'space_before':None,'space_after':None})
            self.assertEqual(status,200,saved)
            if action=='layer': saved=self.call('/api/layers?language=ordos')[1][0]
            self.assertIsNone(saved['space_before']);self.assertIsNone(saved['space_after'])

    def test_invalid_spacing_is_atomic_and_localized(self):
        for action, record in [('layer',self.layer()),('writing',self.writing())]:
            before=self.call('/api/undo-state')[1]['workspace_revision']
            for value in [-301,301,True,'20',[],float('nan'),float('inf')]:
                status, result=self.call('/api/'+action+'-save',{**record,'space_after':value,'name':'Must not save'})
                self.assertEqual(status,400,(action,value,result))
                self.assertIn('-300–300',result['error'])
            self.assertEqual(self.call('/api/undo-state')[1]['workspace_revision'],before)
        self.assertNotIn('行前',ui_localization.message('行前、行后间距须留空或填写 -300–300 的数字（%）','en'))

    def test_writing_projection_updates_all_references_without_editing_content(self):
        record=self.word();t=self.writing(space_before=75,space_after=25)
        record['body']['orthographies']=[dict(type_id=t['id'],label='Script',font='Junicode',text='a̋ŋ')]
        self.assertEqual(self.call('/api/lexeme-save',record)[0],200)
        current=lambda:self.call('/api/lexeme?id='+record['id'])[1]['body']['orthographies'][0]
        self.assertEqual(current()['space_before'],75)
        with server.connect() as db: before=db.execute('SELECT body FROM lexemes WHERE id=?',(record['id'],)).fetchone()[0]
        self.assertEqual(self.call('/api/writing-save',{**t,'space_before':150})[0],200)
        self.assertEqual(current()['space_before'],150)
        with server.connect() as db: self.assertEqual(db.execute('SELECT body FROM lexemes WHERE id=?',(record['id'],)).fetchone()[0],before)
        self.assertEqual(self.undo()[0],200);self.assertEqual(current()['space_before'],75)
        generation=self.call('/api/undo-state')[1]['generation']
        self.assertEqual(self.call('/api/redo',dict(generation=generation))[0],200)
        self.assertEqual(current()['space_before'],150)

    def test_both_sentence_kinds_and_all_layer_positions_preserve_spacing(self):
        corpus=self.seed();ind=self.example(self.word())
        word=self.layer(space_before=50,space_after=0)
        self.annotate('corpus',corpus,word);self.annotate('independent',ind,word)
        self.layer(anchor='ipa',space_before=100,space_after=25)
        self.layer(anchor='translation',space_before=0,space_after=150)
        with server.connect() as db:
            for kind,record in [('corpus',corpus),('independent',ind)]:
                body=annotations.owner(db,kind,record['id'])[0]
                projected=annotations.enrich(db,body,kind,record['id'])
                self.assertEqual(projected['words'][0]['extra_layers'][0]['space_before'],50)
                rows={l['anchor']:l for l in projected['sentence_layers']}
                self.assertEqual(rows['ipa']['space_after'],25)
                self.assertEqual(rows['translation']['space_after'],150)

    def test_exchange_backup_and_other_language_isolation(self):
        layer=self.layer(space_before=-12.5,space_after=75,line_spacing=-25);t=self.writing(space_before=200,space_after=0)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/import-language',dict(_language=other,bundle=bundle))[0],200)
        copied=self.call('/api/layers?language='+other)[1][0]
        written=self.call('/api/writing-types?language='+other)[1]['items'][0]
        self.assertEqual(copied['space_before'],-12.5);self.assertEqual(written['space_after'],0)
        self.assertEqual(copied['line_spacing'],-25)
        self.assertNotEqual(copied['id'],layer['id']);self.assertNotEqual(written['id'],t['id'])
        self.assertEqual(self.call('/api/layer-save',{**copied,'space_after':300,'_language':other})[0],200)
        self.assertEqual(self.call('/api/layers?language=ordos')[1][0]['space_after'],75)
        path=Path(self.temp.name)/'backup.json';path.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8')
        destination=Path(self.temp.name)/'restored.sqlite3';restore(path,destination);server.DB=destination
        self.assertEqual(self.call('/api/layers?language='+other)[1][0]['space_after'],300)
        self.assertEqual(self.call('/api/layers?language='+other)[1][0]['line_spacing'],-25)
        self.assertEqual(self.call('/api/writing-types?language='+other)[1]['items'][0]['space_before'],200)

    def test_old_schema_upgrade_keeps_rows_and_default_layout(self):
        with sqlite3.connect(':memory:') as db:
            db.row_factory=sqlite3.Row
            db.execute('CREATE TABLE writing_types(id TEXT PRIMARY KEY,language_id TEXT,name TEXT,font TEXT,position INTEGER,revision INTEGER)')
            db.execute("INSERT INTO writing_types VALUES('old','ordos','Old','Junicode',2,4)")
            db.execute("CREATE TABLE annotation_layers(id TEXT PRIMARY KEY,language_id TEXT,name TEXT,font TEXT,style TEXT,position INTEGER,visible INTEGER,searchable INTEGER,revision INTEGER,size INTEGER,anchor TEXT)")
            db.execute("INSERT INTO annotation_layers VALUES('layer','ordos','Old tier','Junicode','normal',1,1,1,3,120,'word')")
            dictionary_data.initialize(db);annotations.initialize(db)
            for table in ['writing_types','annotation_layers']:
                row=dict(db.execute('SELECT * FROM '+table).fetchone())
                self.assertIsNone(row['space_before']);self.assertIsNone(row['space_after'])
            self.assertEqual(db.execute('SELECT revision FROM writing_types').fetchone()[0],4)
            self.assertEqual(db.execute('SELECT size FROM annotation_layers').fetchone()[0],120)

    def test_negative_spacing_persists_and_undo_restores_both_definitions(self):
        for action,record in [('layer',self.layer()),('writing',self.writing())]:
            status,saved=self.call('/api/'+action+'-save',{**record,'space_before':-300,'space_after':-12.5})
            self.assertEqual(status,200,saved)
            listing=lambda:self.call('/api/layers?language=ordos')[1] if action=='layer' else self.call('/api/writing-types?language=ordos')[1]['items']
            current=lambda:next(r for r in listing() if r['id']==record['id'])
            self.assertEqual((current()['space_before'],current()['space_after']),(-300,-12.5))
            self.undo();self.assertIsNone(current()['space_before'])
            self.undo('redo');self.assertEqual(current()['space_before'],-300)
