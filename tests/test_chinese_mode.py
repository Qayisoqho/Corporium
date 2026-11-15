import source_fixtures
import copy
import json
import unittest
from unittest import mock

import chinese_mode
import dictionary_form_sync
import server
import test_lexicon


class ChineseModeTests(unittest.TestCase):
    for helper in ('setUp','tearDown','call','seed','entries','undo','link'):
        locals()[helper]=getattr(test_lexicon.LexiconTests,helper)

    def api(self,path,body=None):
        code,value=self.call('/api/'+path,body)
        self.assertEqual(code,200,value)
        return value

    def enable(self,lid='ordos',enabled=True):
        row=next(r for r in self.api('languages') if r['id']==lid)
        metadata=json.loads(row['metadata'])
        self.api('save-language',dict(id=lid,revision=row['revision'],name=row['name'],
                 metadata={**metadata,'chinese_mode':enabled},_language=lid))

    def body(self,forms=('学','生'),joiner=''):
        return dict(headword_source=dict(analysis_id='main',joiner=joiner),
                    word_structure=dict(analyses=[dict(id='main',components=[
                        dict(id='part'+str(i),form=form,gloss='meaning'+str(i),readings=['reading'+str(i)])
                        for i,form in enumerate(forms)])]))

    def word(self,forms=('学','生'),joiner=''):
        self.enable()
        return self.api('lexeme-save',dict(headword='untrusted-client-preview',body=self.body(forms,joiner)))

    def test_language_switch_is_strict_and_independent_entries_are_preserved(self):
        old=self.api('lexeme-save',dict(headword='自由形式',body={}))
        self.assertEqual(self.call('/api/lexeme-save',dict(headword='学生',body=self.body()))[0],400)
        for invalid in ('true',1,None):
            self.assertEqual(self.call('/api/save-language',dict(name='Invalid',metadata={'chinese_mode':invalid}))[0],400)
        with mock.patch('lexicon.validate_links',side_effect=AssertionError('mode-only save must not scan dictionary')):
            self.enable()
        self.assertEqual(self.api('lexeme?id='+old['id'])['headword'],'自由形式')
        independent=self.api('lexeme-save',dict(headword='独立词形',body={'headword_source':None}))
        self.assertEqual(independent['headword'],'独立词形')

    def test_authoritative_joiner_and_stable_source_survive_reopen(self):
        x=self.word(('multi-character','form'),' ')
        self.assertEqual(x['headword'],'multi-character form')
        self.assertEqual(x['body']['headword_source'],dict(analysis_id='main',joiner=' '))
        self.assertEqual(self.api('lexeme?id='+x['id'])['body']['headword_source'],x['body']['headword_source'])
        x['headword']='client-edited';x['body'].pop('headword_source')
        saved=self.api('lexeme-save',x)
        self.assertEqual(saved['headword'],'multi-character form')
        self.assertEqual([c['id'] for c in saved['body']['word_structure']['analyses'][0]['components']],['part0','part1'])

    def test_turning_off_language_mode_preserves_existing_source_and_explicit_opt_out(self):
        x=self.word();self.enable(enabled=False)
        x=self.api('lexeme?id='+x['id']);x['body']['notes']='edit while disabled'
        x=self.api('lexeme-save',x)
        self.assertEqual(x['headword'],'学生')
        x['body']['headword_source']=None;x['headword']='freely entered'
        x=self.api('lexeme-save',x)
        self.assertEqual(x['headword'],'freely entered')
        x['body']['headword_source']=dict(analysis_id='main',joiner='')
        self.assertEqual(self.call('/api/lexeme-save',x)[0],400)

    def test_leaf_forms_exclude_group_labels_and_other_analyses(self):
        x=self.word()
        analysis=x['body']['word_structure']['analyses'][0]
        analysis['components'].insert(0,dict(id='group',form='group label'))
        for c in analysis['components'][1:]:c['parent_id']='group'
        x['body']['word_structure']['analyses'].append(dict(id='other',components=[dict(id='otherpart',form='unrelated')]))
        self.assertEqual(self.api('lexeme-save',x)['headword'],'学生')

    def test_invalid_source_and_noncontinuous_leaf_are_atomic(self):
        x=self.word();before=self.api('undo-state')
        invalid_joiners=[dict(analysis_id='main',joiner=value) for value in ('\n','\r','\x85','\u2028','\u2029')]
        for source in (dict(analysis_id='missing'),*invalid_joiners,{},'main'):
            candidate=copy.deepcopy(x);candidate['body']['headword_source']=source
            self.assertEqual(self.call('/api/lexeme-save',candidate)[0],400)
        candidate=copy.deepcopy(x);candidate['body']['word_structure']['analyses'][0]['components'][0]['segments']=['a','b']
        self.assertEqual(self.call('/api/lexeme-save',candidate)[0],400)
        self.assertEqual(self.api('lexeme?id='+x['id']),x)
        self.assertEqual(self.api('undo-state'),before)

    def test_legacy_unicode_separator_can_be_repaired_without_blocking_other_entries(self):
        word=self.word()
        other=self.api('lexeme-save',dict(headword='independent',body={}))
        legacy=copy.deepcopy(word['body']);legacy['headword_source']['joiner']='\u2028'
        with server.connect(audit=False) as db:
            source_fixtures.replace(db,'lexemes',word['id'],json.dumps(legacy),columns=dict(headword='学\u2028生'))
        other['headword']='another form'
        self.assertEqual(self.api('lexeme-save',other)['headword'],'another form')
        draft=self.api('lexeme?id='+word['id'])
        self.assertEqual(draft['headword'],'学\u2028生')
        draft['body']['headword_source']['joiner']=''
        self.assertEqual(self.api('lexeme-save',draft)['headword'],'学生')
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.api('lexeme?id='+word['id'])['headword'],'学\u2028生')

    def test_regular_preview_creates_linked_morphemes_in_one_undo(self):
        self.enable();body=self.body()
        plan=self.api('morpheme-save-preview',dict(body=body))
        old=self.api('undo-state')
        x=self.api('lexeme-save',dict(headword='学生',body=body,morpheme_confirmation=plan['token']))
        links=self.api('morpheme-components?id='+x['id'])['items']
        self.assertTrue(all(r['link'] for r in links))
        self.assertEqual(self.api('dictionary-counts'),dict(lexemes=1,morphemes=2))
        self.assertEqual(len(self.api('undo-state')['steps']),len(old['steps'])+1)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.api('dictionary-counts'),dict(lexemes=0,morphemes=0))
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.api('lexeme?id='+x['id'])['headword'],'学生')
        self.assertTrue(all(r['link'] for r in self.api('morpheme-components?id='+x['id'])['items']))

    def test_explicit_variant_is_projected_before_headword_and_collision_checks(self):
        self.enable()
        m=self.api('morpheme-save',dict(form='base',body=dict(gloss='g',variants=[dict(form='variant')])) )
        form_id=m['body']['variants'][0]['id'];body=self.body(('outdated-component',))
        assignments=[dict(analysis_id='main',component_id='part0',morpheme_id=m['id'],form_id=form_id)]
        plan=self.api('morpheme-save-preview',dict(body=body,assignments=assignments))
        x=self.api('lexeme-save',dict(headword='wrong-preview',body=body,morpheme_assignments=assignments,morpheme_confirmation=plan['token']))
        self.assertEqual(x['headword'],'variant')
        self.assertEqual(x['body']['word_structure']['analyses'][0]['components'][0]['form'],'variant')
        m=self.api('morpheme?id='+m['id']);m['body']['variants'][0]['form']='renamed'
        self.api('morpheme-save',m)
        self.assertEqual(self.api('lexeme?id='+x['id'])['headword'],'renamed')

    def test_shared_rename_local_override_and_homonym_numbering_undo(self):
        self.enable()
        m=self.api('morpheme-save',dict(form='学',body={'gloss':'g'}))
        body=self.body(('学',))
        assignments=[dict(analysis_id='main',component_id='part0',morpheme_id=m['id'],form_id=None)]
        plan=self.api('morpheme-save-preview',dict(body=body,assignments=assignments))
        x=self.api('lexeme-save',dict(headword='学',body=body,morpheme_assignments=assignments,morpheme_confirmation=plan['token']))
        other=self.api('lexeme-save',dict(headword='learn',body={}))
        m=self.api('morpheme?id='+m['id']);m['form']='learn';self.api('morpheme-save',m)
        changed=self.api('lexeme?id='+x['id']);peer=self.api('lexeme?id='+other['id'])
        self.assertEqual(changed['headword'],'learn')
        self.assertNotEqual(changed['body']['homonym_number'],peer['body']['homonym_number'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.api('lexeme?id='+x['id'])['headword'],'学')
        self.assertEqual(self.api('lexeme?id='+other['id'])['body']['homonym_number'],None)
        self.assertEqual(self.undo('redo')[0],200)
        local=self.api('lexeme?id='+x['id']);local['body']['word_structure']['analyses'][0]['components'][0]['form']='local'
        local=self.api('lexeme-save',local)
        m=self.api('morpheme?id='+m['id']);m['form']='later';self.api('morpheme-save',m)
        self.assertEqual(self.api('lexeme?id='+x['id'])['headword'],'local')

    def test_initial_adoption_keeps_recorded_surface_then_regular_edits_sync(self):
        self.enable()
        e=self.seed('#pass([ipa], (([old],[oldgloss])), [translation])')
        body=self.body(('new',));body.pop('headword_source')
        body['usages']=[dict(pos='N',senses=[dict(short_gloss='oldgloss')])]
        x=self.api('lexeme-save',dict(headword='old',body=body))
        self.link(e['words'][0]['unit_id'],x)
        x=self.api('lexeme?id='+x['id']);x['body']['headword_source']=dict(analysis_id='main',joiner='')
        x=self.api('lexeme-save',x)
        self.assertEqual(x['headword'],'new')
        self.assertEqual(self.entries()[0]['words'][0]['form'],'old')
        x['body']['word_structure']['analyses'][0]['components'][0]['form']='newer'
        self.assertEqual(self.api('lexeme-save',x)['headword'],'newer')
        # The independent old surface stays local, rather than a substring match.
        self.assertEqual(self.entries()[0]['words'][0]['form'],'old')

    def test_source_change_remains_conflict_checked(self):
        x=self.word();other=copy.deepcopy(x)
        x['body']['word_structure']['analyses'][0]['components'][0]['form']='先'
        self.api('lexeme-save',x)
        other['body']['word_structure']['analyses'][0]['components'][0]['form']='后'
        self.assertEqual(self.call('/api/lexeme-save',other)[0],400)
        self.assertEqual(self.api('lexeme?id='+x['id'])['headword'],'先生')

    def test_import_export_preserves_source_and_form_with_fresh_owner_ids(self):
        x=self.word()
        bundle=self.api('export-language?language=ordos')
        lid=self.api('save-language',dict(name='Imported',metadata={}))['id']
        self.api('import-language',dict(_language=lid,bundle=bundle))
        copied=self.api('lexemes?language='+lid)['items'][0]
        self.assertNotEqual(copied['id'],x['id'])
        self.assertEqual(copied['headword'],'学生')
        self.assertEqual(copied['body']['headword_source'],x['body']['headword_source'])
        copied['body']['notes']='retained provenance'
        self.assertEqual(self.api('lexeme-save',dict(**copied,_language=lid))['headword'],'学生')

    def test_dictionary_copy_remaps_source_and_preserves_it_with_default_mode_off(self):
        x=self.word();self.enable(enabled=False)
        copied=self.api('dictionary-copy',dict(id=x['id'],revision=x['revision'],kind='lexeme',confirmed=True))
        self.assertEqual(copied['headword'],'学生')
        source=copied['body']['headword_source']
        self.assertNotEqual(source['analysis_id'],x['body']['headword_source']['analysis_id'])
        self.assertEqual(source['analysis_id'],copied['body']['word_structure']['analyses'][0]['id'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/lexeme?id='+copied['id'])[0],400)
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.api('lexeme?id='+copied['id'])['body']['headword_source'],source)

    def linked_source(self,variant=False):
        self.enable()
        native=dict(gloss='meaning',readings=['reading'])
        if variant:native['variants']=[dict(id='variant',form='source-variant',pronunciation='variant-reading')]
        m=self.api('morpheme-save',dict(form='source',body=native))
        body=self.body(('source-variant' if variant else 'source',))
        assignments=[dict(analysis_id='main',component_id='part0',morpheme_id=m['id'],
                          form_id=m['body']['variants'][0]['id'] if variant else None)]
        plan=self.api('morpheme-save-preview',dict(body=body,assignments=assignments))
        x=self.api('lexeme-save',dict(headword='source',body=body,morpheme_assignments=assignments,
                                    morpheme_confirmation=plan['token']))
        return self.api('morpheme?id='+m['id']),x

    def test_native_merge_preserves_variant_source_and_all_undo_edges(self):
        source,x=self.linked_source(variant=True)
        target=self.api('morpheme-save',dict(form='target',body=dict(gloss='other',
                        variants=[dict(id='variant',form='target-variant')])))
        source=self.api('morpheme?id='+source['id'])
        merged=self.api('morpheme-merge',dict(id=source['id'],revision=source['revision'],
                    target_id=target['id'],target_revision=target['revision'],confirmed=True))
        saved=self.api('lexeme?id='+x['id'])
        link=self.api('morpheme-components?id='+x['id'])['items'][0]['link']
        self.assertEqual(saved['headword'],'source-variant')
        self.assertEqual(saved['body']['headword_source'],x['body']['headword_source'])
        self.assertEqual(link['morpheme_id'],target['id'])
        selected=next(v for v in merged['body']['variants'] if v['id']==link['form_id'])
        self.assertEqual(selected['form'],'source-variant')
        self.assertEqual(self.call('/api/morpheme?id='+source['id'])[0],400)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.api('morpheme-components?id='+x['id'])['items'][0]['link']['morpheme_id'],source['id'])
        self.assertEqual(self.undo('redo')[0],200)
        merged=self.api('morpheme?id='+target['id'])
        next(v for v in merged['body']['variants'] if v['id']==link['form_id'])['form']='new-variant'
        self.api('morpheme-save',merged)
        self.assertEqual(self.api('lexeme?id='+x['id'])['headword'],'new-variant')
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.api('lexeme?id='+x['id'])['headword'],'source-variant')

    def test_linked_delete_rejects_atomically_and_unassignment_preserves_local_form(self):
        native,x=self.linked_source()
        previous=self.api('undo-state')
        self.assertEqual(self.call('/api/morpheme-delete',native)[0],400)
        self.assertEqual(self.api('undo-state'),previous)
        link=self.api('morpheme-components?id='+x['id'])['items'][0]['link']
        self.api('morpheme-unassign',dict(id=link['id'],revision=link['revision']))
        self.assertEqual(self.api('lexeme?id='+x['id'])['headword'],'source')
        self.assertEqual(self.api('lexeme?id='+x['id'])['body']['headword_source'],x['body']['headword_source'])
        native=self.api('morpheme?id='+native['id'])
        self.api('morpheme-delete',native)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.api('morpheme-components?id='+x['id'])['items'][0]['link']['morpheme_id'],native['id'])
        self.assertEqual(self.api('lexeme?id='+x['id'])['headword'],'source')

    def test_direct_body_materialization_preserves_raw_research_fields(self):
        self.enable();raw=self.body();raw['unknown_research_field']={'text':'retain exactly'}
        x=self.api('lexeme-save',dict(headword='independent',body={}))
        with server.connect(audit=False) as db:
            chinese_mode.write_body(db,dict(id=x['id'],target_kind='lexeme'),raw)
        with server.connect(audit=False) as db:
            saved=db.execute('SELECT headword,body FROM lexemes_documents WHERE id=?',(x['id'],)).fetchone()
        self.assertEqual(saved['headword'],'学生')
        self.assertEqual(json.loads(saved['body']),raw)

    def test_full_validation_rejects_mismatched_and_malformed_source(self):
        x=self.word()
        import lexicon
        for source in ({},'',dict(analysis_id='missing')):
            body=copy.deepcopy(x['body']);body['headword_source']=source
            with server.connect(audit=False) as db:
                source_fixtures.replace(db,'lexemes',x['id'],json.dumps(body))
                with self.assertRaises(ValueError):lexicon.validate_links(db)
                db.rollback()
        with server.connect(audit=False) as db:
            db.execute('UPDATE lexemes SET headword=? WHERE id=?',('inconsistent',x['id']))
            with self.assertRaises(ValueError):lexicon.validate_links(db)
            db.rollback()


if __name__=='__main__':
    unittest.main()
