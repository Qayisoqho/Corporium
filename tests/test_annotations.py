import unittest
import json
from pathlib import Path
import server
from restore_backup import restore
import test_server
import test_lexicon
import test_dictionary_manager

class AnnotationTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    word=test_lexicon.LexiconTests.word
    undo=test_lexicon.LexiconTests.undo
    example=test_dictionary_manager.DictionaryManagerTests.example

    def layer(self):
        code,l=self.call('/api/layer-save',dict(name='词类',font='Junicode',style='small-caps'))
        self.assertEqual(code,200,l)
        return self.call('/api/layers?language=ordos')[1][0]

    def annotate(self,kind,e,l):
        d=self.call('/api/annotations?kind='+kind+'&id='+e['id'])[1]
        b=dict(kind=kind,id=e['id'],revision=d['revision'],before=d['cells'],layers=d['layers'],cells=[dict(unit_id=d['words'][0]['id'],layer_id=l['id'],value='NOUN')])
        code,r=self.call('/api/annotation-save',b);self.assertEqual(code,200,r)
        self.assertEqual(self.call('/api/annotation-save',b)[0],400)
        return self.call('/api/annotations?kind='+kind+'&id='+e['id'])[1]

    def test_unified_search_and_exchange(self):
        e=self.seed();x=self.word();y=self.word();ind=self.example(x,[y]);l=self.layer()
        self.annotate('corpus',e,l);self.annotate('independent',ind,l)
        data=self.call('/api/example-library?language=ordos')[1]
        self.assertEqual(data['total'],2)
        self.assertEqual(self.call('/api/example-library?field=layers&q=NOU&mode=prefix')[1]['total'],2)
        self.assertEqual(self.call('/api/example-library?source=independent')[1]['total'],1)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',dict(name='Copy',metadata={}))[1]['id']
        code,r=self.call('/api/import-language',dict(_language=other,bundle=bundle));self.assertEqual(code,200,r)
        copied=self.call('/api/example-library?language='+other+'&field=layers&q=NOUN')[1]
        self.assertEqual(copied['total'],2,copied)
        self.assertEqual(sum(i['body']['annotation_review_count'] for i in copied['items']),0)

    def test_orphan_preservation_and_undo(self):
        e=self.seed();l=self.layer();self.annotate('corpus',e,l)
        e['words']=e['words'][1:];e['notes']=''
        code,result=self.call('/api/save',e);self.assertEqual(code,200,result)
        d=self.call('/api/annotations?kind=corpus&id='+e['id'])[1]
        self.assertEqual(len(d['orphaned']),1)
        self.assertEqual(self.undo()[0],200)
        d=self.call('/api/annotations?kind=corpus&id='+e['id'])[1]
        self.assertEqual(d['orphaned'],[]);self.assertEqual(d['cells'][0]['value'],'NOUN')
        self.assertEqual(self.call('/api/layer-delete',{**l,'confirmed':True})[0],200)
        self.assertEqual(self.call('/api/annotations?kind=corpus&id='+e['id'])[1]['cells'],[])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(len(self.call('/api/annotations?kind=corpus&id='+e['id'])[1]['cells']),1)

    def test_hidden_searchable_and_independent_edit(self):
        x=self.word();e=self.example(x);l=self.layer();d=self.annotate('independent',e,l)
        self.assertEqual(self.call('/api/layer-save',{**l,'visible':False,'searchable':False})[0],200)
        self.assertEqual(self.call('/api/example-library?field=layers&q=NOUN')[1]['total'],0)
        e['body']['words'].append(dict(form='new',gloss='new'))
        self.assertEqual(self.call('/api/example-save',e)[0],200)
        fresh=self.call('/api/annotations?kind=independent&id='+e['id'])[1]
        self.assertEqual(fresh['words'][0]['id'],d['words'][0]['id']);self.assertEqual(fresh['orphaned'],[])

    def test_backup_and_orphan_cleanup(self):
        e=self.seed();l=self.layer();self.annotate('corpus',e,l)
        path=Path(self.temp.name)/'backup.json';path.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8')
        restored=Path(self.temp.name)/'restored.sqlite3';restore(path,restored);server.DB=restored
        self.assertEqual(self.call('/api/example-library?field=layers&q=NOUN')[1]['total'],1)
        e['words']=[];e['notes']='';self.assertEqual(self.call('/api/save',e)[0],200)
        d=self.call('/api/annotations?kind=corpus&id='+e['id'])[1]
        code,r=self.call('/api/annotation-save',dict(kind='corpus',id=e['id'],revision=d['revision'],before=d['cells'],layers=d['layers'],cells=[],discard=[d['orphaned'][0]['id']]))
        self.assertEqual(code,200,r);self.assertEqual(self.call('/api/annotations?kind=corpus&id='+e['id'])[1]['cells'],[])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(len(self.call('/api/annotations?kind=corpus&id='+e['id'])[1]['orphaned']),1)
