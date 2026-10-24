import base64
import copy
import io
import json
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as E
from unittest.mock import patch

import server
import docx_exchange as x
import test_lexicon

class DocxTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    undo=test_lexicon.LexiconTests.undo

    def api(self,action,**body):
        code,result=self.call('/api/docx-'+action,body);self.assertEqual(code,200,result);return result

    def raw(self,words=None,**kw):
        body=dict(ipa='ɑ b\nc',translation='译文',notes='备注',words=[dict(form=f,gloss=g) for f,g in (words if words is not None else [('a','A'),('b','B'),('c','C')])])
        return x.document('标准文本',[dict(body=body)],**kw)

    def upload(self,raw=None):return self.api('inspect',data=base64.b64encode(raw or self.raw()).decode(),filename='来源.docx')

    def config(self,u):return dict(token=u['token'],title='导入文本',groups=u['groups'],layer_map={d['key']:d['key'] for d in u['source_layers']})

    def imported(self,u,**overrides):
        b={**self.config(u),**overrides};p=self.api('preview',**b);r=self.api('import',**b,signature=p['signature']);return r,p

    def bodies(self,tid):
        with server.connect(audit=False) as db:return [json.loads(r[0]) for r in db.execute('SELECT body FROM entries WHERE text_id=? ORDER BY position',(tid,))]

    def mutate(self,raw,fn):
        output=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as z,zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as dest:
            for name in z.namelist():
                value=z.read(name)
                if name=='word/document.xml':
                    root=E.fromstring(value);fn(root);value=E.tostring(root)
                dest.writestr(name,value)
        return output.getvalue()

    def test_long_sentence_tables_and_page_breaks_stay_one_sentence(self):
        raw=self.raw([(str(i),'TAG-'+str(i)) for i in range(31)],words_per_table=4)
        def page(root):
            table=root.find('.//'+x.q('tbl'));r=x.el(table.find('.//'+x.q('p')),'r');x.el(r,'lastRenderedPageBreak')
        u=self.upload(self.mutate(raw,page));self.assertEqual((u['sentences'],u['slots'],u['segments']),(1,31,8))
        r,p=self.imported(u);b=self.bodies(r['ids'][0]);self.assertEqual(len(b),1);self.assertEqual([w['form'] for w in b[0]['words']],[str(i) for i in range(31)]);self.assertEqual(b[0]['ipa'],'ɑ b\nc')

    def test_empty_sentence_slots_missing_sides_and_literals_roundtrip(self):
        bodies=[dict(ipa='',translation='',notes='',words=[]),dict(ipa='i',translation='译',notes='n',words=[dict(form='=literal~x#',gloss=''),dict(form='',gloss='TAG'),dict(form='',gloss='')])]
        u=self.upload(x.document('空句测试',[dict(body=b) for b in bodies]));r,p=self.imported(u);exported=self.api('export',id=r['ids'][0]);u2=self.upload(base64.b64decode(exported['data']));r2,_=self.imported(u2)
        b=self.bodies(r2['ids'][0]);self.assertEqual([len(v['words']) for v in b],[0,3]);self.assertEqual([(w['form'],w['gloss']) for w in b[1]['words']],[('=literal~x#',''),('','TAG'),('','')])

    def test_merge_split_recipes_preserve_order_fields_empty_sentence_and_layers(self):
        wl=self.call('/api/layer-save',dict(name='词层',font='Junicode',anchor='word'))[1]['id'];sl=self.call('/api/layer-save',dict(name='句层',font='Junicode',anchor='ipa'))[1]['id']
        with server.connect(audit=False) as db:defs=x.annotations.layers(db,'ordos')
        sentences=[dict(body=dict(ipa='first',translation='第一',notes='n1',words=[dict(form='a',gloss='A'),dict(form='b',gloss='B')]),cells={(0,wl):'甲',(1,wl):'乙',(None,sl):'句甲'}),dict(body=dict(ipa='empty',translation='空句',notes='',words=[])),dict(body=dict(ipa='last',translation='最后',notes='n2',words=[dict(form='c',gloss='C')]),cells={(0,wl):'丙',(None,sl):'句丙'})]
        u=self.upload(x.document('连续操作',sentences,defs,words_per_table=1));cfg=self.config(u);cfg['groups']=[dict(start=0,end=1),dict(start=1,end=4,translation='人工合并译文')]
        p=self.api('preview',**cfg);self.assertEqual(p['total'],2);self.assertEqual(p['items'][0]['body']['ipa'],'first');self.assertEqual(p['items'][1]['body']['ipa'],'empty\nlast');self.assertEqual(p['items'][1]['breaks'],[2,4])
        r=self.api('import',**cfg,signature=p['signature']);b=self.bodies(r['ids'][0]);self.assertEqual([[w['form'] for w in s['words']] for s in b],[['a'],['b','c']]);self.assertEqual(b[1]['translation'],'人工合并译文')
        with server.connect(audit=False) as db:
            values=[r[0] for r in db.execute('SELECT value FROM annotation_cells')];self.assertCountEqual(values,['甲','乙','丙','句甲','句丙'])

    def test_preview_no_writes_pagination_and_single_step_undo_redo(self):
        raw=x.document('分页',[dict(body=dict(ipa='',translation=str(i),notes='',words=[])) for i in range(25)])
        before=self.call('/api/undo-state?language=ordos')[1];u=self.upload(raw);cfg=self.config(u);p=self.api('preview',**cfg,page=2);self.assertEqual((p['total'],p['page'],len(p['items'])),(25,2,5));self.assertEqual(self.call('/api/undo-state?language=ordos')[1]['generation'],before['generation'])
        r=self.api('import',**cfg,signature=p['signature']);self.assertEqual(r['count'],25);self.assertEqual(self.undo()[0],200)
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT count(*) FROM texts').fetchone()[0],0)
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(len(self.bodies(r['ids'][0])),25)

    def test_signature_groups_title_and_layer_revision_rechecked(self):
        u=self.upload();cfg=self.config(u);p=self.api('preview',**cfg)
        for change in [dict(title='改变标题'),dict(groups=[dict(start=0,end=2)]),dict(groups=[dict(start=0,end=2),dict(start=1,end=3)]),dict(groups=[dict(start=0,end=3,notes='改变')])]:
            self.assertEqual(self.call('/api/docx-import',{**cfg,**change,'signature':p['signature']})[0],400)
        self.call('/api/layer-save',dict(name='新层',font='Junicode',anchor='word'));self.assertEqual(self.call('/api/docx-import',{**cfg,'signature':p['signature']})[0],400)
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT count(*) FROM texts').fetchone()[0],0)

    def test_language_project_layer_scope_and_no_foreign_overwrite(self):
        u=self.upload();r,_=self.imported(u);lid=self.call('/api/save-language',dict(name='另一语言',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/docx-export',dict(id=r['ids'][0],_language=lid))[0],400)
        old=server.DB
        try:
            server.DB=Path(self.temp.name)/'other.sqlite3';server.init();self.assertEqual(self.call('/api/docx-preview',self.config(u))[0],400)
        finally:server.DB=old

    def test_invalid_package_template_missing_fields_tables_and_tracked_changes(self):
        cases=[b'not a zip',self.mutate(self.raw(),lambda root:root.find('.//'+x.q('sdtPr')+'/'+x.q('tag')).set(x.q('val'),'unknown')),
               self.mutate(self.raw(),lambda root:x.el(root.find('.//'+x.q('tcPr')),'gridSpan',val=2)),
               self.mutate(self.raw(),lambda root:x.el(root.find('.//'+x.q('p')),'drawing')),
               self.mutate(self.raw(),lambda root:x.el(root.find('.//'+x.q('p')),'ins'))]
        for raw in cases:self.assertEqual(self.call('/api/docx-inspect',dict(data=base64.b64encode(raw).decode()))[0],400)

    def test_split_runs_tabs_scripts_and_literal_xml_characters(self):
        raw=self.raw([('a#sub[1]','NEG#super[POT]'),('x\ty\nz','<>&')]);data=x.read(io.BytesIO(raw));self.assertEqual(data['sentences'][0]['words'],[dict(form='a#sub[1]',gloss='NEG#super[POT]'),dict(form='x\ty\nz',gloss='<>&')])

    def test_word_renamed_style_ids_and_custom_xml_parts_are_resolved(self):
        layer=dict(id='source-layer',name='自定义层',font='Junicode',anchor='word',style='normal',size=100)
        raw=x.document('Word 标题',[dict(body=dict(ipa='',translation='',notes='',words=[dict(form='a',gloss='A')]),cells={(0,'source-layer'):'extra'})],[layer])
        out=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as z,zipfile.ZipFile(out,'w') as dest:
            for name in z.namelist():
                data=z.read(name)
                if name=='word/document.xml':data=data.replace(b'w:val="Title"',b'w:val="a3"')
                if name=='word/styles.xml':data=data.replace(b'w:styleId="Title"',b'w:styleId="a3"')
                dest.writestr('customXml/item1.xml' if name=='customXml/corporium.xml' else name,data)
        parsed=x.read(io.BytesIO(out.getvalue()));self.assertEqual(parsed['title'],'Word 标题');self.assertEqual(parsed['sentences'][0]['word_layers']['source-layer'],{0:'extra'})

    def test_stray_text_outside_a_field_cannot_be_silently_discarded(self):
        def change(root):
            p=next(p for p in root.iter(x.q('p')) if any(x.tag(s)=='corporium:field:translation' for s in p.iter(x.q('sdt'))));x._runs(p,'未放入字段的重要内容')
        self.assertEqual(self.call('/api/docx-inspect',dict(data=base64.b64encode(self.mutate(self.raw(),change)).decode()))[0],400)

    def test_missing_layer_mapping_wrong_anchor_and_explicit_skip(self):
        wl=self.call('/api/layer-save',dict(name='词层',font='Junicode',anchor='word'))[1]['id'];sl=self.call('/api/layer-save',dict(name='句层',font='Junicode',anchor='ipa'))[1]['id']
        with server.connect(audit=False) as db:defs=x.annotations.layers(db,'ordos')
        u=self.upload(x.document('Layers',[dict(body=dict(ipa='',translation='',notes='',words=[dict(form='a',gloss='A')]),cells={(0,wl):'保留'})],defs));cfg=self.config(u)
        self.assertEqual(self.call('/api/docx-preview',{**cfg,'layer_map':{}})[0],400)
        self.assertEqual(self.call('/api/docx-preview',{**cfg,'layer_map':{wl:sl,sl:None}})[0],400)
        r,_=self.imported(u,layer_map={wl:None,sl:None})
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT count(*) FROM annotation_cells WHERE record_id IN (SELECT id FROM entries WHERE text_id=?)',(r['ids'][0],)).fetchone()[0],0)

    def test_preview_does_not_reanalyze_every_sentence(self):
        u=self.upload();cfg=self.config(u)
        with patch.object(x,'analyze',side_effect=AssertionError('preview must remain literal')):self.api('preview',**cfg)

    def test_export_reads_current_inherited_gloss_without_modifying_the_source(self):
        import test_gloss_inheritance
        h=test_gloss_inheritance.GlossInheritanceTests();h.call=self.call
        row=self.call('/api/import',dict(title='继承',content='#pass([], (([home],[原值]),), [])'))[1]
        e=self.call('/api/entries?text='+row['id'])[1]['items'][0];lex=h.word('home',['家']);h.link(e,lex,'@word');h.change(lex,'住所')
        with server.connect(audit=False) as db:before=tuple(db.execute('SELECT body,revision FROM entries WHERE id=?',(e['id'],)).fetchone())
        result=self.api('export',id=row['id']);parsed=x.read(io.BytesIO(base64.b64decode(result['data'])));self.assertEqual(parsed['sentences'][0]['words'][0]['gloss'],'住所')
        with server.connect(audit=False) as db:self.assertEqual(tuple(db.execute('SELECT body,revision FROM entries WHERE id=?',(e['id'],)).fetchone()),before)

    def test_export_batches_word_identities_and_layer_cells(self):
        raw=x.document('批量',[dict(body=dict(ipa='',translation='',notes='',words=[dict(form='a',gloss='A')])) for _ in range(12)])
        r,_=self.imported(self.upload(raw));queries=[]
        with server.connect(audit=False) as db:
            db.set_trace_callback(queries.append)
            with patch.object(x.annotations,'units',side_effect=AssertionError('avoid a per-sentence identity query')):result=x.dispatch(db,server.DB,'export',dict(id=r['ids'][0]),'ordos')
        self.assertEqual(len(x.read(io.BytesIO(base64.b64decode(result['data'])))['sentences']),12)
        self.assertEqual(sum('FROM annotation_cells c JOIN entries e' in q for q in queries),1)

    def test_font_scales_export_integer_widths_and_actual_half_points(self):
        raw=self.raw(metadata=dict(ipa_scale=1.2,morpheme_scale=1.3,gloss_scale=.9,translation_scale=1.1))
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            root=E.fromstring(z.read('word/document.xml'))
            for c in root.findall('.//'+x.q('gridCol')):self.assertEqual(str(int(c.get(x.q('w')))),c.get(x.q('w')))
            ipa=next(s for s in root.iter(x.q('sdt')) if x.tag(s)=='corporium:field:ipa');self.assertEqual(ipa.find('.//'+x.q('sz')).get(x.q('val')),str(round(22*1.2)))

    def test_failure_in_middle_rolls_back_every_row_and_history(self):
        u=self.upload();cfg=self.config(u);p=self.api('preview',**cfg);original=x.lexicon.sync_entry
        def broken(db,rid):original(db,rid);raise ValueError('模拟导入失败')
        with patch.object(x.lexicon,'sync_entry',broken):self.assertEqual(self.call('/api/docx-import',{**cfg,'signature':p['signature']})[0],400)
        with server.connect(audit=False) as db:
            for table in ('texts','entries','corpus_units','annotation_cells','undo_steps'):self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)

    def test_desktop_save_template_and_current_gloss(self):
        from unittest.mock import Mock
        import desktop,types
        doc=self.api('template');parsed=x.read(io.BytesIO(base64.b64decode(doc['data'])));self.assertEqual(len(parsed['sentences'][0]['words']),6)
        bridge=desktop.Bridge(None);bridge._origin='http://127.0.0.1:123';bridge._window=Mock();bridge._window.get_current_url.return_value=bridge._origin+'/'
        with patch.dict('sys.modules',webview=types.SimpleNamespace(FileDialog=types.SimpleNamespace(SAVE=1))):
            bridge._window.create_file_dialog.return_value=None;self.assertTrue(bridge.save_docx_export(doc['token'],doc['name'])['cancelled'])
            dest=Path(self.temp.name)/'保存.docx';bridge._window.create_file_dialog.return_value=[str(dest)];self.assertTrue(bridge.save_docx_export(doc['token'],doc['name'])['ok']);self.assertEqual(dest.read_bytes(),base64.b64decode(doc['data']))

if __name__=='__main__':unittest.main()
