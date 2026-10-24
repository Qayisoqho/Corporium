import undo_codec
import unittest
import json
import corpus
import grammar
import script_tags
import server
import test_grammar

class ScriptTagTests(unittest.TestCase):
    setUp=test_grammar.GrammarTests.setUp
    tearDown=test_grammar.GrammarTests.tearDown
    call=test_grammar.GrammarTests.call
    seed=test_grammar.GrammarTests.seed
    entries=test_grammar.GrammarTests.entries
    tag=test_grammar.GrammarTests.tag
    word=test_grammar.GrammarTests.word
    link=test_grammar.GrammarTests.link
    SOURCE='#pass([], (([ta<ve>ku+le=hie],[打<neg#sub[POT]>过+来=PRT]),), [])'

    def test_derived_display_preserves_identity_and_api(self):
        e=self.seed(self.SOURCE)
        m=e['words'][0]['morphemes'][1]
        self.assertEqual(m['gloss'],'negPOT')
        self.assertEqual(m['display_gloss'],'neg#sub[POT]')
        uid=m['unit_id']
        x=self.word()
        # A linked occurrence now inherits its selected dictionary meaning.
        # Use the scripted label in that meaning to test display preservation.
        x['body']['usages'][0]['senses'][0]['short_gloss']='neg#sub[POT]'
        code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x)
        self.link(uid,x)
        examples=self.call('/api/lexeme-examples?id='+x['id'])[1]['items']
        self.assertEqual(examples[0]['display_gloss'],'neg#sub[POT]')
        code,d=self.call('/api/unit-dictionary?id='+uid)
        self.assertEqual(code,200,d)
        self.assertEqual(d['display_gloss'],'neg#sub[POT]')
        self.assertEqual(d['link']['lexeme_id'],x['id'])
        self.assertEqual(self.entries()[0]['words'][0]['morphemes'][1]['unit_id'],uid)
        code,d=self.call('/api/segmentation?kind=corpus&id='+e['id'])
        self.assertEqual(code,200,d)
        self.assertEqual(d['body']['words'][0]['morphemes'][1]['display_gloss'],'neg#sub[POT]')
        unknown=self.call('/api/grammar-audit?lower=true')[1]['unknown']
        self.assertIn('neg#sub[POT]',[t['symbol'] for t in unknown])
        self.assertNotIn('negPOT',[t['symbol'] for t in unknown])

    def test_legacy_tag_recovery_is_unambiguous_idempotent_and_undo_safe(self):
        self.seed(self.SOURCE);old=self.tag('negPOT')
        with server.connect() as db:script_tags.recover(db,force=True)
        tags=self.call('/api/grammar-tags?language=ordos')[1]
        t=next(t for t in tags if t['id']==old['id'])
        self.assertEqual(t['symbol'],'neg#sub[POT]');self.assertIn('negPOT',t['aliases'])
        with server.connect() as db:
            script_tags.recover(db,force=True)
            for step in db.execute('SELECT changes FROM undo_steps'):
                for c in undo_codec.decode(step[0]):
                    for side in ('before','after'):
                        if c['table']=='grammar_tags' and c[side] and c[side]['id']==old['id']:
                            self.assertEqual(c[side]['symbol'],'neg#sub[POT]')
        self.assertEqual(self.call('/api/grammar-tags?language=ordos')[1],tags)

    def test_no_guessing_when_source_has_two_script_spellings(self):
        self.seed(self.SOURCE);self.seed(self.SOURCE.replace('#sub[POT]','#sup[POT]'))
        self.tag('negPOT')
        with server.connect() as db:script_tags.recover(db,force=True)
        self.assertEqual(self.call('/api/grammar-tags?language=ordos')[1][0]['symbol'],'negPOT')

    def test_all_script_commands_keep_display(self):
        for syntax in ('sub','sup','super'):
            label='neg#'+syntax+'[POT]'
            w=corpus.analyze(dict(ipa='',translation='',words=[dict(form='a<b>c',gloss='打<'+label+'>过')]))['words'][0]
            self.assertEqual(w['morphemes'][1]['display_gloss'],label)

if __name__=='__main__':unittest.main()
