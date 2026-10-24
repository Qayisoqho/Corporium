import json
import unittest
import server
import corpus
import test_lexicon


class UnitSymbolTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo

    def test_relations_and_plus_search(self):
        e=self.seed('#pass([ipa], (([so+ma],[go+s.1>o.3sg]),), [translation])')
        self.assertEqual([m['form'] for m in e['words'][0]['morphemes']],['so','ma'])
        self.assertEqual(e['words'][0]['morphemes'][1]['gloss'],'s.1>o.3sg')
        self.assertEqual(e['words'][0]['gloss_relations'],[dict(morpheme=1,operator='>',sides=['s.1','o.3sg'])])
        self.assertEqual(self.call('/api/entries?field=morpheme&q=ma&mode=exact')[1]['total'],1)
        self.assertEqual(self.call('/api/entries?field=morpheme&q=so&mode=exact')[1]['total'],1)
        uid=e['words'][0]['morphemes'][1]['unit_id']
        self.assertEqual(self.call('/api/unit-dictionary?id='+uid)[1]['gloss_relations'][0]['sides'],['s.1','o.3sg'])
        self.assertEqual(e['warnings'],[])

    def test_hash_boundaries_no_lexical_links_or_audit(self):
        e=self.seed('#pass([ipa], (([#],[]),([##],[BOUNDARY]),([###],[]),([word],[word])), [translation])')
        self.assertEqual([w['boundary_count'] for w in e['words']],[1,2,3,0])
        self.assertEqual(e['warnings'],[])
        self.assertEqual(e['words'][0]['morphemes'],[])
        self.assertEqual(self.call('/api/entries?field=form&q=%23&mode=exact')[1]['total'],0)
        self.assertEqual(self.call('/api/entries?field=all&q=%23&mode=exact')[1]['total'],1)
        code,x=self.call('/api/lexeme-save',dict(headword='##',body={'usages':[{'senses':[{'short_gloss':'BOUNDARY'}]}]}))
        self.assertEqual(code,200,x)
        self.assertEqual(self.call('/api/lexeme-auto-preview?language=ordos')[1]['matches'],[])
        code,r=self.call('/api/lexeme-link',{'unit_id':e['words'][1]['unit_id']})
        self.assertEqual(code,400);self.assertIn('音系单位边界',r['error'])
        audit=self.call('/api/grammar-audit?language=ordos')[1]
        self.assertEqual(audit['unknown'],[]);self.assertEqual(audit['counts'],{})
        # Old evidence is retained but flagged for review, never silently deleted.
        with server.connect() as db:
            db.execute("INSERT INTO lexical_links VALUES('legacy',?,?,NULL,NULL,'','ordos',1)",(e['words'][1]['unit_id'],x['id']))
        self.assertTrue(self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]['needs_review'])
        self.assertEqual(self.call('/api/grammar-audit?language=ordos')[1]['counts']['link'],1)
        for value in ['a#','#a','#.','#sub[x]']:
            self.assertEqual(corpus.boundary_count(value),0)
        self.assertEqual(corpus.boundary_count(' \\#\\# '),2)

    def test_boundary_settings_undo_and_inline_alignment(self):
        e=self.seed('#pass([ipa], (([so+ma],[go+PL]),([##],[]),([end],[end])), [translation])')
        lang=self.call('/api/languages')[1][0]
        metadata=json.loads(lang['metadata']);metadata['phonological_boundaries']={'#':'音系词边界','##':'音系短语边界','####':'话轮边界'}
        self.assertEqual(self.call('/api/save-language',{**lang,'metadata':metadata})[0],200)
        self.assertEqual(json.loads(self.call('/api/export-language?language=ordos')[1]['language']['metadata'])['phonological_boundaries'],metadata['phonological_boundaries'])
        self.assertEqual(self.undo()[0],200)
        self.assertNotIn('phonological_boundaries',json.loads(self.call('/api/languages')[1][0]['metadata']))
        self.assertEqual(self.undo('redo')[0],200)
        lang=self.call('/api/languages')[1][0];metadata['phonological_boundaries']={'#abc':'bad'}
        self.assertEqual(self.call('/api/save-language',{**lang,'metadata':metadata})[0],400)
        d=self.call('/api/annotations?kind=corpus&id='+e['id'])[1]
        self.assertEqual(len(d['words']),3)
        d['body']['words'][0]['form']='so+mi';d['body']['words'][1]['gloss']='停顿'
        code,r=self.call('/api/inline-save',dict(kind='corpus',id=e['id'],revision=d['revision'],before=d['cells'],layers=d['layers'],body=d['body'],cells=[]))
        self.assertEqual(code,200,r)
        now=self.entries()[0]
        self.assertEqual(now['words'][1]['unit_id'],e['words'][1]['unit_id'])
        self.assertEqual(now['words'][2]['unit_id'],e['words'][2]['unit_id'])
        self.assertEqual(now['words'][0]['morphemes'][1]['form'],'mi')
        self.assertEqual(now['words'][1]['gloss'],'停顿')
        exported=self.call('/api/export?id='+e['text_id'])[1]
        parsed,errors=corpus.parse(exported)
        self.assertFalse(errors);self.assertEqual(parsed[0]['words'][1]['unit_type'],'phonological_boundary')

    def test_upgrade_old_units_preserves_slot_ids(self):
        e=self.seed('#pass([ipa], (([so+ma],[go+PL]),([##],[])), [translation])')
        ids=[w['unit_id'] for w in e['words']]
        with server.connect() as db:
            db.execute("DELETE FROM corpus_units WHERE kind='morpheme'")
            db.execute("INSERT INTO corpus_units(id,entry_id,kind,parent_id,position,form,gloss) VALUES('old',?,'morpheme',?,0,'so+ma','go+PL')",(e['id'],ids[0]))
            db.execute('PRAGMA user_version=0')
        server.init()
        now=self.entries()[0]
        self.assertEqual([w['unit_id'] for w in now['words']],ids)
        self.assertEqual([w['form'] for w in now['words'][0]['morphemes']],['so','ma'])
        with server.connect() as db:self.assertEqual(db.execute("SELECT active FROM corpus_units WHERE id='old'").fetchone()[0],0)
        self.assertTrue(list(server.DB.parent.glob('backups/*.sqlite3')))


if __name__=='__main__':unittest.main()
