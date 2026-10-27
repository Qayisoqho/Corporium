"""Replacement uses live annotation cells without altering sentence identities."""
import copy
import json
import unittest
import server
import test_sentence_dictionary as sd


class LayerReplaceTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args','entry','undo'):
        locals()[name]=getattr(sd.SentenceDictionaryTests,name)

    def layer(self,name,anchor='word',**more):
        return self.api('layer-save',dict(name=name,anchor=anchor,font='Junicode',**more))['id']

    def data(self,src):return self.api('annotations?kind='+src['kind']+'&id='+src['id'])

    def contents(self,value):
        # Undo intentionally advances optimistic revision stamps.
        if isinstance(value,dict):return {k:self.contents(v) for k,v in value.items() if k!='revision'}
        if isinstance(value,list):return [self.contents(v) for v in value]
        return value

    def annotate(self,src,values):
        d=self.data(src)
        cells=[dict(layer_id=layer,unit_id=d['words'][word]['id'] if word is not None else '@sentence',value=value) for layer,word,value in values]
        self.api('annotation-save',dict(**src,revision=d['revision'],before=d['cells'],layers=d['layers'],cells=cells))

    def preview(self,kind,**extra):
        b={**dict(owner_kind=kind,field='layer',find='old',replacement='NEW'),**extra}
        return b,self.api('text-replace-preview',b)

    def apply(self,b,p,**extra):
        return self.api('text-replace-apply',{**b,'token':p['token'],'keys':[c['key'] for c in p['changes']],**extra})

    def test_all_anchors_hidden_layers_and_both_sources_preserve_links_body_and_undo(self):
        layers=[self.layer('Word'),self.layer('IPA extra','ipa'),self.layer('Translation extra','translation',visible=False,searchable=False)]
        x=self.entry('root','G');u=x['body']['usages'][0]
        for kind in ('corpus','independent'):
            with self.subTest(kind=kind):
                src=self.source(kind,[('root','G'),('tail','T')])
                self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',lexeme_id=x['id'],lexeme_revision=x['revision'],usage_id=u['id'],sense_id=u['senses'][0]['id']))
                self.annotate(src,[(layers[0],0,'𐐀 old old'),(layers[0],1,'keep'),(layers[1],None,'old'),(layers[2],None,'old')])
                before=self.data(src);history=self.api('undo-state')['generation']
                b,p=self.preview(kind);self.assertEqual(len(p['changes']),4);self.assertEqual(len({c['key'] for c in p['changes']}),4)
                self.assertFalse(p['conflicts'] or p['blocked']);self.assertEqual(self.api('undo-state')['generation'],history)
                r=self.apply(b,p);self.assertEqual((r['sentences'],r['replacements']),(1,4))
                after=self.data(src);self.assertEqual(after['body'],before['body']);self.assertEqual(after['revision'],before['revision']);self.assertEqual(after['words'],before['words'])
                self.assertEqual([c['id'] for c in after['cells']],[c['id'] for c in before['cells']])
                self.assertEqual([c['value'] for c in after['cells']],['𐐀 NEW NEW','keep','NEW','NEW'])
                self.undo();self.assertEqual(self.contents(self.data(src)),self.contents(before))
                self.undo(True);self.assertEqual(self.contents(self.data(src)),self.contents(after))

    def test_partial_replacement_tracks_each_cell_and_never_replaces_inserted_matches(self):
        a=self.layer('A','ipa');b=self.layer('B','translation')
        for kind in ('corpus','independent'):
            src=self.source(kind,[('root','G')]);self.annotate(src,[(a,None,'old old'),(b,None,'old old')])
            args,p=self.preview(kind,replacement='oldold')
            first=p['changes'][0];r=self.apply(args,p,keys=[first['key']],pending_keys=[c['key'] for c in p['changes']])
            self.assertEqual(len(r['remaining_keys']),3)
            fresh=self.api('text-replace-preview',args);remaining=[c for c in fresh['changes'] if c['key'] in r['remaining_keys']]
            self.assertEqual(len(remaining),3);self.apply(args,fresh,keys=[c['key'] for c in remaining],pending_keys=[c['key'] for c in remaining])
            self.assertEqual({c['value'] for c in self.data(src)['cells']},{'oldold oldold'})

    def test_layer_filter_scope_arbitrary_text_empty_and_orphans(self):
        a=self.layer('A');b=self.layer('B');src=self.source('corpus',[('root','G')]);other=self.source('corpus',[('other','G')])
        self.annotate(src,[(a,0,'old'),(b,0,'old')]);self.annotate(other,[(a,0,'old')])
        with server.connect(audit=False) as db:
            tid=db.execute('SELECT text_id FROM entries WHERE id=?',(src['id'],)).fetchone()[0]
            db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,?)',('orphan','corpus',src['id'],'lost-word',a,'old',1))
        args,p=self.preview('corpus',layer_id=a,text_id=tid,replacement='[𐐀\n')
        self.assertEqual(len(p['changes']),1);self.assertFalse(p['blocked']);self.apply(args,p)
        self.assertEqual({c['unit_id']:c['value'] for c in self.data(src)['cells']}['lost-word'],'old')
        self.assertEqual(self.data(other)['cells'][0]['value'],'old')
        args,p=self.preview('corpus',layer_id=b,text_id=tid,replacement='');self.apply(args,p)
        self.assertFalse(any(c['layer_id']==b for c in self.data(src)['cells']))
        self.undo();self.assertTrue(any(c['layer_id']==b for c in self.data(src)['cells']))

    def test_language_and_concurrent_cell_or_definition_changes_invalidate_preview(self):
        layer=self.layer('A');src=self.source('independent',[('root','G')]);self.annotate(src,[(layer,0,'old')])
        b,p=self.preview('independent');self.annotate(src,[(layer,0,'old changed')])
        self.assertEqual(self.call('/api/text-replace-apply',dict(**b,token=p['token'],keys=[c['key'] for c in p['changes']]))[0],400)
        b,p=self.preview('independent');definition=self.data(src)['layers'][0]
        self.api('layer-save',{**definition,'name':'Renamed'})
        self.assertEqual(self.call('/api/text-replace-apply',dict(**b,token=p['token'],keys=[c['key'] for c in p['changes']]))[0],400)
        foreign=self.api('save-language',dict(name='Other',metadata={}))['id']
        self.assertEqual(self.call('/api/text-replace-preview',dict(**b,layer_id=layer,_language=foreign))[0],400)
        self.assertEqual(self.api('text-replace-preview',dict(**b,_language=foreign))['changes'],[])
        self.assertEqual(self.call('/api/text-replace-preview',dict(**b,layer_id=[]))[0],400)


if __name__=='__main__':unittest.main()
