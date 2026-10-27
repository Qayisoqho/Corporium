"""All form markers, portable complex analyses and intake class registration."""
import copy
import unittest

import server
import segmentation
import word_analysis_memory as memory
from test_word_analysis_memory import WordAnalysisMemoryTests as _Fixtures


class AssistanceRefinementTests(unittest.TestCase):
    setUp=_Fixtures.setUp
    tearDown=_Fixtures.tearDown
    call=_Fixtures.call
    api=_Fixtures.api
    source=_Fixtures.source
    detail=_Fixtures.detail
    args=_Fixtures.args
    entry=_Fixtures.entry
    undo=_Fixtures.undo
    reuse=_Fixtures.reuse

    def link(self,src,key,x):
        u=x['body']['usages'][0]
        self.api('segmentation-link',dict(**self.args(src),word=0,key=key,lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id']))

    def test_all_parser_markers_and_protected_formatting(self):
        self.assertEqual(memory.MARKERS,segmentation.FORM_BOUNDARIES+'<>')
        for f in ['a-b','a=b','a+b','a~b',r'a\~b','a<b>']:
            self.assertEqual(memory.form_key(f),'ab')
        self.assertEqual(memory.form_key('a<um>b'),'aumb')
        self.assertNotEqual(memory.form_key('a#sub[2-4]'),memory.form_key('a#sub[24]'))
        self.assertNotEqual(memory.form_key('a?'),memory.form_key('a'))
        self.assertNotEqual(memory.form_key('aː'),memory.form_key('a'))
        self.assertNotEqual(memory.form_key('a.b'),memory.form_key('ab'))

    def test_reduplication_and_infix_both_sources_copy_actual_links_and_undo(self):
        for source_kind in ('corpus','independent'):
            for target_kind in ('corpus','independent'):
                for infix in (False,True):
                    with self.subTest(source=source_kind,target=target_kind,infix=infix):
                        tail=source_kind+target_kind+str(infix)
                        form='s<um>ab'+tail if infix else 'go~go'+tail
                        gloss='go<ACT>'+tail if infix else 'RED~go'+tail
                        src=self.source(source_kind,[(form,gloss)])
                        d=self.detail(src)
                        for n,m in enumerate(d['body']['words'][0]['morphemes']):
                            x=self.entry(m['form']+tail+str(n),m['gloss']);self.link(src,m['key'],x)
                        if not infix:
                            self.api('segmentation-save',dict(**self.args(src),action='redup-save',source=dict(word=0,key='r:0:host'),base=dict(word=0,key='r:1:host'),type='full'))
                        d=self.detail(src);plain=memory.form_key(form);dst=self.source(target_kind,[(plain,'')]);before=self.detail(dst)
                        if infix:
                            explicit=self.source(target_kind,[(form,'')]);p=self.api('sentence-gloss-preview',self.args(explicit))
                            self.assertTrue(p['analyses']);self.assertFalse(p['skipped'])
                        self.reuse(dst);after=self.detail(dst)
                        self.assertEqual(after['body']['words'][0]['form'],form)
                        self.assertEqual(after['body']['words'][0]['gloss'],d['body']['words'][0]['gloss'])
                        self.assertEqual(after['words'][0]['id'],before['words'][0]['id'])
                        if not infix:
                            self.assertNotEqual(after['body']['words'][0]['redup_id'],d['body']['words'][0]['redup_id'])
                            self.assertFalse(after['body']['reduplication_info']['relations'][0]['review'])
                        with server.connect(audit=False) as db:
                            import word_transfer
                            self.assertEqual(len(word_transfer.word_links(db,after,0)),2)
                        self.undo();self.assertEqual(self.detail(dst)['body']['words'][0]['gloss'],'')
                        self.undo(True);self.assertEqual(self.detail(dst)['body']['words'][0]['form'],form)

    def test_marker_opt_out_and_existing_explicit_split(self):
        a=self.entry('a','A');b=self.entry('b','B');src=self.source('corpus',[('a~b','A~B')])
        self.link(src,'r:0:host',a);self.link(src,'r:1:host',b)
        dst=self.source('independent',[('ab','')])
        self.assertTrue(self.api('sentence-gloss-preview',self.args(dst))['analyses'])
        self.assertFalse(self.api('sentence-gloss-preview',self.args(dst,boundaries='-=+<>'))['analyses'])
        dst=self.source('independent',[('a-b','')]);self.assertFalse(self.api('sentence-gloss-preview',self.args(dst))['analyses'])
        self.assertEqual(self.call('/api/sentence-gloss-preview',self.args(dst,boundaries='-<'))[0],400)

    def test_group_analysis_gets_fresh_group_id_and_link_keys(self):
        for kind in ('corpus','independent'):
            src=self.source(kind,[('we-go-la','PST-go-PST')])
            self.api('segmentation-save',dict(**self.args(src),action='save',word=0,members=['0:host','2:host'],type='circumfix',gloss='PST'))
            d=self.detail(src);g=d['body']['words'][0]['morph_groups'][0]
            for m in d['body']['words'][0]['morphemes']:
                self.link(src,m['key'],self.entry(m['form']+kind,m['gloss']))
            dst=self.source(kind,[('wegola','')]);self.reuse(dst);after=self.detail(dst)
            ng=after['body']['words'][0]['morph_groups'][0]
            self.assertNotEqual(ng['id'],g['id']);self.assertEqual(ng['members'],g['members'])
            self.assertFalse(after['body']['words'][0]['group_reviews'])

    def test_intake_existing_or_new_class_same_transaction_and_language_scope(self):
        self.api('class-save',dict(kind='pos',name='Noun'))
        other=self.api('save-language',dict(name='Other',metadata={}))['id']
        self.api('class-save',dict(kind='pos',name='Elsewhere',_language=other))
        for pos,expected in [('noun','Noun'),('New class','New class')]:
            src=self.source('independent',[(pos,'')]);b=self.args(src,word=0,key='@word',mode='new',target_kind='lexeme',form=pos,gloss='meaning',pos=pos)
            p=self.api('sentence-dictionary-preview',b);x=self.api('sentence-dictionary-apply',dict(**b,token=p['token']))
            self.assertEqual(self.api('lexeme?id='+x['id'])['body']['usages'][0]['pos'],expected)
            classes=self.api('classes?language=ordos');self.assertEqual(sum(c['kind']=='pos' and c['name']==expected for c in classes),1)
            self.assertFalse(any(c['name']=='Elsewhere' for c in classes))
            if pos=='New class':
                self.undo();self.assertFalse(any(c['name']==expected for c in self.api('classes?language=ordos')))

    def test_old_index_is_invalidated_once(self):
        src=self.source('corpus',[('s<um>ab','go<ACT>')])
        with server.connect(audit=False) as db:
            memory.refresh(db);db.execute('DELETE FROM word_analysis_version');db.execute("INSERT INTO word_analysis_version VALUES('old')")
            memory.initialize(db)
            self.assertTrue(db.execute('SELECT 1 FROM word_analysis_dirty WHERE owner_id=?',(src['id'],)).fetchone())
            memory.refresh(db);memory.initialize(db)
            self.assertFalse(db.execute('SELECT 1 FROM word_analysis_dirty').fetchone())

    def test_confirmed_infix_relation_and_component_association_are_preserved(self):
        for kind in ('corpus','independent'):
            src=self.source(kind,[('so<l>ma'+kind,'home<s.1>o.3sg>')])
            self.api('segmentation-save',dict(**self.args(src),action='confirm-infix',word=0))
            for n,m in enumerate(self.detail(src)['body']['words'][0]['morphemes']):
                self.link(src,m['key'],self.entry(m['form']+kind+str(n),m['gloss']))
            dst=self.source(kind,[('solma'+kind,'')]);self.reuse(dst)
            after=self.detail(dst)['body']['words'][0]
            self.assertFalse(after['infix_ambiguous']);self.assertEqual(after['infix_confirmation'],dict(form=after['form'],gloss=after['gloss']))
        x=self.entry('host-entry','house',word_structure=dict(analyses=[dict(id='a',title='Analysis',components=[dict(id='c',form='home',gloss='house')])]))
        ka=self.entry('ka','LOC');src=self.source('corpus',[('home-ka','house-LOC')]);u=x['body']['usages'][0]
        self.api('segmentation-link',dict(**self.args(src),word=0,key='0:host',lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id'],component_selection=dict(analysis_id='a',component_id='c')))
        self.link(src,'1:host',ka)
        dst=self.source('independent',[('homeka','')]);self.reuse(dst)
        target=next(t for t in self.detail(dst)['body']['targets'] if t['lexeme_id']==x['id'])
        self.assertEqual(target['component_ref']['component_id'],'c')

    def test_cross_word_base_is_explained_without_guessing_a_new_target(self):
        src=self.source('corpus',[('go~go','RED~go'),('outside','outside')])
        for n,m in enumerate(self.detail(src)['body']['words'][0]['morphemes']):self.link(src,m['key'],self.entry(m['form']+str(n),m['gloss']))
        self.api('segmentation-save',dict(**self.args(src),action='redup-save',source=dict(word=0,key='r:0:host'),base=dict(word=1,key='@word'),type='full'))
        dst=self.source('independent',[('gogo','')]);p=self.api('sentence-gloss-preview',self.args(dst))
        self.assertFalse(p['analyses']);self.assertTrue(any('基底' in r['reason'] for r in p['skipped']))
        self.assertFalse(self.detail(dst)['body'].get('reduplications'))

    def test_mixed_boundaries_keep_infix_and_reduplication_structure(self):
        form='g<um>o~go-s=na+la';gloss='RED<ACT>~go-PL=TOP+X'
        src=self.source('corpus',[(form,gloss)])
        for n,m in enumerate(self.detail(src)['body']['words'][0]['morphemes']):self.link(src,m['key'],self.entry(m['form']+str(n),m['gloss']))
        self.api('segmentation-save',dict(**self.args(src),action='redup-save',source=dict(word=0,key='r:0:host'),base=dict(word=0,key='r:1:host'),type='partial'))
        dst=self.source('independent',[(memory.form_key(form),'')]);self.reuse(dst);w=self.detail(dst)['body']
        self.assertEqual(w['words'][0]['form'],form);self.assertEqual(w['words'][0]['gloss'],gloss)
        self.assertEqual(len(w['words'][0]['morphemes']),6)
        self.assertFalse(w['reduplication_info']['relations'][0]['review'])


del _Fixtures
