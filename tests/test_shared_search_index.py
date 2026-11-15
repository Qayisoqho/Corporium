"""Shared projections preserve the pre-index readers and transactional changes."""
import json
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

import corpus
import corpus_search
import annotations
import gloss_inheritance as gloss
import gloss_search_index
import material_search_index
import sentence_search_index as index
import lexicon
import dictionary_search
import server
import test_gloss_inheritance as inheritance
import test_sentence_search_index as existing


class SharedSearchTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','undo','api','word','example','detail','link','fixture','change','mode'):
        locals()[name]=getattr(inheritance.GlossInheritanceTests,name)
    compare=existing.SentenceSearchIndexTests.compare

    def dictionary(self,query='',**spec):
        with server.connect(audit=False) as db:
            with patch.object(index,'available',return_value=False):
                expected=lexicon.list_lexemes(db,'ordos',query,page_size='all',summary=True,search=spec)
            actual=lexicon.list_lexemes(db,'ordos',query,page_size='all',summary=True,search=spec)
            self.assertEqual(actual,expected,(query,spec))
            return actual

    def test_effective_gloss_and_all_field_modes_keep_distinct_boundaries(self):
        self.seed('#pass([IPA], (([root-n],[根-GEN]),([Straße],[路]),([é],[é]),([#],[BOUNDARY]),([x],[neg#sub[POT]])), [Translation])')
        self.example([('root-n','根-GEN'),('é','é'),('x','Straße')])
        for field in ('gloss','all'):
            for term in ('根','GEN','根-GEN','STRASSE','é','POT','negPOT','BOUNDARY','missing'):
                for mode in ('contains','exact','prefix','suffix'):
                    for case in ('true','false'):
                        q=dict(language='ordos',field=field,q=term,mode=mode,case=case,include_independent='true',page_size=10,page=99)
                        self.compare(q);self.compare(dict(q,source='all'),True)

    def test_library_original_is_literal_and_stored_text_notes_keep_library_scope(self):
        import record_sources
        ex=self.example([('home','家')]);e=self.seed()
        with server.connect(audit=False) as db:
            for table,rid in (('entries',e['id']),('dictionary_examples',ex['id'])):
                body=record_sources.read(db,table,rid)
                body.update(original='#sub[2] literal\\#',text_notes='stored-note-only')
                record_sources.write(db,table,rid,body,bump=False)
        for field,term in [('original','#sub[2] literal\\#'),('all','#sub[2] literal\\#'),('notes','stored-note-only'),('all','stored-note-only')]:
            for mode in ('contains','exact','prefix','suffix'):
                self.compare(dict(field=field,q=term,mode=mode,source='all',language='ordos'),True)
        self.assertEqual(self.compare(dict(field='notes',q='stored-note-only',include_independent='true'))['total'],0)

    def test_word_parts_do_not_apply_dictionary_meaning_composition_to_sentence_fields(self):
        import record_sources
        e,ex,x=self.fixture()
        with server.connect(audit=False) as db:
            for table,rid in (('entries',e['id']),('dictionary_examples',ex['id'])):
                body=record_sources.read(db,table,rid)
                body['words'][0]['gloss_addition']='PST'
                record_sources.write(db,table,rid,body,bump=False)
        self.assertEqual(self.dictionary('家.SG',field='examples.words.gloss')['total'],1)
        self.assertEqual(self.dictionary('PST',field='examples.words.gloss')['total'],0)

    def test_meaning_override_blank_undo_and_external_rollback(self):
        e,ex,x=self.fixture()
        for value in ('家','住所'):
            if value!='家':self.change(x,value)
            for field in ('gloss','all'):
                self.compare(dict(field=field,q=value,include_independent='true'))
                self.compare(dict(field=field,q=value,source='all'),True)
            self.dictionary(value)
        self.mode('independent',ex,'override','本句')
        self.mode('corpus',e,'override','')
        for term in ('住所','本句'):
            self.compare(dict(field='gloss',q=term,include_independent='true'));self.dictionary(term,field='examples.words.gloss')
        self.undo();self.dictionary('住所')
        self.undo('redo');self.dictionary('住所')
        with server.connect(audit=False) as db:
            baseline=corpus_search.search(db,dict(field='gloss',q='住所',include_independent='true'),'ordos')
            db.execute('SAVEPOINT temporary_edit')
            db.execute("UPDATE gloss_meanings SET gloss='事务新义',revision=revision+1")
            actual=corpus_search.search(db,dict(field='gloss',q='事务新义',include_independent='true'),'ordos')
            with patch.object(index,'available',return_value=False):
                self.assertEqual(actual,corpus_search.search(db,dict(field='gloss',q='事务新义',include_independent='true'),'ordos'))
            db.execute('ROLLBACK TO temporary_edit');db.execute('RELEASE temporary_edit')
            self.assertEqual(corpus_search.search(db,dict(field='gloss',q='住所',include_independent='true'),'ordos'),baseline)

    def test_dictionary_predicates_share_evidence_and_keep_negative_and_empty_semantics(self):
        e,ex,x=self.fixture();other=self.word('free',['FREE'])
        for kind,row in [('corpus',e),('independent',ex)]:self.link(row,other,'@word',word=1,kind=kind)
        for field in ('all','examples','examples.words.form','examples.words.gloss','examples.ipa','examples.translation','examples.notes'):
            for op in ('contains','exact','prefix','suffix','not_contains','empty','present'):
                self.dictionary('',conditions=[dict(field=field,op=op,value='' if op in ('empty','present') else '家')])
        self.dictionary('家')
        with server.connect(audit=False) as db:
            with patch.object(gloss,'load',side_effect=AssertionError('warm evidence must not load source examples')):
                self.assertEqual(lexicon.list_lexemes(db,'ordos','家',page_size='all',summary=True)['total'],2)
        self.change(x,'新义')
        self.dictionary('新义');self.dictionary('家')

    def test_warm_sentence_queries_only_render_visible_hits(self):
        self.seed('\n'.join('#pass([], (([root],[HOUSE])), [])' for _ in range(45)))
        for field in ('gloss','all'):
            self.compare(dict(field=field,q='HOUSE',page=2,page_size=10))
            with server.connect(audit=False) as db:
                with patch.object(corpus,'QueryMatcher',side_effect=AssertionError('indexed query must not scan')):
                    with patch.object(gloss,'load',wraps=gloss.load) as loads:
                        result=corpus_search.search(db,dict(field=field,q='HOUSE',page=2,page_size=10),'ordos')
                        self.assertEqual((result['total'],len(result['items'])),(45,10))
                        visible={('corpus',item['id']) for item in result['items']}
                        self.assertLessEqual({(call.args[1],call.args[2]) for call in loads.call_args_list},visible)

    def test_missing_fts_and_backup_rebuild_shared_projections(self):
        e,ex,x=self.fixture();self.dictionary('家')
        with server.connect(audit=False) as db:
            db.execute('DROP TABLE projection_search_fts')
        self.compare(dict(field='gloss',q='家',include_independent='true'));self.dictionary('家')
        with server.connect(audit=False) as db:
            target=sqlite3.connect(':memory:');target.row_factory=sqlite3.Row
            try:
                db.backup(target);index.drop(target)
                self.assertFalse(target.execute("SELECT name FROM sqlite_master WHERE name GLOB 'gloss_search_*' OR name GLOB 'material_search_*' OR name GLOB 'projection_search_*'").fetchone())
                index.initialize(target)
                result=corpus_search.search(target,dict(field='gloss',q='家',include_independent='true'),'ordos')
                self.assertEqual(result['total'],2)
            finally:target.close()

    def test_meaning_edit_refreshes_one_shared_recipe_without_occurrence_rewrites(self):
        self.seed('\n'.join('#pass([], (([home],[家.SG])), [])' for _ in range(24)))
        with server.connect(audit=False) as db:
            records=[dict(r) for r in db.execute('SELECT id,body FROM entries_documents ORDER BY position')]
        x=self.word('home',['家']);self.link(records[0],x,'@word')
        with server.connect(audit=False) as db:
            binding=dict(db.execute('SELECT * FROM gloss_bindings LIMIT 1').fetchone())
            columns=list(binding)
            for n,row in enumerate(records[1:]):
                uid=db.execute("SELECT id FROM corpus_units WHERE entry_id=? AND kind='word' AND active=1",(row['id'],)).fetchone()[0]
                copied={**binding,'id':'shared-test-'+str(n),'owner_id':row['id'],'word_id':uid}
                db.execute('INSERT INTO gloss_bindings('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',[copied[k] for k in columns])
            gloss_search_index.refresh(db)
            before=[tuple(r) for r in db.execute('SELECT * FROM gloss_search_words ORDER BY kind,owner_id,word')]
            self.assertEqual(db.execute('SELECT count(DISTINCT recipe_id) FROM gloss_search_words').fetchone()[0],1)
            db.execute("UPDATE gloss_meanings SET gloss='新义',revision=revision+1 WHERE id=?",(binding['meaning_id'],))
            self.assertEqual(db.execute('SELECT count(*) FROM gloss_search_dirty').fetchone()[0],0)
            with patch.object(gloss,'render_word',wraps=gloss.render_word) as rendered:
                gloss_search_index.refresh(db)
            self.assertEqual(rendered.call_count,1)
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM gloss_search_words ORDER BY kind,owner_id,word')])
            self.assertEqual(corpus_search.search(db,dict(field='gloss',q='新义'),'ordos')['total'],24)

    def test_dictionary_only_prepares_actual_evidence_sources(self):
        self.seed('\n'.join('#pass([], (([home],[家])), [])' for _ in range(24)))
        x=self.word('local',['LOCAL'])
        with patch.object(gloss_search_index,'refresh',side_effect=AssertionError('unlinked sources must not be prepared')):
            self.assertEqual(self.dictionary('LOCAL')['total'],1)
        with server.connect(audit=False) as db:
            record=dict(db.execute('SELECT id,body FROM entries_documents LIMIT 1').fetchone())
        self.link(record,x,'@word')
        self.dictionary('家',field='examples.words.gloss')
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM gloss_search_owners').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM gloss_search_dirty').fetchone()[0],23)

    def test_literal_evidence_refreshes_only_the_invalidated_record(self):
        import dictionary_cold
        self.enterContext(patch.object(dictionary_cold,'available',return_value=False))
        import sentence_rows
        import source_fixtures
        _,example,target=self.fixture()
        self.dictionary('家')
        with server.connect(audit=False) as db:
            source_fixtures.patch_values(db,'dictionary_examples',example['id'],
                                         ((('translation',),'updated literal evidence'),))
        with patch.object(sentence_rows,'headers',wraps=sentence_rows.headers) as headers:
            result=self.api('lexemes?language=ordos&q=updated+literal+evidence&summary=1')
            self.assertEqual([r['id'] for r in result['items']],[target['id']])
            self.assertEqual([c.args[2] for c in headers.call_args_list],[[example['id']]])

    def test_full_dictionary_edits_read_only_affected_owners_with_attachments(self):
        import dictionary_rows
        import dictionary_own_index
        import sentence_rows
        _,example,target=self.fixture()
        other=self.word('unrelated',['Other'])
        with server.connect(audit=False) as db:
            db.execute("INSERT INTO timeline_media VALUES('fixture','ordos','recording title','','missing',?,1)",
                       (json.dumps(dict(streams=[dict(type='audio')],duration_ms=1000)),))
            db.executemany('INSERT INTO object_media VALUES(?,?,?,?,?,?,0,1)',(
                ('attach-x','ordos','lexeme',target['id'],'fixture',json.dumps({'caption':'direct caption','end_ms':100})),
                ('attach-e','ordos','independent',example['id'],'fixture',json.dumps({'caption':'example caption','end_ms':100})),
                ('attach-y','ordos','lexeme',other['id'],'fixture',json.dumps({'caption':'other caption','end_ms':100}))))
        self.assertEqual(self.dictionary('example caption')['total'],1)
        self.assertEqual(self.dictionary('recording title')['total'],2)
        # This is an entry-local definition change. No evidence words or other
        # definitions need to be read before matching against the postings.
        target=self.api('lexeme?id='+target['id'])
        target['body']['usages'][0]['senses'][0]['definition']='unique changed definition'
        self.api('lexeme-save',target)
        with patch.object(dictionary_rows,'targets',wraps=dictionary_rows.targets) as definitions, \
                patch.object(sentence_rows,'headers',side_effect=AssertionError('unrelated evidence was rebuilt')):
            answer=self.api('lexemes?language=ordos&q=unique+changed+definition&summary=1')
            self.assertEqual([r['id'] for r in answer['items']],[target['id']])
            self.assertEqual([call.args[1] for call in definitions.call_args_list],[[target['id']]])
        self.undo()
        self.assertEqual(self.dictionary('unique changed definition')['total'],0)
        self.assertEqual(self.dictionary('example caption')['total'],1)
        with server.connect(audit=False) as db:
            db.execute("UPDATE object_media SET body=json_set(body,'$.caption','changed example caption') WHERE id='attach-e'")
        self.assertEqual(self.dictionary('changed example caption')['total'],1)
        with server.connect(audit=False) as db:
            args=dict(query='changed example caption',summary=True)
            with patch.object(dictionary_own_index,'predicate',return_value=None):
                expected=lexicon._list_lexemes(db,'ordos',**args)
            self.assertEqual(lexicon._list_lexemes(db,'ordos',**args),expected)
            db.execute("UPDATE timeline_media SET name='renamed recording' WHERE id='fixture'")
        self.assertEqual(self.dictionary('recording title')['total'],0)
        self.assertEqual(self.dictionary('renamed recording')['total'],2)

    def test_full_dictionary_search_tracks_referenced_names_and_reverse_relations(self):
        base=self.word('before rename',['Base'])
        other=self.word('other base',['Other'])
        derived=self.word('derived form',['Derived'])
        derived['body']['relation']=dict(type='derivation',base_id=base['id'])
        derived=self.api('lexeme-save',derived)

        def ids(query):
            return {item['id'] for item in self.dictionary(query)['items']}

        self.assertEqual(ids('before rename'),{base['id'],derived['id']})
        self.assertEqual(ids('derived form'),{base['id'],derived['id']})
        base=self.api('lexeme?id='+base['id'])
        base['headword']='after rename'
        self.api('lexeme-save',base)
        self.assertEqual(ids('before rename'),set())
        self.assertEqual(ids('after rename'),{base['id'],derived['id']})
        self.undo()
        self.assertEqual(ids('before rename'),{base['id'],derived['id']})
        derived=self.api('lexeme?id='+derived['id'])
        derived['body']['relation']['base_id']=other['id']
        self.api('lexeme-save',derived)
        self.assertEqual(ids('derived form'),{other['id'],derived['id']})
        self.undo()
        self.assertEqual(ids('derived form'),{base['id'],derived['id']})

    def test_full_dictionary_manual_annotation_edits_follow_undo(self):
        import dictionary_cold
        self.enterContext(patch.object(dictionary_cold,'available',return_value=False))
        corpus_record,_,target=self.fixture()
        layer=self.api('layer-save',dict(name='Analysis note',anchor='translation'))['id']

        def write(value):
            data=self.api('annotations?kind=corpus&id='+corpus_record['id'])
            self.api('annotation-save',dict(kind='corpus',id=corpus_record['id'],
                revision=data['revision'],before=data['cells'],layers=data['layers'],
                cells=[dict(unit_id=annotations.SENTENCE,layer_id=layer,value=value)]))

        def ids(query):
            result=self.api('lexemes?language=ordos&summary=1&q='+query)
            return [item['id'] for item in result['items']]

        write('early-note-only')
        self.assertEqual(ids('early-note-only'),[target['id']])
        write('later-note-only')
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM material_search_manual_dirty').fetchone()[0],1)
        self.assertEqual(ids('early-note-only'),[])
        self.assertEqual(ids('later-note-only'),[target['id']])
        self.undo()
        self.assertEqual(ids('later-note-only'),[])
        self.assertEqual(ids('early-note-only'),[target['id']])

    def test_full_dictionary_search_updates_incoming_evidence_membership(self):
        example=self.example([('evidence form','isolated-example-token')])
        target=self.word('evidence form',['Target'])

        def hits():
            return self.dictionary('isolated-example-token')['total']

        self.assertEqual(hits(),0)
        self.link(example,target,'@word',kind='independent',sense=None)
        self.assertEqual(hits(),1)
        self.undo()
        self.assertEqual(hits(),0)
        self.undo('redo')
        self.assertEqual(hits(),1)

    def test_nested_inheritance_searches_keep_precedence_and_frozen_children(self):
        e=self.seed('#pass([], (([home-n],[家-GEN])), [])');ex=self.example([('home-n','家-GEN')])
        whole=self.word('home-n',['家-GEN']);child=self.word('n',['POSS'])
        for kind,row in [('corpus',e),('independent',ex)]:
            self.link(row,whole,'@word',kind=kind);self.link(row,child,'1:host',kind=kind)
        def check():
            for term in ('家','POSS','住所','DAT','FUT'):
                self.compare(dict(field='gloss',q=term,include_independent='true'))
                self.dictionary(term,field='examples.words.gloss')
        check();self.change(whole,'住所-DAT');check()
        d=self.detail(e);u=self.api('unit-dictionary?id='+d['body']['words'][0]['morphemes'][1]['unit_id'])
        self.api('lexeme-unlink',dict(id=u['link']['id'],revision=u['link']['revision']))
        d=self.detail(ex,'independent');pos=next(i for i,t in enumerate(d['body']['targets']) if t['segmentation_ref']['key']=='1:host')
        self.api('segmentation-link',dict(kind='independent',id=ex['id'],revision=d['revision'],remove_target=pos))
        self.change(child,'FUT');check()

    def test_grouped_inheritance_searches_keep_physical_spans_after_whole_edit(self):
        e=self.seed('#pass([], (([we-go-la],[PST-go-PST])), [])');ex=self.example([('we-go-la','PST-go-PST')])
        whole=self.word('we-go-la',['PST-go-PST']);child=self.word('we…la',['家'])
        for kind,row in [('corpus',e),('independent',ex)]:
            d=self.detail(row,kind)
            self.api('segmentation-save',dict(kind=kind,id=row['id'],revision=d['revision'],word=0,action='save',type='circumfix',members=['0:host','2:host'],gloss='PST'))
            self.link(row,whole,'@word',kind=kind)
            key=self.detail(row,kind)['body']['words'][0]['morphemes'][0]['key'];self.link(row,child,key,kind=kind)
        for label in ('PST-go-PST','ANT-go-ANT'):
            if label.startswith('ANT'):self.change(whole,label)
            for term in ('家','go','ANT','家-go-家'):
                self.compare(dict(field='gloss',q=term,include_independent='true'))
                self.dictionary(term,field='examples.words.gloss')

    def test_linked_writing_values_reuse_and_follow_target_edits_and_undo(self):
        e,ex,x=self.fixture();writing=self.api('writing-save',dict(name='Script',font='Junicode'))
        x=self.api('lexeme?id='+x['id']);x['body']['orthographies']=[dict(type_id=writing['id'],font='Junicode',label='Script',text='First spelling')]
        self.api('lexeme-save',x)
        q=dict(field='writing:'+writing['id'],q='First spelling',include_independent='true')
        self.assertEqual(self.compare(q)['total'],2)
        with server.connect(audit=False) as db:
            with patch('word_structure.writing_rows',side_effect=AssertionError('warm spellings must not expand linked targets')):
                self.assertEqual(corpus_search.search(db,q,'ordos')['total'],2)
        x=self.api('lexeme?id='+x['id']);x['body']['orthographies'][0]['text']='Second spelling';self.api('lexeme-save',x)
        self.assertEqual(self.compare(q)['total'],0)
        self.assertEqual(self.compare(dict(q,q='Second spelling'))['total'],2)
        self.undo();self.assertEqual(self.compare(q)['total'],2)

    def test_catalog_cache_invalidates_and_read_only_connections_keep_original_readers(self):
        self.fixture()
        with server.connect(audit=False) as db:
            first=dictionary_search.catalog(db,'ordos')
            with patch('dictionary_data.resolve',side_effect=AssertionError('warm options must reuse their catalog')):
                self.assertEqual(dictionary_search.catalog(db,'ordos'),first)
        writing=self.api('writing-save',dict(name='New script',font='Junicode'))
        with server.connect(audit=False) as db:
            self.assertIn('writing:'+writing['id'],{f['id'] for f in dictionary_search.catalog(db,'ordos')['fields']})
        expected=self.dictionary('家')
        with closing(sqlite3.connect(server.DB.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            self.assertEqual(lexicon.list_lexemes(db,'ordos','家',page_size='all',summary=True),expected)

    def test_search_options_update_only_touched_definition_and_follow_undo(self):
        import dictionary_option_catalog as options
        a=self.word('one',['first'])
        self.word('two',['second'])
        query='dictionary-search-options?language=ordos'
        first=self.api(query)
        writing=self.api('writing-save',dict(name='Search script',font='Junicode'))
        a=self.api('lexeme?id='+a['id'])
        a['body']['orthographies']=[dict(label=writing['name'],type_id=writing['id'],text='字',font='Junicode')]
        self.api('lexeme-save',a)

        with patch.object(options,'_shapes',wraps=options._shapes) as shapes:
            changed=self.api(query)
            self.assertEqual([list(call.args[2]) for call in shapes.call_args_list],[[a['id']]])
        self.assertIn('orthographies.type_id',{field['id'] for field in changed['fields']})
        self.undo()
        self.assertNotIn('orthographies.type_id',{field['id'] for field in self.api(query)['fields']})
        self.undo()
        self.assertEqual(self.api(query),first)

    def test_linked_translation_predicate_skips_dictionary_documents(self):
        self.fixture()
        spec=dict(field='examples.translation',case=False)
        with server.connect(audit=False) as db:
            query='translation'
            import dictionary_own_index
            with patch.object(dictionary_own_index,'evidence_translation',return_value=None):
                expected=lexicon.list_lexemes(db,'ordos',query,search=spec,summary=True)
            with patch.object(dictionary_search,'SearchIndex',side_effect=AssertionError('translation only needs headers')):
                actual=lexicon.list_lexemes(db,'ordos',query,search=spec,summary=True)
            self.assertEqual(actual,expected)

    def test_bulk_manual_projection_agrees_with_per_owner_layer_reads(self):
        e,ex,_=self.fixture()
        with server.connect(audit=False) as db:
            db.execute("INSERT INTO annotation_layers(id,language_id,name,font,anchor) VALUES('bulk','ordos','Bulk','Junicode','word')")
            for kind,row in (('corpus',e),('independent',ex)):
                unit=annotations.get(db,kind,row['id'])['words'][0]['id']
                db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,1)',
                           (kind,kind,row['id'],unit,'bulk','distinct annotation'))
            db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,1)',
                       ('stale','corpus',e['id'],'retired','bulk','do not find'))
            material_search_index.refresh_custom(db)
            query="SELECT kind,owner_id,field,word,origin,display FROM material_search_custom ORDER BY kind,owner_id,field,word"
            before=[tuple(row) for row in db.execute(query)]
            self.assertEqual(len(before),2)
            db.execute('UPDATE material_search_dirty SET custom=1')
            db.executemany('INSERT INTO material_search_dirty VALUES(?,?,0,1)',
                           [('corpus',e['id']),('independent',ex['id'])])
            material_search_index.refresh_manual_cells(db,'',material_search_index.Values(db))
            self.assertEqual([tuple(row) for row in db.execute(query)],before)

    def test_dictionary_background_task_cancellation_rolls_back_derived_publication(self):
        import dictionary_cold
        self.enterContext(patch.object(dictionary_cold,'available',return_value=False))
        import long_tasks,journal
        self.fixture()
        with server.connect(audit=False) as db:
            revision=journal.workspace_revision(db)
            tables=('gloss_search_recipes','material_search_literal_records','dictionary_own_keys')
            before={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in tables}
        prepare=material_search_index.literal_records
        def cancel(*args):
            prepare(*args)
            raise long_tasks.Cancelled()
        with patch.object(material_search_index,'literal_records',cancel):
            job=long_tasks.submit(server.DB,'dictionary',dict(language='ordos',q='家',summary='1'))
            long_tasks.JOBS[job]['future'].result(timeout=20)
        self.assertEqual(long_tasks.view(server.DB,job)['state'],'cancelled')
        with server.connect(audit=False) as db:
            self.assertEqual(journal.workspace_revision(db),revision)
            self.assertEqual({table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in before},before)
