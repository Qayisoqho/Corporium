import unittest
from unittest.mock import patch
import server
import gloss_inheritance
import lexicon
import paradigms
import sense_gloss
import test_paradigms

class NumericGlossTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','undo','complete','get','gloss'):
        locals()[name]=getattr(test_paradigms.ParadigmTests,name)

    def test_digit_joining_and_ordinary_dots_share_sense_and_table_rules(self):
        for base,extra,expected in [('pron.3','sg.dat','pron.3sg.dat'),('3','SG','3SG'),('1SG','NOM','1SG.NOM'),('3#sub[POT]','SG','3#sub[POT].SG'),('take_care_of','PST','take_care_of.PST')]:
            self.assertEqual(sense_gloss.effective(dict(short_gloss=base,gloss_addition=extra)),expected)
            self.assertEqual(paradigms.compose(base,extra),expected)
        self.assertEqual(sense_gloss.effective(dict(short_gloss='pron.3',gloss_addition='SG',show_gloss_addition=False)),'pron.3')
        self.assertEqual(lexicon.auto_gloss_key('pron.3sg.dat',{}),lexicon.auto_gloss_key('pron.3.sg.dat',{}))
        self.assertEqual(paradigms.compose(sense_gloss.effective(dict(short_gloss='pron.3',gloss_addition='SG')),'SG.DAT'),'pron.3SG.DAT')

    def test_registered_person_number_suffixes_match_case_aliases_and_inherent_features(self):
        lookup={'3':'person','sg':'number','dat':'case','singular':'number'}
        key=lambda text,features=():lexicon.auto_gloss_key(text,lookup,features)
        self.assertEqual(key('pron.3sg.dat'),key('pron.3.SG.DAT'))
        self.assertEqual(key('pron.3singular.DAT'),key('pron',['person','number','case']))
        self.assertNotEqual(key('pron.3sg.sg.dat'),key('pron.3sg.dat'))
        self.assertNotEqual(key('pron_3sg.dat'),key('pron.3sg.dat'))
        self.assertNotEqual(key('root-3SG.DAT'),key('root.3SG.DAT'))
        self.assertNotEqual(key('pron.3SG_NOM'),key('pron.3SG.NOM'))

    def test_lexeme_morpheme_and_table_match_pron_3sg_dat_in_both_sentence_kinds(self):
        for symbol in ('3','SG','DAT'):self.api('grammar-save',dict(symbol=symbol))
        self.api('lexeme-save',dict(headword='lex',body=dict(usages=[dict(senses=[dict(short_gloss='pron.3',gloss_addition='SG.DAT')])])) )
        self.api('morpheme-save',dict(form='mor',body=dict(gloss='pron.3',gloss_addition='SG.DAT')))
        body=test_paradigms.body();body['usages'][0]['senses'][0]['short_gloss']='pron.3'
        body['paradigms'][0]['rows'][0]['realizations'][0]['meanings'][0].update(gloss_mode='inherit',gloss_addition='SG.DAT')
        self.api('lexeme-save',dict(headword='base',body=body))
        for kind in ('corpus','independent'):self.source(kind,[(form,'pron.3sg.dat') for form in ('lex','mor','went')])
        plan=self.api('lexeme-auto-preview?language=ordos')
        self.assertEqual(len(plan['matches']),6);self.assertEqual(plan['ambiguous'],[])
        self.api('lexeme-auto-link',dict(token=plan['token']))
        self.assertEqual(self.api('lexeme-auto-preview?language=ordos')['already_linked'],6)

    def test_old_computed_labels_refresh_once_without_rewriting_sources_or_overrides(self):
        with patch.object(sense_gloss,'join',side_effect=lambda parts:'.'.join(parts)):
            x=self.api('lexeme-save',dict(headword='legacy',body=dict(usages=[dict(id='u',senses=[dict(id='s',short_gloss='pron.3',gloss_addition='SG.DAT')])])) )
            sources=[self.source(kind,[('legacy','written')]) for kind in ('corpus','independent')]
            for source in sources:
                self.api('segmentation-link',dict(**self.args(source),word=0,key='@word',link_revision=0,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id='u',sense_id='s'))
            self.assertEqual(self.gloss(sources[0]),'pron.3.SG.DAT')
            independent=self.detail(sources[1]);binding=independent['body']['words'][0]['gloss_sources'][0]
            self.api('gloss-source-save',dict(**self.args(sources[1]),binding_id=binding['id'],binding_revision=binding['revision'],gloss_revision=independent['body']['gloss_revision'],mode='override',value='keep_this'))
        tables=('entries','dictionary_examples','lexemes','lexical_links')
        def snapshot(db):return {table:[dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY id')] for table in tables}
        with server.connect(audit=False) as db:
            before=snapshot(db);db.execute('DELETE FROM gloss_migrations WHERE id=?',(gloss_inheritance.NUMBER_JOIN,))
        server.init()
        self.assertEqual(self.gloss(sources[0]),'pron.3SG.DAT');self.assertEqual(self.gloss(sources[1]),'keep_this')
        with server.connect(audit=False) as db:
            self.assertEqual(snapshot(db),before)
            values=[tuple(r) for r in db.execute('SELECT id,gloss,revision FROM gloss_meanings ORDER BY id')]
            version=db.execute('SELECT version FROM analysis_state').fetchone()[0]
            gloss_inheritance.refresh_number_join(db)
            self.assertEqual(db.execute('SELECT version FROM analysis_state').fetchone()[0],version)
        server.init()
        with server.connect(audit=False) as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT id,gloss,revision FROM gloss_meanings ORDER BY id')],values)
