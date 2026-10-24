import json
import unittest
from pathlib import Path
from unittest.mock import patch
import grammar,grammar_reference,server
import test_grammar
from restore_backup import restore


class CandidateTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','tag','undo'):
        locals()[name]=getattr(test_grammar.GrammarTests,name)

    def write(self,action,items,language='ordos'):
        code,r=self.call('/api/'+action,dict(_language=language,items=items))
        self.assertEqual(code,200,r);return r

    def sources(self):
        self.seed('#pass([], (([house-x],[house-PL]),([went],[go.PST]),([pron],[1SG.nom]),([all],[all]),([came],[come.out]),([other],[CUSTOM])), [])')
        code,r=self.call('/api/example-save',dict(body=dict(words=[dict(form='dog-x',gloss='dog-PL'),dict(form='other',gloss='house')],targets=[])))
        self.assertEqual(code,200,r);return r

    def bodies(self):
        with server.connect(audit=False) as db:
            return {t:[tuple(r) for r in db.execute('SELECT id,body FROM '+t+' ORDER BY id')] for t in ('entries','dictionary_examples')}

    def test_reference_never_registers_or_counts_and_default_excludes_english(self):
        self.sources();before=self.bodies()
        ref=self.call('/api/grammar-reference')[1]
        self.assertGreater(len(ref['items']),70)
        self.assertEqual(self.call('/api/grammar-tags')[1],[])
        a=self.call('/api/grammar-audit')[1]
        self.assertEqual({u['symbol']:u['uses'] for u in a['unknown']},{'PL':2,'PST':1,'1':1,'SG':1,'nom':1})
        self.assertEqual(list(grammar.tokens('1SG.nom-PL','ordos',{})),[])
        code,run=self.call('/api/analysis-run',dict(query=dict(conditions=[dict(field='tag',value='PL',mode='exact')],scope={'source':'all'})))
        self.assertEqual(code,200,run);self.assertEqual(run['summary']['hits'],0)
        self.assertNotIn('grammar_reference',self.call('/api/export-language?language=ordos')[1])
        self.assertEqual(before,self.bodies())
        broad=self.call('/api/grammar-audit?lower=true')[1]
        self.assertTrue({'house','go','all','come','out','CUSTOM'}<={u['symbol'] for u in broad['unknown']})
        self.assertEqual(list(grammar.tokens('1go.1THING[house]','ordos',{},candidates=True)),[])

    def test_batch_one_publish_undo_and_raw_aliases_preserved(self):
        self.sources();before=self.bodies();existing=self.tag('custom',aliases=['MyLabel'],notes='Keep')
        with patch.object(grammar,'publish',wraps=grammar.publish) as publish:
            self.write('grammar-register-batch',[dict(symbol='nom',description='主格'),dict(symbol='PL',description='复数')])
            self.assertEqual(publish.call_count,1)
        tags=self.call('/api/grammar-tags')[1]
        self.assertEqual(next(t for t in tags if t['id']==existing['id']),existing)
        self.assertEqual(next(t['symbol'] for t in tags if t['symbol']=='nom'),'nom')
        a=self.call('/api/grammar-audit')[1]
        self.assertEqual(next(t['uses'] for t in a['tags'] if t['symbol']=='PL'),2)
        self.assertFalse({'nom','PL'}&{u['symbol'] for u in a['unknown']})
        code,run=self.call('/api/analysis-run',dict(query=dict(conditions=[dict(field='tag',value='PL',mode='exact')],scope={'source':'all'})))
        self.assertEqual(code,200,run);self.assertEqual(run['summary']['sentences'],2)
        self.assertEqual(before,self.bodies());self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/grammar-tags')[1],[existing])
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(before,self.bodies())

    def test_batch_conflict_rolls_back_all_and_rejects_cross_language(self):
        self.tag('NOM',aliases=['NomCase'])
        before=self.call('/api/grammar-tags')[1]
        for items in ([dict(symbol='PL'),dict(symbol='nomcase')],[dict(symbol='SG'),dict(symbol='sg')],[dict(symbol='PL',language_id='missing')],[dict(symbol='PST',aliases=['bad-alias'])],[],[dict(symbol=3)]):
            code,r=self.call('/api/grammar-register-batch',dict(items=items));self.assertEqual(code,400,r)
            self.assertEqual(self.call('/api/grammar-tags')[1],before)

    def test_ignore_is_language_and_case_scoped_restorable_and_does_not_hide_official(self):
        self.sources();before=self.bodies()
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.call('/api/example-save',dict(_language=other,body=dict(words=[dict(form='x',gloss='PL')],targets=[])))
        self.write('grammar-ignore',[dict(symbol='PL')])
        a=self.call('/api/grammar-audit?language=all&reuse=1')[1]
        self.assertEqual([(u['language_id'],u['uses']) for u in a['unknown'] if u['symbol']=='PL'],[(other,1)])
        self.assertEqual(a['ignored'],[dict(language_id='ordos',symbol='PL')])
        self.assertEqual(self.undo()[0],200)
        self.assertIn('PL',{u['symbol'] for u in self.call('/api/grammar-audit?language=ordos&reuse=1')[1]['unknown']})
        self.assertEqual(self.undo('redo')[0],200)
        self.write('grammar-unignore',[dict(symbol='PL')])
        self.assertEqual(self.call('/api/grammar-audit?language=ordos')[1]['ignored'],[])
        self.write('grammar-ignore',[dict(symbol='PL')]);self.tag('pl')
        a=self.call('/api/grammar-audit?language=ordos')[1]
        self.assertEqual(next(t['uses'] for t in a['tags'] if t['symbol']=='pl'),2)
        self.assertEqual(self.call('/api/grammar-ignore',dict(items=[dict(symbol='PL')]))[0],400)
        self.assertEqual(before['entries'],self.bodies()['entries'])

    def test_sentence_warnings_share_discovery_and_ignore_for_both_sources(self):
        example=self.sources()
        language=next(l for l in self.call('/api/languages')[1] if l['id']=='ordos')
        meta=json.loads(language['metadata']);meta['check_glossary']=True
        self.assertEqual(self.call('/api/save-language',{**language,'metadata':meta})[0],200)
        warnings=self.entries()[0]['warnings'];self.assertTrue(any('PL' in w for w in warnings))
        self.assertFalse(any('house' in w or 'CUSTOM' in w or 'come' in w for w in warnings))
        with server.connect(audit=False) as db:
            import annotations
            body=annotations.enrich(db,json.loads(db.execute('SELECT body FROM dictionary_examples WHERE id=?',(example['id'],)).fetchone()[0]),'independent',example['id'])
        self.assertTrue(any('PL' in w for w in body['warnings']))
        self.write('grammar-ignore',[dict(symbol='PL')])
        self.assertFalse(any('PL' in w for w in self.entries()[0]['warnings']))
        with server.connect(audit=False) as db:
            body=annotations.enrich(db,json.loads(db.execute('SELECT body FROM dictionary_examples WHERE id=?',(example['id'],)).fetchone()[0]),'independent',example['id'])
        self.assertEqual(body['warnings'],[])

    def test_formal_only_script_alias_composition_and_reference_matching(self):
        rows=[dict(id='t',language_id='a',symbol='nom',aliases=['NOMINATIVE']),dict(id='s',language_id='a',symbol='SG',aliases=[]),dict(id='d',language_id='a',symbol='neg#sub[POT]',aliases=[])]
        lookup=grammar.index(rows)
        self.assertEqual(list(grammar.tokens('house-NOM.Nominative.1sg[neg#sub[POT]]','a',lookup)),['NOM','Nominative','sg','neg#sub[POT]'])
        self.assertEqual(list(grammar.tokens('nom.PL','b',lookup)),[])
        self.assertEqual(list(grammar.tokens('all.All.ALL small.NOMINAL pass PASS house[house]','a',{},candidates=True)),['ALL','PASS'])

    def test_ignore_survives_export_import_backup_and_undo_without_reference_rows(self):
        self.sources();self.write('grammar-ignore',[dict(symbol='PL')]);self.tag('nom',aliases=['Nominative'])
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',dict(name='Copy',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/import-language',dict(_language=other,bundle=bundle))[0],200)
        # Import into an existing language follows its own metadata preferences.
        backup=self.call('/api/backup')[1];path=Path(self.temp.name)/'backup.json';path.write_text(json.dumps(backup),encoding='utf8')
        dest=Path(self.temp.name)/'restored.sqlite3';restore(path,dest);server.DB=dest
        a=self.call('/api/grammar-audit?language=ordos')[1]
        self.assertEqual(a['ignored'],[dict(language_id='ordos',symbol='PL')])
        self.assertEqual(a['tags'][0]['aliases'],['Nominative'])
        self.assertNotIn('PL',{u['symbol'] for u in a['unknown']})

    def test_candidate_use_filter_is_exact_and_cache_is_invalidated(self):
        self.sources()
        a=self.call('/api/grammar-audit?language=ordos&reuse=1&issue=unknown&candidate=PL')[1]
        self.assertEqual(a['total'],2)
        self.assertTrue(all(i['token']=='PL' for i in a['items']))
        self.write('grammar-ignore',[dict(symbol='PL')])
        self.assertEqual(self.call('/api/grammar-audit?language=ordos&reuse=1&issue=unknown&candidate=PL')[1]['total'],0)
        self.write('grammar-unignore',[dict(symbol='PL')]);self.write('grammar-register-batch',[dict(symbol='PL')])
        a=self.call('/api/grammar-audit?language=ordos&reuse=1')[1]
        self.assertEqual(next(t['uses'] for t in a['tags'] if t['symbol']=='PL'),2)

    def test_english_homographs_require_explicit_registered_spelling(self):
        self.seed('#pass([], (([one],[all]),([two],[ALL]),([three],[nom]),([four],[NOM])), [])')
        self.tag('ALL');self.tag('nom')
        audit=self.call('/api/grammar-audit')[1]
        self.assertEqual({t['symbol']:t['uses'] for t in audit['tags']},{'ALL':1,'nom':2})
        lookup=grammar.index([dict(id='x',language_id='a',symbol='all',aliases=[])])
        self.assertEqual(list(grammar.tokens('all.ALL','a',lookup)),['all','ALL'])
        lookup=grammar.index([dict(id='x',language_id='a',symbol='ALL',aliases=[])])
        self.assertEqual(list(grammar.tokens('all.All.ALL[all]','a',lookup)),['ALL','all'])
        self.assertEqual(list(grammar.tokens('x#sub[nom.sg]','a',{},candidates=True)),[])

    def test_new_frontend_resource_is_served(self):
        code,body=self.call('/grammar-candidates.js');self.assertEqual(code,200)
        self.assertIn('drawGrammarCandidates',body.decode() if isinstance(body,bytes) else body)

    def test_additive_registration_checks_tags_but_deletion_keeps_reference_validation(self):
        import lexicon
        self.sources()
        with patch.object(lexicon,'validate_links',side_effect=AssertionError('unrelated graph rescanned')):
            self.write('grammar-register-batch',[dict(symbol='PL',category='数'),dict(symbol='NOM',category='格')])
        with patch.object(lexicon,'validate_links',wraps=lexicon.validate_links) as full:
            self.assertEqual(self.undo()[0],200);self.assertTrue(full.called)
        with patch.object(lexicon,'validate_links',side_effect=AssertionError('additive redo rescanned graph')):
            self.assertEqual(self.undo('redo')[0],200)


if __name__=='__main__':unittest.main()
