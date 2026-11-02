import copy
import re
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import corpus
import morpheme_colors
import paradigms
import server
import test_dictionary_gloss_sync as base


class SuperscriptTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','seed','entries','undo','word','example','detail','link'):
        locals()[name]=getattr(base.DictionaryGlossSyncTests,name)

    def test_parse_display_search_export_and_ranges_for_all_scripts(self):
        for script in ('sub','sup','super'):
            with self.subTest(script=script):
                form='t#'+script+'[h]-na';gloss='ROOT-NOM#'+script+'[2]'
                source=f'#pass([IPA#{script}[1]], (([{form}],[{gloss}]),), [Translation#{script}[2]])'
                rows,errors=corpus.parse(source);self.assertFalse(errors);e=rows[0];self.assertFalse(e['warnings'])
                w=e['words'][0];self.assertEqual(w['morphemes'][0]['form'],'th');self.assertEqual(w['morphemes'][0]['display_form'],'t#'+script+'[h]')
                self.assertEqual(w['morphemes'][1]['display_gloss'],'NOM#'+script+'[2]')
                plain,mapping=morpheme_colors.plain_map(form);self.assertEqual(plain,'th-na');self.assertEqual(form[mapping[1][0]:mapping[1][1]],'#'+script+'[h]')
                self.assertEqual(corpus.match(e,'th','form')[0],[0]);self.assertEqual(corpus.match(e,'2','gloss')[0],[0])
                self.assertIn(form,corpus.export_entry(e));self.assertIn(gloss,corpus.export_entry(e))
                self.assertEqual(paradigms.compose('N#'+script+'[2]','PL'),'N#'+script+'[2].PL')
        host=corpus.analyze(dict(ipa='',translation='',words=[dict(form='t#sup[h]<n>ri',gloss='ro<ASP>ot')]))['words'][0]['morphemes'][0]
        self.assertEqual(host['display_form'],'t#sup[h]…ri');self.assertEqual(host['display_lookup_form'],'t#sup[h]ri')
        unsupported=corpus.analyze(dict(ipa='#other[1]',translation='',words=[dict(form='a',gloss='N')]))
        self.assertTrue(unsupported['warnings'])

    def test_registry_inline_save_and_read_only_projection_keep_source(self):
        for script in ('sup','super'):
            tag='NEG#'+script+'[POT]';self.api('grammar-save',dict(symbol=tag,description='negative'))
            record=self.example([('a#'+script+'[h]',tag)])
            d=self.api('annotations?kind=independent&id='+record['id']);d['body']['notes']='note#'+script+'[1]'
            self.api('inline-save',dict(kind='independent',id=record['id'],revision=d['revision'],body=d['body'],before=d['cells'],cells=d['cells'],layers=d['layers'],slot_ids=[w['id'] for w in d['words']]))
            fresh=self.detail(record,'independent')['body'];self.assertEqual(fresh['words'][0]['form'],'a#'+script+'[h]');self.assertEqual(fresh['words'][0]['gloss'],tag)
            self.assertEqual(fresh['notes'],'note#'+script+'[1]');self.assertFalse(fresh['warnings'])

    def test_auto_links_both_superscript_spellings_in_text_and_independent_examples(self):
        x=self.word('n#super[h]',['NEG#super[POT]'])
        self.word('n#sub[h]',['NEG#sub[POT]'])
        e=self.seed('#pass([], (([n#sup[h]],[NEG#sup[POT]]),), [])');ind=self.example([('n#super[h]','NEG#sup[POT]')])
        p=self.api('lexeme-auto-preview?language=ordos')
        self.assertEqual(len(p['matches']),2,p);self.assertFalse(p['ambiguous']);self.assertEqual({r['lexeme_id'] for r in p['matches']},{x['id']})
        self.assertEqual({r['display_gloss'] for r in p['matches']},{'NEG#sup[POT]'})
        self.api('lexeme-auto-link',dict(token=p['token']))
        self.assertEqual(self.entries()[0]['words'][0]['form'],'n#sup[h]')
        self.assertFalse(any(t.get('segmentation_review') for t in self.detail(ind,'independent')['body']['targets']))
        self.assertEqual(self.undo()[0],200)
        native=self.api('morpheme-save',dict(form='k#super[h]',body=dict(gloss='ASP#super[2]')))
        self.seed('#pass([], (([k#sup[h]],[ASP#sup[2]]),), [])')
        ex=self.example([('k#sup[h]','ASP#sup[2]')])
        p=self.api('lexeme-auto-preview?language=ordos')
        hits=[r for r in p['matches'] if r['lexeme_id']==native['id']]
        self.assertEqual(len(hits),2);self.assertEqual({r['target_kind'] for r in hits},{'morpheme'})
        self.api('lexeme-auto-link',dict(token=p['token']))
        self.assertEqual(self.api('morpheme?id='+native['id'])['form'],'k#super[h]')
        self.assertEqual(self.detail(ex,'independent')['body']['words'][0]['form'],'k#sup[h]')

    def test_morpheme_link_and_form_sync_preserve_script_function(self):
        for script in ('sub','sup','super'):
            x=self.word('n'+script,['NOM'])
            form='#'+script+'[n'+script+']'
            e=self.seed(f'#pass([], (([{form}],[NOM]),), [])')
            e=next(r for r in self.entries() if r['words'][0]['form']==form)
            self.link(e,x,'0:host');d=self.detail(e)['body']['words'][0]
            uid=d['morphemes'][0]['unit_id'];info=self.api('unit-dictionary?id='+uid)
            self.assertEqual(info['display_form'],form)
            self.assertEqual(self.api('lexeme-examples?id='+x['id'])['items'][0]['display_form'],form)
            x=self.api('lexeme?id='+x['id']);x['headword']='m'+script;self.api('lexeme-save',x)
            self.assertEqual(self.detail(e)['body']['words'][0]['form'],'#'+script+'[m'+script+']')

    def test_existing_superscript_links_survive_read_and_save(self):
        # Reproduce the earlier parser, which flattened sub but not sup/super.
        def old_plain(value):return re.sub(r'#sub\[([^\[\]]*)\]',r'\1',value)
        x=self.word('h',['ASP']);form='t#sup[h]-na';gloss='ROOT#super[2]-NOM'
        with patch('corpus.plain',old_plain):
            text=self.seed(f'#pass([], (([{form}],[{gloss}]),), [])')
            ind=self.example([(form,gloss)])
            for kind,r in [('corpus',text),('independent',ind)]:self.link(r,x,'0:host',kind=kind,sense=None)
            oldid=self.detail(text)['body']['words'][0]['morphemes'][0]['unit_id']
        for kind,r in [('corpus',text),('independent',ind)]:
            with self.subTest(kind=kind):
                d=self.detail(r,kind);self.assertFalse(any(t.get('segmentation_review') for t in d['body'].get('targets',[])))
                a=self.api('annotations?kind='+kind+'&id='+r['id']);a['body']['notes']='keep references'
                self.api('inline-save',dict(kind=kind,id=r['id'],revision=a['revision'],body=a['body'],before=a['cells'],cells=a['cells'],layers=a['layers'],slot_ids=[w['id'] for w in a['words']]))
        self.assertEqual(self.detail(text)['body']['words'][0]['morphemes'][0]['unit_id'],oldid)
        self.assertFalse(any(t.get('segmentation_review') for t in self.detail(ind,'independent')['body']['targets']))
