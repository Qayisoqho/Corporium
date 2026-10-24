import json
import unittest
from pathlib import Path
from urllib.parse import urlencode
import server
import analysis_workspace as analysis
import test_lexicon
from restore_backup import restore


class AnalysisTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    word=test_lexicon.LexiconTests.word
    link=test_lexicon.LexiconTests.link
    undo=test_lexicon.LexiconTests.undo

    def execute(self,field='form',value='home-n',conditions=None,scope=None,**extra):
        query=dict(conditions=conditions or [dict(field=field,value=value,mode='exact')],scope=scope or {},**extra)
        code,result=self.call('/api/analysis-run',{'query':query})
        self.assertEqual(code,200,result);return result

    def page(self,r,**kw):
        code,result=self.call('/api/analysis-result?'+urlencode(dict(id=r['id'],language='ordos',**kw)))
        self.assertEqual(code,200,result);return result

    def test_conditions_morphemes_tags_distance_and_counts(self):
        for symbol in ('GEN','PST'):self.assertEqual(self.call('/api/grammar-save',dict(symbol=symbol))[0],200)
        self.seed('#pass([one], (([home-n],[家-GEN]),([。],[]),([#],[#]),([go],[去-PST])), [first])\n#pass([two], (([home-n],[家-GEN]),([stay],[留])), [second])')
        # Explicitly confirmed punctuation is excluded from word-distance counting.
        with server.connect() as db:
            r=db.execute('SELECT id,body FROM entries ORDER BY position LIMIT 1').fetchone();b=json.loads(r['body']);b['words'][1].update(punctuation=True,punctuation_form='。');db.execute('UPDATE entries SET body=? WHERE id=?',(json.dumps(b),r['id']))
        r=self.execute(conditions=[dict(field='morpheme',value='n'),dict(field='tag',value='GEN',relation='same_word'),dict(field='form',value='go',relation='right',min=1,max=1)])
        self.assertEqual((r['summary']['hits'],r['summary']['sentences']),(1,1))
        p=self.page(r);self.assertEqual(p['items'][0]['value'],'n');self.assertEqual(p['items'][0]['word'],0)
        r=self.execute(conditions=[dict(field='tag',value='GEN'),dict(field='tag',value='PST',relation='sentence',exclude=True)])
        self.assertEqual(r['summary']['hits'],1);self.assertEqual(self.page(r)['items'][0]['record']['body']['ipa'],'two')
        r=self.execute('form','');self.assertEqual(r['summary']['hits'],4)
        p=self.page(r,dimension='form');self.assertEqual(p['frequencies'][0]['hits'],2)
        self.assertEqual(self.page(r,dimension='form',value='home-n')['total'],2)

    def test_scope_metadata_and_empty_nonexistent_scope(self):
        e=self.seed();self.call('/api/save-text-info',dict(id=e['text_id'],revision=0,title='Text',metadata=dict(speakers='A / B',place='西部',date='1990年代',genre='叙事')))
        r=self.execute(scope={'place':'西','date':'1990'});self.assertEqual(r['summary']['hits'],1)
        p=self.page(r,dimension='speakers');self.assertEqual(p['frequencies'][0]['label'],'A / B')
        self.assertEqual(self.execute(scope={'place':'东'})['summary']['hits'],0)
        self.assertEqual(self.execute(scope={'text_id':'deleted-id'})['summary']['scope_sentences'],0)

    def test_exactly_thirty_recent_records_and_favorite_independence(self):
        self.seed();generation=self.call('/api/undo-state')[1]['generation'];first=self.execute()
        code,saved=self.call('/api/analysis-save',dict(kind='query',name='my query',notes='note',query=first['query']));self.assertEqual(code,200,saved)
        for _ in range(30):last=self.execute()
        self.assertTrue(last['cached'])
        listing=self.call('/api/analysis-records?language=ordos')[1]
        self.assertEqual(len(listing['recent']),30);self.assertEqual(len(listing['saved']),1)
        with server.connect() as db:
            self.assertIsNone(db.execute('SELECT * FROM analysis_runs WHERE id=?',(first['id'],)).fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM analysis_runs').fetchone()[0],30)
        self.assertEqual(self.call('/api/undo-state')[1]['generation'],generation)
        for _ in range(3):self.page(last,page=99,dimension='text')
        self.assertEqual(len(self.call('/api/analysis-records?language=ordos')[1]['recent']),30)

    def test_listing_purges_expired_runs_but_preserves_saved_snapshot(self):
        e=self.seed();old=self.execute()
        code,snap=self.call('/api/analysis-save',dict(kind='snapshot',name='keep',notes='',run_id=old['id']))
        self.assertEqual(code,200,snap)
        e['notes']='changed';self.assertEqual(self.call('/api/save',e)[0],200)
        fresh=self.execute()
        records=self.call('/api/analysis-records?language=ordos')[1]
        self.assertEqual([r['id'] for r in records['recent']],[fresh['id']])
        self.assertIn(snap['id'],[r['id'] for r in records['saved']])
        with server.connect() as db:
            self.assertIsNone(db.execute('SELECT id FROM analysis_runs WHERE id=?',(old['id'],)).fetchone())
        self.assertTrue(self.page(snap,snapshot='true')['snapshot'])

    def test_stale_results_rejected_after_edit_and_undo(self):
        e=self.seed();r=self.execute();self.assertFalse(self.page(r)['stale'])
        e['notes']='new note';self.assertEqual(self.call('/api/save',e)[0],200)
        p=self.page(r);self.assertTrue(p['stale']);self.assertEqual(p['items'],[])
        self.assertEqual(self.call('/api/analysis-export?'+urlencode(dict(id=r['id'],language='ordos')))[0],400)
        fresh=self.execute();self.assertFalse(fresh['cached']);self.assertEqual(self.undo()[0],200)
        self.assertTrue(self.page(fresh)['stale'])

    def test_snapshot_evidence_export_and_hard_delete(self):
        e=self.seed();r=self.execute()
        code,snap=self.call('/api/analysis-save',dict(kind='snapshot',name='fixed',notes='hypothesis',run_id=r['id']));self.assertEqual(code,200,snap)
        group=self.call('/api/analysis-group',dict(name='unresolved',notes='not a gloss'))[1]
        code,ev=self.call('/api/analysis-evidence',dict(group_id=group['id'],run_id=r['id'],index=0,notes='possible counterexample'));self.assertEqual(code,200,ev)
        e.update(translation='changed',notes='');self.assertEqual(self.call('/api/save',e)[0],200)
        p=self.page(snap,snapshot='true');self.assertTrue(p['stale']);self.assertEqual(p['items'][0]['record']['body']['translation'],'translation')
        evidence=self.call('/api/analysis-group?'+urlencode(dict(id=group['id'],language='ordos')))[1]
        self.assertEqual(evidence['items'][0]['data']['record']['body']['translation'],'translation')
        self.assertEqual(evidence['items'][0]['notes'],'possible counterexample')
        exported=self.call('/api/analysis-export?'+urlencode(dict(id=snap['id'],snapshot='true',language='ordos')))[1]
        self.assertEqual(exported['records'][e['id']]['body']['translation'],'translation')
        self.assertEqual(self.call('/api/analysis-delete',dict(kind='group',id=group['id'],confirmed=True))[0],200)
        with server.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM analysis_evidence').fetchone()[0],0)
        self.assertEqual(self.entries()[0]['translation'],'changed')

    def test_link_policy_and_same_word_conditions(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        r=self.execute('lexeme','home');self.assertEqual(r['summary']['hits'],1)
        r=self.execute(conditions=[dict(field='form',value='home-n'),dict(field='pos',value='名词',relation='same_word')]);self.assertEqual(r['summary']['hits'],1)
        with server.connect() as db:self.assertNotIn("status",{r[1] for r in db.execute("PRAGMA table_info(lexical_links)")});analysis.invalidate(db)
        self.assertEqual(self.execute('lexeme','home')['summary']['hits'],1)
        self.assertEqual(self.execute('lexeme','home',confirmed_only=False)['summary']['hits'],1)

    def test_scope_isolation_and_bad_conditions(self):
        self.seed();r=self.execute();other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/analysis-result?'+urlencode(dict(id=r['id'],language=other)))[0],400)
        self.assertEqual(self.call('/api/analysis-delete',dict(kind='recent',id=r['id'],confirmed=True,_language=other))[0],400)
        for q in ({'conditions':[]},{'conditions':[{'field':'bad'}]},{'conditions':[{'field':'ipa','value':'a'},{'field':'form','value':'x','relation':'right'}]}):
            self.assertEqual(self.call('/api/analysis-run',{'query':q})[0],400)
        self.assertEqual(self.call('/api/analysis-delete',dict(kind='recent',id=r['id']))[0],400)

    def test_changed_sentence_language_excludes_old_lexical_links(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x)
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        e=self.entries()[0];e.update(notes='',language_id=other)
        self.assertEqual(self.call('/api/save',e)[0],200)
        r=self.execute('lexeme','home');self.assertEqual(r['summary']['hits'],0)
        self.assertEqual(r['summary']['linked_words'],0)

    def test_confirmed_circumfix_is_one_morpheme_occurrence(self):
        self.assertEqual(self.call('/api/grammar-save',dict(symbol='PST'))[0],200)
        e=self.seed('#pass([], (([we-amos-la],[PST-go-PST]),), [])')
        d=self.call('/api/segmentation?kind=corpus&id='+e['id'])[1]
        code,result=self.call('/api/segmentation-save',dict(kind='corpus',id=e['id'],revision=d['revision'],action='save',word=0,members=['0:host','2:host'],type='circumfix',status='confirmed',gloss='PST'))
        self.assertEqual(code,200,result)
        self.assertEqual(self.execute('morpheme','we…la')['summary']['hits'],1)
        self.assertEqual(self.execute('morpheme','')['summary']['hits'],2)
        self.assertEqual(self.execute('tag','PST')['summary']['hits'],1)

    def test_full_backup_restores_favorites_and_research(self):
        self.seed();r=self.execute();self.call('/api/analysis-save',dict(kind='snapshot',name='snapshot',run_id=r['id']))
        group=self.call('/api/analysis-group',dict(name='group'))[1];self.call('/api/analysis-evidence',dict(group_id=group['id'],run_id=r['id'],index=0))
        backup=self.call('/api/backup')[1];path=Path(self.temp.name)/'backup.json';path.write_text(json.dumps(backup),encoding='utf-8');target=Path(self.temp.name)/'restored.sqlite3';restore(path,target)
        original=server.DB
        try:
            server.DB=target;listing=self.call('/api/analysis-records?language=ordos')[1]
            self.assertEqual(len(listing['saved']),1);self.assertEqual(listing['groups'][0]['count'],1)
            self.assertEqual(listing['recent'],[])
            self.assertEqual(self.page(listing['saved'][0],snapshot='true')['summary']['hits'],1)
        finally:server.DB=original

    def test_lexical_or_metadata_change_invalidates_cache(self):
        e=self.seed();x=self.word();r=self.execute();self.link(e['words'][0]['unit_id'],x)
        self.assertTrue(self.page(r)['stale'])
        r=self.execute();self.call('/api/save-text-info',dict(id=e['text_id'],revision=0,title='renamed',metadata={}))
        self.assertTrue(self.page(r)['stale'])

    def test_all_language_scope_and_global_limit(self):
        self.seed();r=self.call('/api/analysis-run',dict(_language='all',query={'conditions':[{'field':'form','value':'home-n'}]}))
        self.assertEqual(r[0],200,r)
        self.assertEqual(self.call('/api/analysis-result?'+urlencode(dict(id=r[1]['id'],language='all')))[1]['summary']['hits'],1)
        for _ in range(30):self.execute()
        self.assertEqual(self.call('/api/analysis-records?language=all')[1]['recent'],[])

    def test_result_and_snapshot_include_extra_annotation_lines(self):
        e=self.seed()
        code,l=self.call('/api/layer-save',dict(name='Research layer',font='Junicode',style='normal'));self.assertEqual(code,200,l)
        d=self.call('/api/annotations?kind=corpus&id='+e['id'])[1]
        b=dict(kind='corpus',id=e['id'],revision=d['revision'],before=d['cells'],layers=d['layers'],cells=[dict(unit_id=d['words'][0]['id'],layer_id=l['id'],value='NOUN')])
        code,result=self.call('/api/annotation-save',b);self.assertEqual(code,200,result)
        r=self.execute();p=self.page(r);self.assertEqual(p['items'][0]['record']['body']['words'][0]['extra_layers'][0]['value'],'NOUN')
        code,snap=self.call('/api/analysis-save',dict(kind='snapshot',name='with layer',run_id=r['id']));self.assertEqual(code,200,snap)
        self.assertEqual(self.page(snap,snapshot='true')['items'][0]['record']['body']['words'][0]['extra_layers'][0]['value'],'NOUN')
