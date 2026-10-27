import json
import unittest
from pathlib import Path
from urllib.parse import urlencode
import server
import lexicon
import dictionary_layout
import entry_dates
import test_lexicon
from restore_backup import restore


class DateLayoutTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    undo=test_lexicon.LexiconTests.undo

    def action(self, endpoint, **body):
        status, result=self.call('/api/'+endpoint,body)
        self.assertEqual(status,200,result)
        return result

    def word(self, headword, pos='名词', **body):
        return self.action('lexeme-save',headword=headword,body=dict(usages=[dict(pos=pos)],**body))

    def tree(self,path=None):
        status,result=self.call('/api/dictionary-layout?'+urlencode(dict(language='ordos',path=json.dumps(path or []))))
        self.assertEqual(status,200,result)
        return result

    def move(self,data,kind,xid,target,after=False):
        return self.action('dict-org-layout-move',revision=data['revision'],token=data['token'],path=data['path'],kind=kind,id=xid,before=target,after=after)

    def test_creation_is_immutable_unknown_stays_unknown_and_undo(self):
        a=self.word('z',created_at='1900-01-01T00:00:00+00:00')
        self.assertNotEqual(a['body']['created_at'][:4],'1900')
        b=self.word('a')
        a2=self.action('lexeme-save',id=a['id'],revision=a['revision'],headword='zz',body=dict(created_at='2099-01-01T00:00:00Z'))
        self.assertEqual(a2['body']['created_at'],a['body']['created_at'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/lexeme?id='+a['id'])[1]['body']['created_at'],a['body']['created_at'])
        with server.connect(audit=False) as db:db.execute('INSERT INTO lexemes VALUES(?,?,?,?,1)',('old','ordos','old',json.dumps(lexicon.normalize({}))))
        old=self.action('lexeme-save',id='old',revision=1,headword='old2',body={'created_at':'2099-01-01T00:00:00Z'})
        self.assertNotIn('created_at',old['body'])
        for order,expected in [('@added-asc',[a['id'],b['id'],'old']),('@added-desc',[b['id'],a['id'],'old'])]:
            for query in ('','?'):
                url='/api/lexemes?'+urlencode(dict(sort_order=order,search=json.dumps({'field':'all'}) if query else '{}'))
                self.assertEqual([r['id'] for r in self.call(url)[1]['items']],expected)

    def test_morpheme_creation_dates_filter_pagination_and_import(self):
        a=self.action('morpheme-save',form='z',body={});b=self.action('morpheme-save',form='a',body={})
        changed=self.action('morpheme-save',id=a['id'],revision=a['revision'],form='z',body=dict(gloss='updated',created_at='2000-01-01T00:00:00Z'))
        self.assertEqual(changed['body']['created_at'],a['body']['created_at'])
        with server.connect(audit=False) as db:db.execute('INSERT INTO morphemes VALUES(?,?,?,?,?,1)',('old-m','ordos','old',1,json.dumps(dict(readings=[]))))
        for order,first in [('@added-asc',a),('@added-desc',b)]:
            result=self.call('/api/morphemes?'+urlencode(dict(sort_order=order,page_size=10)))[1]
            self.assertEqual(result['items'][0]['id'],first['id']);self.assertEqual(result['items'][-1]['id'],'old-m')
        self.assertEqual(self.call('/api/morphemes?sort_order=missing')[0],400)
        with server.connect(audit=False) as db:
            entry_dates.imported(db,'morphemes',a['id'],{})
        self.assertNotIn('created_at',self.call('/api/morpheme?id='+a['id'])[1]['body'])

    def test_nested_class_and_entry_order_is_display_only_and_undoable(self):
        c=self.action('dict-org-class-save',name='自然');d=self.action('dict-org-class-save',name='动物',parent_id=c['id'])
        a=self.word('a',semantic_classes=[d['id']]);b=self.word('b',semantic_classes=[d['id']]);v=self.word('v',pos='动词')
        root=self.tree();groups=root['groups'];self.assertEqual(len(groups),2)
        before=[g['key'] for g in groups];self.move(root,'groups',before[1],before[0])
        self.assertEqual([g['key'] for g in self.tree()['groups']],before[::-1])
        self.assertEqual(self.undo()[0],200);self.assertEqual([g['key'] for g in self.tree()['groups']],before)
        path=[next(g['key'] for g in root['groups'] if g['label']=='名词')]
        path += ['semantic:'+c['id'],'semantic:'+d['id']]
        leaf=self.tree(path);self.assertEqual([r['id'] for r in leaf['items']],[a['id'],b['id']])
        self.move(leaf,'entries',b['id'],a['id'])
        self.assertEqual([r['id'] for r in self.tree(path)['items']],[b['id'],a['id']])
        rows=self.call('/api/lexemes?language=ordos&sort_order=%40classes')[1]['items']
        self.assertEqual(len(rows),3);self.assertEqual(len({r['id'] for r in rows}),3)
        self.assertEqual(next(r for r in rows if r['id']==a['id'])['sort_path'][-1]['label'],'动物')
        self.assertEqual(self.call('/api/lexeme?id='+a['id'])[1]['body'],a['body'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual([r['id'] for r in self.tree(path)['items']],[a['id'],b['id']])

    def test_stale_tree_cross_group_and_invalid_levels_rejected(self):
        a=self.word('a');b=self.word('b',pos='动词');root=self.tree()
        bad=dict(revision=root['revision'],token=root['token'],path=[],kind='entries',id=a['id'],before=b['id'])
        self.assertEqual(self.call('/api/dict-org-layout-move',bad)[0],400)
        self.word('c')
        bad.update(kind='groups',id=root['groups'][0]['key'],before=root['groups'][1]['key'])
        self.assertEqual(self.call('/api/dict-org-layout-move',bad)[0],400)
        self.assertEqual(self.call('/api/dict-org-layout-save',dict(revision=root['revision'],levels=['pos','pos']))[0],400)

    def test_multiple_classes_deduplicate_and_levels_can_change(self):
        a=self.action('dict-org-class-save',name='甲');b=self.action('dict-org-class-save',name='乙')
        word=self.word('many',semantic_classes=[a['id'],b['id']]);root=self.tree()
        self.action('dict-org-layout-save',revision=root['revision'],levels=['semantic'])
        rows=self.call('/api/lexemes?language=ordos&sort_order=%40classes')[1]['items']
        self.assertEqual([r['id'] for r in rows],[word['id']]);self.assertEqual(rows[0]['sort_path'][0]['label'],'乙')

    def test_dates_and_layout_full_backup_and_language_exchange(self):
        a=self.word('a');b=self.word('b');root=self.tree()
        self.action('dict-org-layout-save',revision=root['revision'],levels=['pos'])
        root=self.tree();leaf=self.tree([root['groups'][0]['key']]);self.move(leaf,'entries',b['id'],a['id'])
        with server.connect(audit=False) as db:
            bundle=lexicon.export_bundle(db,'ordos')
            language=dict(db.execute("SELECT * FROM languages WHERE id='ordos'").fetchone())
            other=self.action('save-language',name='Imported',metadata=json.loads(language['metadata']))['id']
            result=lexicon.import_bundle(db,bundle,{'ordos':other},{},other)
            imported=[{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT * FROM lexemes WHERE language_id=?',(other,))]
            self.assertEqual({r['body']['created_at'] for r in imported},{a['body']['created_at'],b['body']['created_at']})
            self.assertEqual([r['headword'] for r in dictionary_layout.sorted_rows(db,other,imported)],['b','a'])
        backup=self.call('/api/backup')[1];source=Path(self.temp.name)/'dates.json';source.write_text(json.dumps(backup),encoding='utf8');target=Path(self.temp.name)/'restored.sqlite3';restore(source,target)
        original=server.DB
        try:
            server.DB=target
            self.assertEqual(self.call('/api/lexeme?id='+a['id'])[1]['body']['created_at'],a['body']['created_at'])
            self.assertEqual([r['headword'] for r in self.call('/api/lexemes?language=ordos&sort_order=%40classes')[1]['items']],['b','a'])
        finally:server.DB=original

    def test_language_api_import_preserves_unknown_dates_and_existing_layout(self):
        a=self.word('a');b=self.word('b');root=self.tree()
        self.action('dict-org-layout-save',revision=root['revision'],levels=['pos'])
        leaf=self.tree([self.tree()['groups'][0]['key']]);self.move(leaf,'entries',b['id'],a['id'])
        with server.connect(audit=False) as db:
            db.execute('INSERT INTO lexemes VALUES(?,?,?,?,1)',('old','ordos','old',json.dumps(lexicon.normalize({}))))
            db.execute('INSERT INTO morphemes VALUES(?,?,?,?,?,1)',('old-m','ordos','old',1,json.dumps(dict(readings=[]))))
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.action('save-language',name='New copy',metadata={})['id']
        self.action('import-language',_language=other,bundle=bundle)
        imported=self.call('/api/lexemes?'+urlencode(dict(language=other,sort_order='@classes')))[1]['items']
        self.assertEqual([r['headword'] for r in imported],['b','a','old'])
        self.assertNotIn('created_at',next(r for r in imported if r['headword']=='old')['body'])
        self.assertNotIn('created_at',self.call('/api/morphemes?language='+other)[1]['items'][0]['body'])
        with server.connect(audit=False) as db:before=json.loads(db.execute("SELECT metadata FROM languages WHERE id='ordos'").fetchone()[0])['dictionary_layout']
        self.action('import-language',bundle=bundle,_language='ordos')
        with server.connect(audit=False) as db:after=json.loads(db.execute("SELECT metadata FROM languages WHERE id='ordos'").fetchone()[0])['dictionary_layout']
        self.assertEqual(after,before)

    def test_custom_morph_form_usage_tag_and_grammar_classes(self):
        morph=self.action('class-save',kind='morph',name='形态A')
        self.action('class-save',kind='form',name='实验变体')
        self.action('class-save',kind='usage_tag',name='调查渠道')
        tag=self.action('grammar-save',symbol='TEST',category='时体')
        word=self.word('x',variants=[dict(form='xx',kind='实验变体')],tags=[dict(type='调查渠道',value='口述')],features=[tag['id']],word_structure=dict(memberships=[dict(class_id=morph['id'],title='词干',parts=[dict(label='基本形',form='x')])]))
        for kind,name in [('morph','形态A'),('form','实验变体'),('usage_tag','调查渠道'),('grammar','时体')]:
            root=self.tree();self.action('dict-org-layout-save',revision=root['revision'],levels=[kind])
            result=self.call('/api/lexemes?language=ordos&sort_order=%40classes')[1]['items']
            self.assertEqual(result[0]['id'],word['id']);self.assertEqual(result[0]['sort_path'][0]['label'],name)

    def test_unused_class_order_applies_when_entries_are_added(self):
        self.word('a');unused=self.action('class-save',kind='pos',name='空词类')
        root=self.tree();empty=next(g for g in root['groups'] if g['key']=='pos:'+unused['id']);self.assertEqual(empty['count'],0)
        self.move(root,'groups',empty['key'],root['groups'][0]['key'])
        later=self.word('z',pos='空词类')
        self.assertEqual(self.call('/api/lexemes?language=ordos&sort_order=%40classes')[1]['items'][0]['id'],later['id'])


if __name__=='__main__':unittest.main()
