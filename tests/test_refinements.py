import json
import unittest
from pathlib import Path
import server
import test_annotations
import test_segmentation
import test_operations
import test_lexicon
from restore_backup import restore


class RefinementTests(unittest.TestCase):
    setUp=test_annotations.AnnotationTests.setUp
    tearDown=test_annotations.AnnotationTests.tearDown
    call=test_annotations.AnnotationTests.call
    seed=test_annotations.AnnotationTests.seed
    entries=test_annotations.AnnotationTests.entries
    word=test_annotations.AnnotationTests.word
    example=test_annotations.AnnotationTests.example
    undo=test_annotations.AnnotationTests.undo
    get=test_segmentation.SegmentationTests.get
    group=test_segmentation.SegmentationTests.group

    def test_sentence_layers_inline_search_exchange_restore(self):
        e=self.seed();x=self.word();ind=self.example(x,[])
        for anchor in ('ipa','translation'):
            code,r=self.call('/api/layer-save',dict(name=anchor,anchor=anchor,font='Junicode',style='bolditalic',size=120))
            self.assertEqual(code,200,r)
        for kind,entry in [('corpus',e),('independent',ind)]:
            d=self.call('/api/annotations?kind='+kind+'&id='+entry['id'])[1]
            cells=[dict(unit_id='@sentence',layer_id=l['id'],value='additional '+l['anchor']) for l in d['layers']]
            code,r=self.call('/api/inline-save',dict(kind=kind,id=entry['id'],body=d['body'],revision=d['revision'],before=d['cells'],layers=d['layers'],cells=cells))
            self.assertEqual(code,200,r)
            data=self.call('/api/annotations?kind='+kind+'&id='+entry['id'])[1]
            self.assertEqual(data['orphaned'],[])
        found=self.call('/api/example-library?field=layers&q=additional')[1]
        self.assertEqual(found['total'],2)
        for entry in found['items']:
            self.assertEqual(len(entry['body']['sentence_layers']),2)
            self.assertEqual(entry['body']['words'][0]['extra_layers'],[])
            self.assertEqual(entry['body']['annotation_review_count'],0)
        l=d['layers'][0]
        self.assertEqual(self.call('/api/layer-save',{**l,'anchor':'word'})[0],400)
        self.assertEqual(self.call('/api/grammar-audit?issue=annotation')[1]['total'],0)
        tag=self.call('/api/grammar-save',dict(symbol='GEN'))[1]
        tag_examples=self.call('/api/grammar-audit?issue=usage&tag='+tag['id'])[1]
        self.assertTrue(tag_examples['items'])
        self.assertEqual(len(tag_examples['items'][0]['body']['sentence_layers']),2)
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',dict(name='copy',metadata={}))[1]['id']
        code,r=self.call('/api/import-language',dict(_language=other,bundle=bundle));self.assertEqual(code,200,r)
        copied=self.call('/api/example-library?language='+other+'&field=layers&q=additional')[1]
        self.assertEqual(copied['total'],2)
        self.assertTrue(all(i['body']['annotation_review_count']==0 for i in copied['items']))
        backup=Path(self.temp.name)/'new-layers.json';backup.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf8')
        destination=Path(self.temp.name)/'restored-layers.sqlite3';restore(backup,destination)
        old=server.DB
        try:
            server.DB=destination
            restored=self.call('/api/example-library?language='+other+'&field=layers&q=additional')[1]
            self.assertEqual(restored['total'],2)
            self.assertTrue(all(i['body']['annotation_review_count']==0 for i in restored['items']))
        finally:server.DB=old

    def test_semantic_tag_occurrences(self):
        e=self.seed('#pass([], (([a-eye-b],[1poss-eye.pl-1poss]),([c],[1poss])), [])')
        self.call('/api/grammar-save',dict(symbol='1POSS'))
        uses=lambda:next(t['uses'] for t in self.call('/api/grammar-audit')[1]['tags'] if t['symbol']=='1POSS')
        self.assertEqual(uses(),3)
        self.group(e,gloss='1poss')
        self.assertEqual(uses(),2)
        self.undo();self.assertEqual(uses(),3)
        self.undo('redo');self.assertEqual(uses(),2)
        self.assertEqual(self.call('/api/grammar-audit?issue=usage&tag='+self.call('/api/grammar-tags')[1][0]['id'])[1]['total'],1)

    def test_lexical_occurrences_exclude_old_pieces_and_duplicate_word_links(self):
        e=self.seed('#pass([], (([a-eye-b],[1poss-eye.pl-1poss]),([home],[家]),([home],[家])), [])');x=self.word()
        link=lambda uid:test_lexicon.LexiconTests.link(self,uid,x)
        for i in (0,2):link(e['words'][0]['morphemes'][i]['unit_id'])
        d=self.group(e,gloss='1poss')
        link(d['body']['words'][0]['morphemes'][0]['unit_id'])
        for w in e['words'][1:]:
            link(w['unit_id']);link(w['morphemes'][0]['unit_id'])
        result=self.call('/api/lexeme-examples?id='+x['id'])[1]
        self.assertEqual(result['total'],7)  # historical records remain available
        self.assertEqual(result['occurrences'],3)  # one circumfix plus two separate words
        self.assertEqual(self.call('/api/lexemes')[1]['items'][0]['example_count'],3)

    def test_reorder_preserves_identity_and_undo(self):
        tid,entries=test_operations.OrganizationTests.seed(self,'Order',4)
        e=entries[1];payload=dict(id=e['id'],text_id=tid,revision=e['revision'],position=2,where='after',anchor_id=entries[3]['id'])
        code,r=self.call('/api/reorder-entry',payload);self.assertEqual(code,200,r);self.assertEqual(r['position'],4)
        self.assertEqual(self.call('/api/reorder-entry',payload)[0],400)
        rows=self.call('/api/entries?text='+tid)[1]['items']
        self.assertEqual([r['id'] for r in rows],[entries[i]['id'] for i in (0,2,3,1)])
        self.assertEqual(rows[-1]['words'][0]['unit_id'],e['words'][0]['unit_id'])
        self.undo();self.assertEqual([r['id'] for r in self.call('/api/entries?text='+tid)[1]['items']],[e['id'] for e in entries])
        for where,expected in [('up',1),('down',3),('before',3)]:
            payload['revision']=next(r['revision'] for r in self.call('/api/entries?text='+tid)[1]['items'] if r['id']==e['id'])
            code,r=self.call('/api/reorder-entry',{**payload,'where':where});self.assertEqual(code,200,r);self.assertEqual(r['position'],expected);self.undo()
        self.assertEqual(self.call('/api/reorder-entry',{**payload,'anchor_id':e['id']})[0],400)

    def test_subclass_edit_and_exchange(self):
        code,x=self.call('/api/lexeme-save',dict(headword='test',body={'usages':[{'pos':'名词','subclass':'II类','senses':[{'definition':'test'}]}]}))
        self.assertEqual(code,200,x);self.assertEqual(x['body']['usages'][0]['subclass'],'II类')
        self.assertEqual(self.call('/api/lexemes?q=II')[1]['total'],1)
        x['body']['usages'][0]['subclass']='III类'
        self.assertEqual(self.call('/api/lexeme-save',x)[0],200)
        self.undo();self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['usages'][0]['subclass'],'II类')
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',dict(name='copy',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/import-language',dict(_language=other,bundle=bundle))[0],200)
        self.assertEqual(self.call('/api/lexemes?language='+other)[1]['items'][0]['body']['usages'][0]['subclass'],'II类')
