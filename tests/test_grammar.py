import json
import unittest
from pathlib import Path
import server
import grammar
import test_server
import test_lexicon
import test_dictionary_manager
from restore_backup import restore

class GrammarTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    word=test_lexicon.LexiconTests.word
    link=test_lexicon.LexiconTests.link
    undo=test_lexicon.LexiconTests.undo
    example=test_dictionary_manager.DictionaryManagerTests.example

    def tag(self,symbol='GEN',**extra):
        code,r=self.call('/api/grammar-save',dict(symbol=symbol,description='属格',**extra))
        self.assertEqual(code,200,r)
        return next(t for t in self.call('/api/grammar-tags?language=all')[1] if t['id']==r['id'])

    def test_crud_collision_revision_scope_and_undo(self):
        e=self.seed();tag=self.tag(aliases=['GENITIVE'])
        self.assertEqual(self.call('/api/grammar-save',dict(symbol='genitive'))[0],400)
        self.assertEqual(self.call('/api/grammar-save',dict(symbol='a,b'))[0],400)
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.tag(_language=other)
        self.assertEqual(self.call('/api/grammar-save',{**tag,'_language':other})[0],400)
        self.assertEqual(self.call('/api/grammar-save',{**tag,'notes':'note'})[0],200)
        self.assertEqual(self.call('/api/grammar-save',tag)[0],400)
        tag=self.call('/api/grammar-tags?language=ordos')[1][0]
        self.assertEqual(self.call('/api/grammar-delete',tag)[0],400)
        self.assertEqual(self.call('/api/grammar-delete',{**tag,'confirmed':True})[0],200)
        self.assertEqual(self.call('/api/grammar-tags?language=ordos')[1],[])
        server.init()  # A deleted definition must not reappear from the legacy glossary.
        self.assertEqual(self.call('/api/grammar-tags?language=ordos')[1],[])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/grammar-tags?language=ordos')[1][0]['notes'],'note')
        self.assertEqual(self.entries()[0]['words'][0]['gloss'],e['words'][0]['gloss'])
        self.assertEqual(self.undo('redo')[0],200)

    def test_audit_tokens_aliases_boundaries_and_usage(self):
        self.seed('#pass([ipa], (([a-b],[家-genitive]),([c],[3sg]),([d],[run]),([e-f],[家]),([g],[GEN])), [translation])')
        tag=self.tag(aliases=['GENITIVE']);self.tag('SG');self.tag('3')
        audit=self.call('/api/grammar-audit?language=ordos')[1]
        self.assertEqual(audit['sentences'],1)
        self.assertEqual(audit['counts'],{'alias':2,'boundary':1})
        self.assertEqual(next(t['uses'] for t in audit['tags'] if t['id']==tag['id']),2)
        self.assertEqual(self.call('/api/grammar-audit?lower=true')[1]['unknown'][0]['symbol'],'run')
        examples=self.call('/api/grammar-audit?issue=usage&tag='+tag['id'])[1]
        self.assertEqual(examples['total'],1)
        self.assertEqual(len(examples['items'][0]['body']['words']),5)
        self.assertEqual(self.call('/api/grammar-audit?issue=boundary')[1]['total'],1)
        self.assertEqual(self.call('/api/grammar-audit?q=absent')[1]['total'],0)

    def test_independent_multi_target_and_mixed_language(self):
        e=self.seed();x=self.word();y=self.word();ex=self.example(x,[y])
        ex['body']['words'][0]['gloss']='N';self.call('/api/example-save',ex)
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.tag(_language=other)
        self.assertEqual(self.call('/api/save',{**e,'language_id':other,'notes':''})[0],200)
        audit=self.call('/api/grammar-audit?language='+other)[1]
        self.assertEqual(audit['sentences'],1);self.assertEqual(audit['tags'][0]['uses'],1)
        audit=self.call('/api/grammar-audit?language=ordos&source=independent')[1]
        self.assertEqual(audit['sentences'],1);self.assertEqual(audit['unknown'][0]['uses'],1)
        bundle=self.call('/api/export-language?language=ordos')[1]
        self.assertEqual(bundle['grammar_tags'][0]['language_id'],other)

    def test_exchange_backup_conflict_rollback(self):
        self.seed();self.tag(aliases=['GENITIVE'],category='格',notes='reference')
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',dict(name='Copy',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/import-language',dict(_language=other,bundle=bundle))[0],200)
        self.assertEqual(self.call('/api/grammar-tags?language='+other)[1][0]['aliases'],['GENITIVE'])
        bundle['grammar_tags'][0]['description']='different'
        before=self.call('/api/entries?language='+other)[1]['total']
        self.assertEqual(self.call('/api/import-language',dict(_language=other,bundle=bundle))[0],400)
        self.assertEqual(self.call('/api/entries?language='+other)[1]['total'],before)
        backup=self.call('/api/backup')[1];p=Path(self.temp.name)/'backup.json';p.write_text(json.dumps(backup),encoding='utf-8')
        restored=Path(self.temp.name)/'restored.sqlite3';restore(p,restored);server.DB=restored
        self.assertEqual(self.call('/api/grammar-tags?language=ordos')[1][0]['notes'],'reference')

    def test_stale_links_do_not_add_results_or_counts_and_pagination_still_works(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        self.assertEqual(self.call('/api/save',{**e,'words':[dict(form='other',gloss='N')],'notes':''})[0],200)
        audit=self.call('/api/grammar-audit?issue=link')[1]
        self.assertEqual(audit['total'],0)
        self.assertNotIn('link',audit['counts'])
        all_items=self.call('/api/grammar-audit')[1]
        self.assertEqual(all_items['total'],1)
        self.assertEqual(all_items['counts'],{'unknown':1})
        self.assertEqual([item['issue'] for item in all_items['items']],['unknown'])
        self.seed('\n'.join('#pass([ipa], (([x],[UNREGISTERED])), [t])' for _ in range(25)))
        audit=self.call('/api/grammar-audit?issue=unknown&page=2&lower=true')[1]
        self.assertEqual(audit['total'],26);self.assertEqual(audit['page'],2);self.assertEqual(len(audit['items']),6)

    def test_language_mismatched_links_do_not_add_results_or_change_stored_links(self):
        e=self.seed('#pass([], (([home],[house])), [])');x=self.word();self.link(e['words'][0]['unit_id'],x)
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/save',{**e,'language_id':other,'notes':''})[0],200)
        with server.connect() as db:before=[dict(r) for r in db.execute('SELECT * FROM lexical_links')]
        for lid in ('all','ordos',other):
            for reuse in ('0','1'):
                audit=self.call('/api/grammar-audit?language='+lid+'&reuse='+reuse)[1]
                self.assertEqual(audit['items'],[]);self.assertEqual(audit['total'],0);self.assertEqual(audit['counts'],{})
        with server.connect() as db:self.assertEqual([dict(r) for r in db.execute('SELECT * FROM lexical_links')],before)

    def test_legacy_phonological_boundary_links_are_not_audit_items(self):
        e=self.seed('#pass([], (([home],[house])), [])');x=self.word();self.link(e['words'][0]['unit_id'],x)
        with server.connect() as db:db.execute("UPDATE corpus_units SET form='home#' WHERE id=?",(e['words'][0]['unit_id'],))
        audit=self.call('/api/grammar-audit')[1]
        self.assertEqual(audit['items'],[]);self.assertEqual(audit['total'],0);self.assertEqual(audit['counts'],{})

    def test_legacy_migration(self):
        with server.connect() as db:
            db.execute('DROP TABLE grammar_tags')
            db.execute('UPDATE languages SET metadata=? WHERE id=?',(json.dumps(dict(glossary={'GEN':'属格','gen':'另一说明'})),'ordos'))
        server.init()
        tags=self.call('/api/grammar-tags?language=ordos')[1]
        self.assertEqual([(t['symbol'],t['description']) for t in tags],[('GEN','属格')])
        self.assertIn('另一说明',tags[0]['notes'])
        server.init();self.assertEqual(self.call('/api/grammar-tags?language=ordos')[1],tags)

    def test_new_referenced_language_keeps_aliases(self):
        e=self.seed();other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.tag(_language=other,aliases=['GENITIVE'],notes='reference')
        self.assertEqual(self.call('/api/save',{**e,'language_id':other,'notes':''})[0],200)
        bundle=self.call('/api/export-language?language=ordos')[1]
        server.DB=Path(self.temp.name)/'new-project.sqlite3';server.init()
        code,r=self.call('/api/import-language',dict(bundle=bundle))
        self.assertEqual(code,200,r)
        tags=self.call('/api/grammar-tags?language=all')[1]
        self.assertEqual(len(tags),1);self.assertEqual(tags[0]['aliases'],['GENITIVE'])
        self.assertEqual(self.call('/api/grammar-audit?language=all')[1]['tags'][0]['uses'],1)
