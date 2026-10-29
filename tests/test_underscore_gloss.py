import copy,json,unittest
import corpus,grammar,lexicon,paradigms,script_tags,server
import test_sentence_dictionary as base
import test_inline_slots
import test_paradigm_inheritance as inherited

class UnderscoreGlossTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo'):
        locals()[name]=getattr(base.SentenceDictionaryTests,name)

    def test_underscores_stay_inside_one_morpheme_and_survive_empty_cell_cleanup(self):
        for gloss in ['look_after','看_起来','NOM_SG','_edge_','look__after','NEG#sub[POT]_meaning','meaning_NEG#sub[POT]']:
            with self.subTest(gloss=gloss):
                w=corpus.analyze(dict(ipa='',translation='',words=[dict(form='x',gloss=gloss)]))['words'][0]
                self.assertEqual(len(w['morphemes']),1)
                self.assertEqual(corpus.normalize_edited_pair('x',gloss),('x',gloss))
        self.assertEqual(corpus.normalize_edited_pair('x-y','look_after-PL'),('x-y','look_after-PL'))

    def test_tags_do_not_match_inside_underscore_text_even_with_script_runs(self):
        tags=[dict(id='pst',language_id='ordos',symbol='PST',aliases=[]),dict(id='neg',language_id='ordos',symbol='neg#sub[POT]',aliases=[])]
        lookup=grammar.index(tags)
        for value in ['look_PST','PST_look','[look_PST]','look_neg#sub[POT]','neg#sub[POT]_look','看_neg#sub[POT]']:
            self.assertEqual(list(grammar.tokens(value,'ordos',lookup)),[],value)
        self.assertEqual(list(grammar.tokens('look_after.PST-neg#sub[POT]','ordos',lookup)),['PST','neg#sub[POT]'])
        self.assertNotIn('neg#sub[POT]',list(grammar.tokens('look_neg#sub[POT]','ordos',lookup,lower=True,candidates=True)))

    def test_a_registered_underscore_symbol_is_one_tag_including_aliases(self):
        t=self.api('grammar-save',dict(symbol='NOM_SG',aliases=['nom_sg_alias']))
        lookup=grammar.index(self.api('grammar-tags?language=ordos'))
        self.assertEqual(list(grammar.tokens('look_after.NOM_SG','ordos',lookup)),['NOM_SG'])
        self.assertEqual(list(grammar.tokens('nom_sg_alias','ordos',lookup)),['nom_sg_alias'])
        self.assertEqual(list(grammar.tokens('NOM_SG_extra','ordos',lookup)),[])
        self.assertEqual(lexicon.auto_gloss_key('look_after.NOM_SG',{'nom_sg':t['id']}),('ordinary','look_after',(t['id'],)))

    def test_old_sentence_read_edit_undo_and_export_keep_literal_underscores(self):
        for kind in ('corpus','independent'):
            src=self.source(kind,[('x','look_after'),('y','看_起来.PST')]);before=self.detail(src)
            d=test_inline_slots.SlotTests.draft(self,kind,src)
            ids=d['slot_ids'][:];d['body']['words'][0]['gloss']='look__after_'
            self.api('inline-save',d)
            saved=self.detail(src);self.assertEqual(saved['body']['words'][0]['gloss'],'look__after_')
            self.assertEqual(test_inline_slots.SlotTests.draft(self,kind,src)['slot_ids'],ids)
            self.undo();self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'look_after')
            self.undo(True);self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'look__after_')
            self.assertEqual(before['body']['words'][0]['form'],self.detail(src)['body']['words'][0]['form'])
            if kind=='corpus':
                with server.connect(audit=False) as db:tid=db.execute('SELECT text_id FROM entries WHERE id=?',(src['id'],)).fetchone()[0]
                self.assertIn('look__after_',self.api('export?id='+tid))

    def test_exact_auto_links_do_not_equate_underscores_with_tag_separators(self):
        self.api('grammar-save',dict(symbol='PST'))
        self.api('lexeme-save',dict(headword='x',body=dict(usages=[dict(senses=[dict(short_gloss='look_PST')])])) )
        for kind in ('corpus','independent'):self.source(kind,[('x','look_PST'),('x','look.PST'),('x','PST_look')])
        p=self.api('lexeme-auto-preview?language=ordos');self.assertEqual(len(p['matches']),2)
        self.api('lexeme-auto-link',dict(token=p['token']))

    def test_paradigm_inheritance_and_template_additions_accept_whole_underscore_atoms(self):
        self.assertEqual(paradigms.compose('look_after','PST'), 'look_after.PST')
        self.assertEqual(paradigms.compose('NOM_SG','NOM.SG'), 'NOM_SG.NOM.SG')
        self.assertEqual(paradigms.addition('NOM_SG.NOM_SG.PST'),'NOM_SG.PST')
        b=inherited.body();b['usages'][0]['senses'][0]['short_gloss']='look_after'
        for row in b['paradigms'][0]['rows']:
            row['gloss_addition']='NOM_SG'
            for form in row['realizations']:form['meanings'][0]['gloss_addition']='NOM_SG'
        language=self.api('languages')[0];metadata=json.loads(language['metadata'])
        metadata['paradigm_templates']=[copy.deepcopy(b['paradigms'][0])]
        self.api('save-language',dict(id=language['id'],revision=language['revision'],name=language['name'],metadata=metadata))
        self.assertEqual(json.loads(self.api('languages')[0]['metadata'])['paradigm_templates'][0]['rows'][0]['gloss_addition'],'NOM_SG')
        x=self.api('lexeme-save',dict(headword='x',body=b))
        self.assertEqual(paradigms.usages(x['body'])[0]['senses'][1]['short_gloss'],'look_after.NOM_SG')
        for kind in ('corpus','independent'):
            src=self.source(kind,[('went','')]);args=self.args(src);p=self.api('sentence-gloss-preview',args)
            row=next(r for r in p['rows'] if r['word']==0);self.assertTrue(row['automatic'])
            self.api('sentence-gloss-apply',dict(args,token=p['token'],choices=[dict(word=0,key=row['key'],candidate_id=row['candidates'][0]['id'])]))
            self.assertEqual(self.detail(src)['body']['words'][0]['gloss'],'look_after.NOM_SG')

    def test_completion_feature_append_does_not_find_a_tag_inside_underscore_text(self):
        t=self.api('grammar-save',dict(symbol='PST'))
        x=self.api('lexeme-save',dict(headword='x',body=dict(usages=[dict(features=[t['id']],senses=[dict(short_gloss='look_PST')])])) )
        for kind in ('corpus','independent'):
            src=self.source(kind,[('x','')]);p=self.api('sentence-gloss-preview',self.args(src))
            self.assertEqual(p['rows'][0]['candidates'][0]['gloss'],'look_PST.PST')

    def test_audit_and_analysis_do_not_count_substrings_as_tags(self):
        t=self.api('grammar-save',dict(symbol='PST'))
        for kind in ('corpus','independent'):self.source(kind,[('x','look_PST'),('y','look_after.PST')])
        audit=self.api('grammar-audit?language=ordos&issue=usage&tag='+t['id'])
        self.assertEqual(next(row for row in audit['tags'] if row['id']==t['id'])['uses'],2)
        run=self.api('analysis-run',dict(query=dict(conditions=[dict(field='tag',value='PST',mode='exact')],scope=dict(source='all'))))
        self.assertEqual(run['summary']['sentences'],2)

    def test_script_recovery_does_not_infer_a_tag_from_inside_underscore_text(self):
        self.source('corpus',[('x','look_neg#sub[POT]'),('y','neg#sub[POT]_meaning')])
        t=self.api('grammar-save',dict(symbol='negPOT'))
        with server.connect() as db:script_tags.recover(db,force=True)
        self.assertEqual(self.api('grammar-tags?language=ordos')[0]['symbol'],'negPOT')

    def test_bound_meaning_replacement_never_preserves_half_an_underscore_atom(self):
        from dictionary_gloss_sync import replace_short
        for value in ['SG_GEN','GEN#sub[2]_text','#sup[GEN]_text','text_GEN#sub[2]']:
            self.assertEqual(replace_short(value,'GEN','POSS'),'POSS')
        self.assertEqual(replace_short('look_after.GEN','GEN','POSS'),'look_after.POSS')
        self.assertEqual(replace_short('look_after.PL','look_after','care_for'),'care_for.PL')

