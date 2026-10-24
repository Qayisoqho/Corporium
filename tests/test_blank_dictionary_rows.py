import copy
import unittest
import lexicon
import server
import test_lexicon

class BlankDictionaryRows(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    undo=test_lexicon.LexiconTests.undo

    def test_empty_new_rows_save_without_registering_defaults(self):
        body=dict(tags=[dict(type='语域',value=' ',note='')],orthographies=[{}],variants=[dict(kind='语素变体',variation='unknown')],usages=[dict(pos='',senses=[dict(short_gloss=' ',tags=[dict(type='语域',value='')])])])
        before=copy.deepcopy(body)
        code,x=self.call('/api/lexeme-save',dict(headword='new word',body=body));self.assertEqual(code,200,x)
        for field in ('tags','orthographies','variants','usages'):self.assertEqual(x['body'][field],[],field)
        self.assertEqual(body,before)
        self.assertEqual(self.undo()[0],200)

    def test_dropping_rows_does_not_shift_features_or_stable_ids(self):
        tag=self.call('/api/grammar-save',dict(symbol='SG',description='singular'))[1]['id']
        body=dict(usages=[{},dict(id='u',pos='名词',features=[tag],senses=[{},dict(id='s',short_gloss='意义',features=[tag])])],variants=[{},dict(id='v',form='word',kind='other',features=[tag])])
        code,x=self.call('/api/lexeme-save',dict(headword='word',body=body));self.assertEqual(code,200,x)
        usage=x['body']['usages'][0];self.assertEqual((usage['id'],usage['features']),('u',[tag]));self.assertEqual(usage['senses'][0]['features'],[tag]);self.assertEqual(x['body']['variants'][0]['features'],[tag])
        saved=x['body'];saved['usages'].append({});saved['usages'][0]['senses'].append({})
        code,result=self.call('/api/lexeme-save',{**x,'body':saved});self.assertEqual(code,200,result);self.assertEqual(result['body']['usages'][0]['senses'][0]['id'],'s')

    def test_feature_only_sense_is_content_and_partial_rows_still_validate(self):
        tag=self.call('/api/grammar-save',dict(symbol='SG',description='singular'))[1]['id']
        code,x=self.call('/api/lexeme-save',dict(headword='feature',body={'usages':[{'senses':[{'features':[tag]}]}]}));self.assertEqual(code,200,x);self.assertEqual(x['body']['usages'][0]['senses'][0]['features'],[tag])
        for body in ({'tags':[dict(type='语域',value='',note='保留此备注')]},{'variants':[{'notes':'有内容，不应舍弃'}]},{'orthographies':[{'label':'手填名称'}]}):
            with self.subTest(body=body):self.assertEqual(self.call('/api/lexeme-save',dict(headword='partial',body=body))[0],400)
        with self.assertRaisesRegex(ValueError,'义项内容'):lexicon.normalize({'usages':[{'id':'existing','senses':[{'id':'existing-sense'}]}]})

if __name__=='__main__':unittest.main()
