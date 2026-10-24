import unittest
import json
import server
import test_lexicon

class DictionaryReplaceTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    word=test_lexicon.LexiconTests.word
    link=test_lexicon.LexiconTests.link
    undo=test_lexicon.LexiconTests.undo

    def preview(self,**kw):
        args={**dict(field='notes',find='old',replacement='new',scope='language'),**kw}
        code,p=self.call('/api/dictionary-replace-preview',args);self.assertEqual(code,200,p)
        return args,p

    def apply(self,args,p,**extra):
        return self.call('/api/dictionary-replace-apply',{**args,'token':p['token'],'keys':[c['key'] for c in p['changes']],**extra})

    def simple(self,headword='first',notes='old old'):
        code,x=self.call('/api/lexeme-save',dict(headword=headword,body={'notes':notes}));self.assertEqual(code,200,x);return x

    def test_preview_no_write_apply_and_atomic_undo(self):
        x=self.simple();y=self.simple('second');state=self.call('/api/undo-state')[1]
        args,p=self.preview();self.assertEqual(len(p['changes']),4)
        self.assertEqual(self.call('/api/undo-state')[1]['generation'],state['generation'])
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['revision'],x['revision'])
        code,r=self.apply(args,p);self.assertEqual(code,200,r);self.assertEqual(r['lexemes'],2)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['notes'],'new new')
        self.assertEqual(self.undo()[0],200)
        for row in (x,y):self.assertEqual(self.call('/api/lexeme?id='+row['id'])[1]['body']['notes'],'old old')

    def test_stale_preview_and_wrong_language_do_not_write(self):
        x=self.simple();args,p=self.preview();x['body']['notes']='old changed';self.call('/api/lexeme-save',x)
        self.assertEqual(self.apply(args,p)[0],400)
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/dictionary-replace-preview',{**args,'scope':'current','lexeme_id':x['id'],'_language':other})[0],400)

    def test_headword_collision_requires_confirmation_and_preserves_links(self):
        e=self.seed();x=self.word();self.link(e['words'][0]['unit_id'],x);peer=self.simple('house')
        args=dict(field='headword',find='home',replacement='house',scope='language')
        code,p=self.call('/api/dictionary-replace-preview',args);self.assertEqual(code,200,p);self.assertFalse(p['blocked']);self.assertTrue(p['conflicts'])
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['headword'],'home')
        generation=self.call('/api/undo-state')[1]['generation']
        code,r=self.apply(args,p);self.assertEqual(code,200,r);self.assertTrue(r['needs_confirmation'])
        self.assertEqual(self.call('/api/undo-state')[1]['generation'],generation)
        self.assertEqual(self.call('/api/lexeme?id='+peer['id'])[1]['revision'],peer['revision'])
        code,r=self.apply(args,p,confirm_conflicts=True);self.assertEqual(code,200,r)
        after=self.call('/api/lexeme?id='+x['id'])[1];self.assertEqual(after['headword'],'house')
        self.assertNotEqual(after['body']['homonym_number'],self.call('/api/lexeme?id='+peer['id'])[1]['body']['homonym_number'])
        self.assertEqual(self.entries()[0]['words'][0]['form'],'house-n')
        with server.connect() as db:self.assertIsNone(db.execute('SELECT reason FROM lexical_reviews').fetchone())
        self.assertEqual(self.undo()[0],200)
        with server.connect() as db:self.assertIsNone(db.execute('SELECT reason FROM lexical_reviews').fetchone())

    def test_invalid_empty_headword_blocks_every_write(self):
        x=self.simple();args=dict(field='headword',find='first',replacement='',scope='language')
        p=self.call('/api/dictionary-replace-preview',args)[1];self.assertTrue(p['blocked'])
        self.assertEqual(self.apply(args,p,confirm_conflicts=True)[0],400)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['headword'],'first')

    def test_one_by_one_unicode_does_not_replace_new_matches(self):
        x=self.simple(notes='𐐀 old old');args,p=self.preview();args['replacement']='oldold';p=self.call('/api/dictionary-replace-preview',args)[1]
        code,r=self.apply(args,p,keys=[p['changes'][0]['key']]);self.assertEqual(code,200,r)
        fresh=self.call('/api/dictionary-replace-preview',args)[1];remaining=[c for c in fresh['changes'] if c['key'] in r['remaining_keys']]
        self.assertEqual(len(remaining),1)
        code,r=self.apply(args,fresh,keys=[remaining[0]['key']],pending_keys=[remaining[0]['key']]);self.assertEqual(code,200,r)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['notes'],'𐐀 oldold oldold')

    def test_page_sizes_and_search_scope_cover_all_pages(self):
        for i in range(12):self.simple('item'+str(i))
        first=self.call('/api/lexemes?page_size=10')[1];second=self.call('/api/lexemes?page_size=10&page=2')[1]
        self.assertEqual((len(first['items']),len(second['items']),first['pages']),(10,2,2))
        self.assertEqual(self.call('/api/lexemes?page_size=999')[0],400)
        args,p=self.preview(scope='search',query='item1');self.assertEqual(p['records'],3)
        self.assertEqual(self.apply(args,p)[0],200)
        self.assertEqual(self.call('/api/lexemes?q=new')[1]['total'],3)

    def test_supported_fields_preserve_ids_and_class_names(self):
        x=self.word();b=x['body'];b['notes']='old';b['variants'][0]['form']='old'
        b['orthographies']=[dict(label='测试书写',text='old',font='Junicode')]
        b['usages'][0]['senses'][0].update(short_gloss='old',definition='old')
        b['tags'][0]['value']='old'
        code,x=self.call('/api/lexeme-save',x);self.assertEqual(code,200,x)
        before=x['body'];uids=[u['id'] for u in before['usages']]
        for field in ('variant','writing','short_gloss','definition','notes','tag_value'):
            args=dict(field=field,find='old',replacement='new',scope='current',lexeme_id=x['id'])
            code,p=self.call('/api/dictionary-replace-preview',args);self.assertEqual(code,200,p);self.assertFalse(p['blocked']);self.assertTrue(p['changes'])
            code,r=self.apply(args,p,confirm_conflicts=True);self.assertEqual(code,200,r)
        after=self.call('/api/lexeme?id='+x['id'])[1]['body']
        self.assertEqual([u['id'] for u in after['usages']],uids)
        self.assertEqual(after['variants'][0]['id'],before['variants'][0]['id'])
        self.assertEqual(after['orthographies'][0]['id'],before['orthographies'][0]['id'])
        self.assertEqual(after['usages'][0]['pos'],before['usages'][0]['pos'])
        self.assertEqual(after['usages'][0]['senses'][0]['definition'],'new')

    def test_search_scope_remains_fixed_during_individual_replacement(self):
        x=self.simple(notes='old old')
        args,p=self.preview(scope='search',query='old old')
        args['scope_ids']=p['scope_ids']
        code,r=self.apply(args,p,keys=[p['changes'][0]['key']]);self.assertEqual(code,200,r)
        fresh=self.call('/api/dictionary-replace-preview',args)[1]
        self.assertEqual(fresh['records'],1);self.assertEqual(len(fresh['changes']),1)
        self.assertEqual(fresh['changes'][0]['key'],r['remaining_keys'][0])
        self.assertEqual(self.apply(args,fresh)[0],200)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['body']['notes'],'new new')

    def test_find_only_returns_unchanged_matches_and_cannot_apply(self):
        x=self.simple('old')
        args,p=self.preview(field='all',find_only=True,replacement='')
        self.assertEqual(len(p['changes']),3)
        self.assertTrue(p['find_only']);self.assertFalse(p['blocked'])
        self.assertTrue(all(c['before']==c['after'] for c in p['changes']))
        self.assertEqual(self.apply(args,p)[0],400)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['revision'],x['revision'])

    def test_pending_conditions_apply_to_every_scope(self):
        x=self.simple('old',notes='keep');self.simple('other',notes='skip')
        for scope in ('language','current','search'):
            args,p=self.preview(field='headword',find='old',replacement='new',scope=scope,lexeme_id=x['id'],query='old',search={'field':'headword','conditions':[{'field':'notes','op':'exact','value':'skip'}]})
            self.assertEqual(p['records'],0);self.assertFalse(p['changes'])
        args,p=self.preview(field='headword',find='old',replacement='new',scope='search',search={'field':'notes','conditions':[{'field':'headword','op':'prefix','value':'old'}]},query='keep')
        self.assertEqual([c['id'] for c in p['changes']],[x['id']])
        self.assertEqual(self.apply(args,p)[0],200)

    def morph(self,form='old',**body):
        code,x=self.call('/api/morpheme-save',{'form':form,'body':body})
        self.assertEqual(code,200,x);return x

    def test_morpheme_fields_filters_ids_and_atomic_undo_redo(self):
        wt=self.call('/api/writing-save',{'name':'汉字','font':'Junicode'})[1]
        x=self.morph(gloss='old',notes='keep old old',readings=['old'],writings=[{'type_id':wt['id'],'text':'old'}],senses=[{'id':'sense1','gloss':'old','definition':'old'}],variants=[{'id':'var1','form':'oldx','conditions':'old condition','tags':[{'type':'region','value':'old'}]}],merged_records=[{'form':'old','body':{'notes':'old archive'}}])
        self.morph('other',gloss='old',notes='skip')
        args,p=self.preview(kind='morpheme',field='all',scope='search',query='keep',search={'field':'notes','combine':'all','conditions':[{'field':'variants.conditions','op':'contains','value':'condition'}]})
        self.assertEqual(p['records'],1);self.assertFalse(p['blocked']);self.assertEqual(len(p['changes']),11)
        self.assertEqual(self.apply(args,p)[0],200)
        after=self.call('/api/morpheme?id='+x['id'])[1]
        self.assertEqual(after['form'],'new');self.assertEqual(after['body']['gloss'],'new')
        self.assertEqual(after['body']['variants'][0]['id'],'var1');self.assertEqual(after['body']['senses'][0]['id'],'sense1')
        self.assertEqual(after['body']['writings'][0]['type_id'],wt['id'])
        self.assertEqual(after['body']['merged_records'],x['body']['merged_records'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.call('/api/morpheme?id='+x['id'])[1]['body'],x['body'])
        state=self.call('/api/undo-state')[1]
        self.assertEqual(self.call('/api/redo',{'generation':state['generation']})[0],200)
        self.assertEqual(self.call('/api/morpheme?id='+x['id'])[1]['form'],'new')

    def test_morpheme_scope_stale_collision_and_fixed_remaining(self):
        x=self.morph(notes='old old');peer=self.morph('new')
        args,p=self.preview(kind='morpheme',field='form',scope='current',morpheme_id=x['id'])
        self.assertTrue(p['conflicts']);self.assertEqual(self.apply(args,p)[1]['needs_confirmation'],True)
        self.assertEqual(self.apply(args,p,confirm_conflicts=True)[0],200)
        self.assertNotEqual(self.call('/api/morpheme?id='+x['id'])[1]['number'],self.call('/api/morpheme?id='+peer['id'])[1]['number'])
        self.undo()
        args,p=self.preview(kind='morpheme',scope='search',query='old old')
        args['scope_ids']=p['scope_ids'];code,r=self.apply(args,p,keys=[p['changes'][0]['key']]);self.assertEqual(code,200,r)
        fresh=self.call('/api/dictionary-replace-preview',args)[1]
        self.assertEqual([c['key'] for c in fresh['changes']],r['remaining_keys'])
        self.assertEqual(self.apply(args,p)[0],400)
        self.assertEqual(self.apply(args,fresh)[0],200)
        other=self.call('/api/save-language',{'name':'Other','metadata':{}})[1]['id']
        self.assertEqual(self.call('/api/dictionary-replace-preview',{**args,'scope':'current','morpheme_id':x['id'],'_language':other})[0],400)

    def test_morpheme_invalid_forms_and_unknown_fields_never_write(self):
        x=self.morph(variants=[{'id':'a','form':'xa'},{'id':'b','form':'xb'}])
        for field,find,replacement in [('form','old',''),('variant','b','a')]:
            args,p=self.preview(kind='morpheme',field=field,find=find,replacement=replacement)
            self.assertTrue(p['blocked']);self.assertEqual(self.apply(args,p)[0],400)
        self.assertEqual(self.call('/api/dictionary-replace-preview',{'kind':'morpheme','field':'headword','find':'old'})[0],400)
        self.assertEqual(self.call('/api/morpheme?id='+x['id'])[1]['revision'],x['revision'])

    def test_morpheme_variant_media_survives_replace_and_undo(self):
        from test_object_media import ObjectMediaTests
        x=self.morph(variants=[{'id':'media-variant','form':'old'}])
        code,media=ObjectMediaTests.add(self,x,ObjectMediaTests.audio(self),{'target_id':'media-variant'},kind='morpheme')
        self.assertEqual(code,200,media)
        before=self.call('/api/object-media?kind=morpheme&id='+x['id'])[1]['items']
        args,p=self.preview(kind='morpheme',field='variant')
        self.assertEqual(self.apply(args,p)[0],200)
        self.assertEqual(self.call('/api/object-media?kind=morpheme&id='+x['id'])[1]['items'],before)
        self.assertEqual(self.call('/api/morpheme?id='+x['id'])[1]['body']['variants'][0]['form'],'new')
        self.undo()
        self.assertEqual(self.call('/api/morpheme?id='+x['id'])[1]['body']['variants'][0]['form'],'old')
        self.assertEqual(self.call('/api/object-media?kind=morpheme&id='+x['id'])[1]['items'],before)

    def test_find_only_keeps_nonreplaceable_search_hits(self):
        x=self.call('/api/lexeme-save',{'headword':'sample','body':{'usages':[{'pos':'名词'}],'variants':[{'form':'sam','conditions':'元音之后'}]}})[1]
        for query,field in [('名词','usages.pos'),('元音','variants.conditions')]:
            args,p=self.preview(field='all',find=query,query=query,find_only=True,scope='search',search={'field':field})
            self.assertEqual(p['records'],1);self.assertTrue(p['changes'])
            self.assertTrue(all(c.get('read_only') for c in p['changes']))
            self.assertEqual(self.apply(args,p)[0],400)
        self.assertEqual(self.call('/api/lexeme?id='+x['id'])[1]['revision'],x['revision'])
