import copy
import unittest

import server
import test_dictionary_gloss_sync as base
import test_inline_slots


class SentenceToolsTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','seed','entries','undo','word','example','detail','link'):
        locals()[name]=getattr(base.DictionaryGlossSyncTests,name)
    draft=test_inline_slots.SlotTests.draft

    def test_infix_and_host_match_complete_script_gloss_both_sources(self):
        infix=self.api('morpheme-save',dict(form='vəʔ⁰',body=dict(gloss='neg#sub[POT]',entry_type='affix',affix_position='infix')))
        host=self.word('taku',['打过'])
        self.word('vəʔ⁰',['negPOT'])  # Flattened letters must not collapse distinct meanings.
        e=self.seed('#pass([], (([ta<vəʔ⁰>ku],[打<neg#sub[POT]>过]),([ta<vəʔ⁰>ku],[打<neg#sup[POT]>过])), [])')
        ex=self.example([('ta<vəʔ⁰>ku','打<neg#sub[POT]>过'),('ta<vəʔ⁰>ku','打<neg#sup[POT]>过')])
        for kind,r,scope in [('corpus',e,e['text_id']),('independent',ex,'@independent')]:
            with self.subTest(kind=kind):
                before=self.detail(r,kind)
                p=self.api('lexeme-auto-preview?language=ordos&text_id='+scope)
                hits=[m for m in p['matches'] if m['lexeme_id']==infix['id']]
                self.assertEqual(len(hits),1,p)
                self.assertFalse(p['ambiguous'])
                self.assertEqual(len([m for m in p['matches'] if m['lexeme_id']==host['id']]),2)
                result=self.api('lexeme-auto-link',dict(token=p['token'],text_id=scope))
                self.assertEqual(result['count'],3)
                fresh=self.detail(r,kind)
                self.assertEqual([w['gloss'] for w in fresh['body']['words']],[w['gloss'] for w in before['body']['words']])
                self.assertTrue(all(not t.get('segmentation_review') for t in fresh['body'].get('targets',[])))
                self.assertEqual(self.undo()[0],200)
                self.assertEqual([(m['unit_id'],m['lexeme_id']) for m in self.api('lexeme-auto-preview?language=ordos&text_id='+scope)['matches']],[(m['unit_id'],m['lexeme_id']) for m in p['matches']])

    def test_simple_infix_matches_without_script_and_ambiguity_is_retained(self):
        self.word('l',['NOM','NOM'])
        e=self.seed('#pass([], (([so<l>ma],[home<NOM>]),([so<lma],[home<NOM>]),), [])')
        p=self.api('lexeme-auto-preview?language=ordos&text_id='+e['text_id'])
        self.assertEqual(len(p['ambiguous']),1)
        self.assertEqual(p['matches'],[])
        self.assertEqual(len(p['ambiguous'][0]['candidates']),2)

    def test_scripted_unsplit_word_does_not_create_duplicate_morpheme_link(self):
        self.word('l',['neg#sub[POT]'])
        e=self.seed('#pass([], (([l],[neg#sub[POT]]),), [])')
        self.example([('l','neg#sub[POT]')])
        for scope in (e['text_id'],'@independent'):
            p=self.api('lexeme-auto-preview?language=ordos&text_id='+scope)
            self.assertEqual(len(p['matches']),1,p)
            self.assertEqual(p['matches'][0]['kind'],'word')
            self.assertEqual(self.api('lexeme-auto-link',dict(token=p['token'],text_id=scope))['count'],1)

    def test_merging_bound_left_word_keeps_typed_gloss_as_override(self):
        x=self.word('go',['去'])
        for kind in ('corpus','independent'):
            r=self.seed('#pass([], (([go],[去]),([n],[NOM])), [])') if kind=='corpus' else self.example([('go','去'),('n','NOM')])
            self.link(r,x,'@word',kind=kind)
            d=self.draft(kind,r);left=d['slot_ids'][0]
            d['body']['words'][0].update(form='gon',gloss='去NOM')
            d['body']['words'].pop();d['slot_ids'].pop();d['delete_confirmed']=True
            self.api('inline-save',d)
            fresh=self.draft(kind,r)
            self.assertEqual(fresh['slot_ids'],[left]);self.assertEqual(fresh['body']['words'][0]['gloss'],'去NOM')
            latest=self.api('lexeme?id='+x['id']);latest['body']['usages'][0]['senses'][0]['short_gloss']='移动'
            self.api('lexeme-save',latest)
            self.assertEqual(self.draft(kind,r)['body']['words'][0]['gloss'],'去NOM')
            latest=self.api('lexeme?id='+x['id']);latest['body']['usages'][0]['senses'][0]['short_gloss']='去';self.api('lexeme-save',latest)

    def test_merge_preserves_layers_manual_analysis_links_and_single_undo(self):
        x=self.word('l',['NOM'])
        for kind in ('corpus','independent'):
            with self.subTest(kind=kind):
                pairs=[('a','A'),('so<l>ma','home<NOM>'),('tail','TAIL')]
                r=self.seed('#pass([ipa], (([a],[A]),([so<l>ma],[home<NOM>]),([tail],[TAIL])), [free])') if kind=='corpus' else self.example(pairs)
                self.link(r,x,'0:infix:0',word=1,kind=kind)
                d=self.detail(r,kind)
                self.api('segmentation-save',dict(kind=kind,id=r['id'],revision=d['revision'],word=1,action='confirm-infix'))
                layer=self.api('layer-save',dict(name='merge '+kind,font='Junicode',style='normal'))
                layers=self.api('layers?language=ordos');layer=next(l for l in layers if l['name']=='merge '+kind)
                d=self.draft(kind,r);a,b,c=d['slot_ids']
                self.api('annotation-save',{**d,'cells':[dict(unit_id=a,layer_id=layer['id'],value='left'),dict(unit_id=b,layer_id=layer['id'],value='right')]})
                before=self.draft(kind,r);d=copy.deepcopy(before)
                d['body']['words'][0]['form']+=d['body']['words'][1]['form'];d['body']['words'][0]['gloss']+=d['body']['words'][1]['gloss']
                del d['slot_ids'][1];del d['body']['words'][1]
                d['cells']=[dict(unit_id=a,layer_id=layer['id'],value='left right')];d['delete_confirmed']=True
                self.api('inline-save',d)
                fresh=self.draft(kind,r)
                self.assertEqual(fresh['slot_ids'],[a,c])
                self.assertEqual(fresh['body']['words'][0]['form'],'aso<l>ma')
                self.assertEqual(fresh['body']['orphaned_morphology'][0]['form'],'so<l>ma')
                self.assertIn('infix_confirmation',fresh['body']['orphaned_morphology'][0])
                current=self.api('annotations?kind='+kind+'&id='+r['id'])
                self.assertTrue(any(v['unit_id']==b and v['value']=='right' for v in current['orphaned']))
                if kind=='independent':self.assertTrue(fresh['body']['targets'][0]['segmentation_ref']['detached'])
                else:
                    with server.connect(audit=False) as db:
                        self.assertEqual(db.execute('SELECT u.active FROM corpus_units u JOIN lexical_links l ON l.unit_id=u.id WHERE l.lexeme_id=?',(x['id'],)).fetchone()[0],0)
                self.assertEqual(self.undo()[0],200)
                restored=self.draft(kind,r)
                self.assertEqual(restored['slot_ids'],before['slot_ids'])
                self.assertEqual([{k:v for k,v in c.items() if k!='revision'} for c in restored['cells']],[{k:v for k,v in c.items() if k!='revision'} for c in before['cells']])
                self.assertEqual([(w['form'],w['gloss'],w.get('infix_confirmation'),w.get('morph_groups')) for w in restored['body']['words']],[(w['form'],w['gloss'],w.get('infix_confirmation'),w.get('morph_groups')) for w in before['body']['words']])
                self.assertEqual(self.call('/api/inline-save',d)[0],400)  # Stale draft cannot overwrite undo.


if __name__=='__main__':unittest.main()
