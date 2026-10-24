import json
import unittest
import test_lexicon
import server

class SenseFeaturesTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    undo=test_lexicon.LexiconTests.undo
    word=test_lexicon.LexiconTests.word

    def test_sense_features_scope_undo_export_and_search(self):
        tag=self.call('/api/grammar-save',dict(symbol='ANIM',description='animate feature',aliases=[]))[1]['id']
        x=self.word();x['body']['usages'][0]['senses'][0]['features']=[tag]
        code,result=self.call('/api/lexeme-save',dict(id=x['id'],revision=x['revision'],headword=x['headword'],body=x['body']));self.assertEqual(code,200,result)
        saved=self.call('/api/lexeme?id='+x['id'])[1];self.assertEqual(saved['body']['usages'][0]['senses'][0]['features'],[tag])
        self.assertEqual(self.call('/api/lexemes?query=animate%20feature')[1]['total'],1)
        self.assertEqual(self.undo()[0],200);self.assertFalse(self.call('/api/lexeme?id='+x['id'])[1]['body']['usages'][0]['senses'][0]['features']);self.assertEqual(self.undo('redo')[0],200)
        current=self.call('/api/grammar-tags')[1];t=next(t for t in current if t['id']==tag)
        self.assertEqual(self.call('/api/grammar-delete',dict(id=tag,revision=t['revision'],confirmed=True))[0],400)
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id'];foreign=self.call('/api/grammar-save',dict(symbol='OTHER',aliases=[],_language=other))[1]['id']
        saved=self.call('/api/lexeme?id='+x['id'])[1];saved['body']['usages'][0]['senses'][0]['features']=[foreign]
        self.assertEqual(self.call('/api/lexeme-save',dict(id=x['id'],revision=saved['revision'],headword=x['headword'],body=saved['body']))[0],400)
        bundle=self.call('/api/export-language?language=ordos')[1]
        with server.connect() as db:
            server.languages.import_bundle(db,bundle,other)
            imported=db.execute('SELECT body FROM lexemes WHERE language_id=?',(other,)).fetchone();feature=json.loads(imported[0])['usages'][0]['senses'][0]['features'][0]
            self.assertNotEqual(feature,tag);self.assertEqual(db.execute('SELECT language_id FROM grammar_tags WHERE id=?',(feature,)).fetchone()[0],other)

if __name__=='__main__':unittest.main()
