"""Keep bounded searches equivalent to their full-source reference paths."""
import copy
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import annotations
import corpus
import dictionary_layers
import server
import test_text_tools
import test_dictionary_layers


class ScalarSearchTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries'):
        locals()[name]=getattr(test_text_tools.TextToolsTests,name)

    def test_scalar_scan_keeps_full_results_without_decoding_off_page_words(self):
        self.seed('\n'.join('#pass([IPA #sup[2]'+str(i)+'], (([wide'+str(i)+'],[W]),), [Straße é '+str(i)+'])' for i in range(35)))
        with server.connect(audit=False) as db:
            rows=list(db.execute('SELECT * FROM entries ORDER BY position'))
            for row in rows:
                body=json.loads(row['body']);body.update(notes='line\né',language_notes='language detail')
                db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(body,ensure_ascii=False),row['id']))
            db.execute("INSERT INTO text_info(text_id,metadata) VALUES(?,?) ON CONFLICT(text_id) DO UPDATE SET metadata=excluded.metadata",(rows[0]['text_id'],json.dumps(dict(notes='shared text note'))))
        self.call('/api/example-save',dict(body=dict(ipa='IPA20',translation='Straße é independent',notes='line\né',words=[dict(form='independent',gloss='I')])) )
        with server.connect(audit=False) as db:
            # The one-time rebuild may read old source documents. Subsequent
            # queries must decode only the requested page, as before.
            import sentence_search_index
            sentence_search_index.refresh(db,'translation')
            expected=[dict(kind='corpus',id=r['id'],body=json.loads(r['body'])) for r in db.execute('SELECT * FROM entries ORDER BY position')]
            expected += [dict(kind='independent',id=r['id'],body=json.loads(r['body'])) for r in db.execute('SELECT * FROM dictionary_examples ORDER BY rowid')]
            for row in expected:row['body']['text_notes']='shared text note' if row['kind']=='corpus' else ''
            offpage={r[0] for r in db.execute('SELECT body FROM entries ORDER BY position LIMIT -1 OFFSET 20')}
        loads=json.loads
        def bounded(value,*a,**kw):
            if isinstance(value,str) and value in offpage:raise AssertionError('off-page word arrays were decoded')
            return loads(value,*a,**kw)
        cases=[('translation','STRASSE','contains'),('translation','é','contains'),('ipa','IPA2','prefix'),('notes','line\né','exact'),('notes','shared text','prefix'),('notes','detail','suffix')]
        for field,query,mode in cases:
            with self.subTest(field=field,query=query,mode=mode):
                matched=[r for r in expected if corpus.match(copy.deepcopy(r['body']),query,field,mode=mode)[1]]
                q=dict(field=field,q=query,mode=mode,include_independent='true',language='ordos',page=1,page_size=10)
                with patch.object(json,'loads',side_effect=bounded):code,result=self.call('/api/entries?'+urlencode(q))
                self.assertEqual(code,200,result);self.assertEqual(result['total'],len(matched));self.assertEqual(result['tokens'],0)
                self.assertEqual([(r['kind'],r['id']) for r in result['items']],[(r['kind'],r['id']) for r in matched[:10]])
                self.assertTrue(all(r['words'] and r['translation'] for r in result['items']))


class DerivedSearchTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo','layer','entry','link'):
        locals()[name]=getattr(test_dictionary_layers.DictionaryLayerTests,name)

    def test_query_analysis_cache_and_linked_only_projection_match_full_rendering(self):
        layer=self.layer('pos');target=self.entry()
        sources=[self.source('corpus',[('mala','old'),('unlinked','U')]) for _ in range(2)]
        # source() imports identical text only once; add an independent owner too.
        sources.append(self.source('independent',[('mala','old'),('unlinked','U')]))
        sources=list({(s['kind'],s['id']):(s) for s in sources}.values())
        for src in sources:self.link(src,target)
        with server.connect(audit=False) as db:
            search=annotations.SearchFields(db,'ordos',dict(field='layer:'+layer['id'],q='V'))
            cache_ids=[]
            for src in sources:
                body=annotations.owner(db,src['kind'],src['id'])[0]
                full=dictionary_layers.project(db,corpus.analyze(copy.deepcopy(body)),src['kind'],src['id'],'ordos',[layer])
                sparse=dictionary_layers.project(db,corpus.analyze(copy.deepcopy(body)),src['kind'],src['id'],'ordos',[layer],linked_only=True)
                expected=[(i,dictionary_layers.text(l)) for i,w in enumerate(full['words']) for l in w['extra_layers'] if any(s['values'] for s in l['segments'])]
                actual=[(i,dictionary_layers.text(l)) for i,w in enumerate(sparse['words']) for l in w['extra_layers'] if any(s['values'] for s in l['segments'])]
                self.assertEqual(actual,expected);self.assertEqual(full['words'][1]['extra_layers'][0]['value'],'—');self.assertFalse(sparse['words'][1]['extra_layers'])
                found=search.values(src['kind'],src['id'],body,'ordos');self.assertEqual([(r['word'],r['text']) for r in found],expected)
                cache_ids.append(id(search.analysis_cache));self.assertEqual(body['words'][0]['form'],'mala')
            self.assertEqual(len(set(cache_ids)),1)
        changed=self.api('lexeme?id='+target['id']);changed['body']['usages'][1]['pos']='Changed';self.api('lexeme-save',changed)
        fresh=self.api('example-library?language=ordos&field=layer:'+layer['id']+'&q=Changed')
        self.assertEqual(fresh['total'],len(sources),[(r['kind'],r['id']) for r in fresh['items']])
