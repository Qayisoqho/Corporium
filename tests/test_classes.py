import unittest,json
import server
import test_lexicon
import test_segmentation

class ClassTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    undo=test_lexicon.LexiconTests.undo
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    get=test_segmentation.SegmentationTests.get
    group=test_segmentation.SegmentationTests.group

    def create(self,name,kind='pos',**kw):
        code,c=self.call('/api/class-save',dict(name=name,kind=kind,**kw));self.assertEqual(code,200,c)
        return next(x for x in self.call('/api/classes?language=all')[1] if x['id']==c['id'])

    def test_hierarchy_rename_delete_references_and_undo(self):
        root=self.create('名词');child=self.create('II类',parent_id=root['id'])
        code,x=self.call('/api/lexeme-save',dict(headword='test',body={'usages':[{'pos':'名词','subclass':'II类'}]}));self.assertEqual(code,200,x)
        self.assertEqual(self.call('/api/class-delete',child)[0],400)
        self.assertEqual(self.call('/api/class-delete',root)[0],400)
        self.assertEqual(self.call('/api/class-save',{**child,'name':'III类'})[0],200)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['usages'][0]['subclass'],'III类')
        self.assertEqual(self.call('/api/class-save',{**child,'name':'stale'})[0],400)
        self.undo();self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['usages'][0]['subclass'],'II类')
        root=next(c for c in self.call('/api/classes')[1] if c['id']==root['id'])
        self.assertEqual(self.call('/api/class-save',{**root,'name':'Noun'})[0],200)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['usages'][0]['pos'],'Noun')
        self.assertEqual(self.call('/api/class-save',dict(name='third',kind='pos',parent_id=child['id']))[0],400)
        empty=self.create('未使用');self.assertEqual(self.call('/api/class-delete',empty)[0],200);self.undo()
        self.assertIn(empty['id'],[c['id'] for c in self.call('/api/classes')[1]])

    def test_legacy_migration_grammar_and_exchange(self):
        code,x=self.call('/api/lexeme-save',dict(headword='test',body={'usages':[{'pos':'数词','subclass':'分布数词'}]}));self.assertEqual(code,200,x)
        rows=self.call('/api/classes')[1];self.assertEqual({r['name'] for r in rows if r['kind']=='pos'},{'数词','分布数词'})
        parent=self.create('语法范畴','grammar');child=self.create('领属','grammar',parent_id=parent['id'])
        code,t=self.call('/api/grammar-save',dict(symbol='2poss',category='领属'));self.assertEqual(code,200,t)
        self.assertEqual(self.call('/api/class-save',{**child,'name':'领属人称'})[0],200)
        self.assertEqual(self.call('/api/grammar-tags')[1][0]['category'],'领属人称')
        server.init();self.assertEqual(len([c for c in self.call('/api/classes')[1] if c['kind'] not in ('form','usage_tag')]),4)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',dict(name='copy',metadata={}))[1]['id']
        code,r=self.call('/api/import-language',dict(bundle=bundle,_language=other));self.assertEqual(code,200,r)
        copied=self.call('/api/classes?language='+other)[1];self.assertEqual(len([c for c in copied if c['kind'] not in ('form','usage_tag')]),4)
        cp=next(c for c in copied if c['name']=='语法范畴');cc=next(c for c in copied if c['name']=='领属人称');self.assertEqual(cc['parent_id'],cp['id'])
        self.assertEqual(self.call('/api/class-save',{**cc,'_language':'ordos','name':'cross'})[0],400)

    def test_duplicate_combination_remains_rejected(self):
        e=self.seed('#pass([], (([we-amos-la],[pst-go-pst]),), [])');d=self.group(e)
        b=dict(kind='corpus',id=e['id'],revision=d['revision'],action='save',word=0,members=['0:host','1:host'],type='root',status='hypothesis',gloss='x')
        self.assertEqual(self.call('/api/segmentation-save',b)[0],400)

    def test_form_classes_rename_protection_exchange_and_seed_once(self):
        preset=next(c for c in self.call('/api/classes')[1] if c['name']=='派生形式')
        custom=self.create('强调形式','form')
        code,x=self.call('/api/lexeme-save',dict(headword='test',body={'variants':[{'form':'tests','kind':'强调形式'}]}));self.assertEqual(code,200,x)
        self.assertEqual(self.call('/api/class-delete',custom)[0],400)
        self.assertEqual(self.call('/api/class-save',{**custom,'name':'加强形式'})[0],200)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['variants'][0]['kind'],'加强形式')
        bundle=self.call('/api/export-language?language=ordos')[1]
        lid=self.call('/api/save-language',dict(name='Copy',metadata={}))[1]['id']
        code,r=self.call('/api/import-language',dict(bundle=bundle,_language=lid));self.assertEqual(code,200,r)
        self.assertEqual(self.call('/api/lexemes?language='+lid)[1]['items'][0]['body']['variants'][0]['kind'],'加强形式')
        self.assertEqual(self.call('/api/class-delete',preset)[0],200)
        server.init()
        self.assertNotIn('派生形式',[c['name'] for c in self.call('/api/classes?language=ordos')[1]])

    def test_legacy_form_body_is_not_rewritten_on_startup(self):
        code,x=self.call('/api/lexeme-save',dict(headword='old',body={'variants':[{'form':'older','kind':'inflected'}]}));self.assertEqual(code,200,x)
        with server.connect() as db:
            b=x['body'];b['variants'][0]['kind']='inflected';raw=json.dumps(b)
            db.execute('UPDATE lexemes SET body=? WHERE id=?',(raw,x['id']))
        server.init()
        with server.connect() as db:self.assertEqual(db.execute('SELECT body FROM lexemes WHERE id=?',(x['id'],)).fetchone()[0],raw)
        c=next(c for c in self.call('/api/classes?language=ordos')[1] if c['name']=='屈折形式')
        self.assertEqual(self.call('/api/class-delete',c)[0],400)
        self.assertEqual(self.call('/api/class-save',{**c,'name':'屈折变形'})[0],200)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['variants'][0]['kind'],'屈折变形')
    def test_usage_tag_types_all_scopes_rename_undo_and_exchange(self):
        category=self.create('证据等级','usage_tag')
        tag={'type':'证据等级','value':'待验证','note':'调查笔记'}
        code,x=self.call('/api/lexeme-save',dict(headword='tag-demo',body={'tags':[tag],'variants':[{'form':'demo','tags':[tag]}],'usages':[{'pos':'名词','tags':[tag],'senses':[{'short_gloss':'例','tags':[tag]}]}]}))
        self.assertEqual(code,200,x)
        self.assertEqual(self.call('/api/class-delete',category)[0],400)
        self.assertEqual(self.call('/api/class-save',{**category,'name':'可靠程度'})[0],200)
        import categories
        body=self.call('/api/lexeme?id='+x['id'])[1]['body']
        self.assertEqual([t['type'] for t in categories.usage_tags(body)],['可靠程度']*4)
        self.undo()
        body=self.call('/api/lexeme?id='+x['id'])[1]['body']
        self.assertEqual([t['type'] for t in categories.usage_tags(body)],['证据等级']*4)
        bundle=self.call('/api/export-language?language=ordos')[1]
        lid=self.call('/api/save-language',dict(name='Tag copy',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/import-language',dict(bundle=bundle,_language=lid))[0],200)
        self.assertTrue(any(c['name']=='证据等级' for c in self.call('/api/classes?language='+lid)[1]))
        self.assertEqual(self.call('/api/lexeme-save',dict(headword='invalid',body={'tags':[{'type':'不存在的类型','value':'x'}]}))[0],400)
        preset=next(c for c in self.call('/api/classes?language=ordos')[1] if c['kind']=='usage_tag' and c['name']=='地域')
        code,legacy=self.call('/api/lexeme-save',dict(headword='legacy-tag',body={'tags':[{'type':'region','value':'西部'}]}));self.assertEqual(code,200)
        self.assertEqual(self.call('/api/class-save',{**preset,'name':'地理分布'})[0],200)
        self.assertEqual(self.call('/api/lexeme?id='+legacy['id'])[1]['body']['tags'][0]['type'],'地理分布')

