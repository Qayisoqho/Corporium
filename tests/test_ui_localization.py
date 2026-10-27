import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import ui_localization as ui
import desktop

class InterfaceLanguageTests(unittest.TestCase):
    def test_locale_is_explicit_and_bounded(self):
        self.assertEqual(ui.language({'Cookie':'corporium-ui-language=en'}),'en')
        self.assertEqual(ui.language({'X-Corporium-UI-Language':'en','Cookie':'corporium-ui-language=zh-CN'}),'en')
        self.assertEqual(ui.language({'Cookie':'corporium-ui-language=../../data'}),'zh-CN')

    def test_presentation_does_not_translate_user_fields_or_mutate_input(self):
        value={'title':'保存','body':{'translation':'保存','gloss':'语素'},'message':'保存','error':'保存'}
        with patch.object(ui,'catalog',return_value={'phrases':{'保存':'Save'}}):
            result=ui.present(value,'/api/lexeme','en')
        self.assertEqual(result['error'],'Save');self.assertEqual(result['body'],value['body'])
        self.assertEqual(result['title'],'保存');self.assertEqual(result['message'],'保存');self.assertEqual(value['error'],'保存')

    def test_template_message_keeps_arbitrary_names_and_escapes_regex(self):
        ui.patterns.cache_clear();ui.message.cache_clear()
        with patch.object(ui,'catalog',return_value={'phrases':{'删除「⟦0⟧」失败':'Could not delete “⟦0⟧”'}}):
            self.assertEqual(ui.message('删除「保存 .* 话题」失败','en'),'Could not delete “保存 .* 话题”')
        ui.patterns.cache_clear();ui.message.cache_clear()

    def test_bootstrap_precedes_application_and_preserves_html_data(self):
        source='<html lang="zh-CN"><head></head><body><p>中文</p><script src="/app.js"></script></body></html>'
        result=ui.bootstrap_html(source,'en')
        self.assertLess(result.index('/i18n.js'),result.index('/app.js'))
        self.assertLess(result.index('localizeStatic'),result.index('/app.js'))
        self.assertEqual(result.count('/i18n-settings.js'),1);self.assertIn('<p>中文</p>',result)
        self.assertIn('data-ui-language="en"',result)

    def test_desktop_preference_is_global_without_opening_or_changing_a_project(self):
        with tempfile.TemporaryDirectory(dir=Path('build')) as folder:
            projects=desktop.Projects(folder);projects.settings={'recent':['example'],'other':True}
            projects.set_ui_language('en')
            self.assertIsNone(projects.current)
            saved=json.loads(projects.file.read_text(encoding='utf-8'))
            self.assertEqual(saved,{'recent':['example'],'other':True,'ui_language':'en'})
            self.assertEqual(desktop.Projects(folder).settings['ui_language'],'en')
            with self.assertRaises(ValueError):projects.set_ui_language('invalid')

    def test_malformed_locale_preferences_are_ignored(self):
        self.assertEqual(ui.language({'X-Corporium-UI-Language':[]},default=[]),'zh-CN')
        with tempfile.TemporaryDirectory(dir=Path('build')) as folder:
            p=Path(folder)/'desktop.json'
            for value in [[],{'recent':[],'ui_language':[]},{'ui_language':'../en'}]:
                p.write_text(json.dumps(value),encoding='utf-8')
                self.assertNotIn('ui_language',desktop.Projects(folder).settings)

    def test_typed_diagnostics_translate_without_changing_any_material(self):
        original={'items':[{'message':'未登记的标签候选，请人工确认','title':'保存','body':{'translation':'保存','notes':'未登记的标签候选，请人工确认'}}]}
        snapshot=json.dumps(original,ensure_ascii=False)
        result=ui.present(original,'/api/grammar-audit','en')
        self.assertEqual(result['items'][0]['message'],'Unregistered label candidate; confirm manually')
        self.assertEqual(result['items'][0]['title'],'保存');self.assertEqual(result['items'][0]['body'],original['items'][0]['body'])
        self.assertEqual(json.dumps(original,ensure_ascii=False),snapshot)

    def test_background_results_use_their_declared_route(self):
        original={'kind':'operation','operation':'punctuation-preview','message':'已完成','result':{'blocked':[{'form':'保存','reason':'纯标点格仍有标注或关联，请人工核对'}]}}
        result=ui.present(original,'/api/task-status','en')
        self.assertEqual(result['message'],'Completed');self.assertEqual(result['result']['blocked'][0]['form'],'保存')
        self.assertIn('punctuation',result['result']['blocked'][0]['reason'])
        self.assertEqual(original['result']['blocked'][0]['reason'],'纯标点格仍有标注或关联，请人工核对')

    def test_dynamic_field_captions_keep_user_names_and_ids(self):
        original={'fields':[{'id':'writing:user-id','name':'自定义书写 › 语素'},{'id':'headword','name':'词形'}]}
        result=ui.present(original,'/api/dictionary-search-options','en')
        self.assertEqual(result['fields'][0],{'id':'writing:user-id','name':'Written form › 语素'})
        self.assertEqual(result['fields'][1]['name'],'Word form')
        self.assertEqual(original['fields'][0]['name'],'自定义书写 › 语素')

    def test_native_file_type_captions_keep_extensions_and_need_no_project(self):
        bridge=desktop.Bridge(None)
        self.assertEqual(bridge._file_types(('Word 文档 (*.docx)',)),('Word 文档 (*.docx)',))
        bridge._projects=type('Preference',(),{'settings':{'ui_language':'en'}})()
        self.assertEqual(bridge._file_types(('Word 文档 (*.docx)',)),('Word documents (*.docx)',))

    def test_real_catalog_only_formats_authored_messages(self):
        self.assertEqual(ui.message('导入标签与目标语言冲突：保存 .* 话题。请先核对定义，或导入到新语言。','en'),
                         'Imported labels conflict with the destination language: 保存 .* 话题. Review definitions first, or import into a new language.')
        self.assertEqual(ui.present({'name':'语素','labels':['话题'],'translation':'保存'},'/api/export-language','en'),
                         {'name':'语素','labels':['话题'],'translation':'保存'})

    def test_builtin_outline_is_localized_only_when_newly_created(self):
        import sqlite3
        import grammar_survey as survey
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        try:
            survey.initialize(db)
            db.execute("INSERT INTO survey_nodes VALUES('existing','test',NULL,'section','名词',0,'{}',1)")
            with patch.object(survey,'clean_body',side_effect=lambda db,body,lid:body):
                survey.mutate(db,'test','template',{'version':survey.version(db,'test'),'_interface_language':'en'})
            self.assertEqual(db.execute("SELECT title FROM survey_nodes WHERE id='existing'").fetchone()[0],'名词')
            titles=[r[0] for r in db.execute("SELECT title FROM survey_nodes WHERE id!='existing'")]
            self.assertIn('Noun',titles);self.assertIn('Noun phrase',titles)
            self.assertTrue(all(not any('\u3400'<=c<='\u9fff' for c in title) for title in titles))
        finally:db.close()

    def test_media_availability_is_a_diagnostic_while_its_name_is_material(self):
        source={'media':{'name':'保存','unavailable':'媒体文件已移动或不存在，请使用换源重新定位'}}
        result=ui.present(source,'/api/timeline-detail','en')
        self.assertEqual(result['media']['name'],'保存');self.assertIn('moved',result['media']['unavailable'])
        self.assertEqual(source['media']['unavailable'],'媒体文件已移动或不存在，请使用换源重新定位')
