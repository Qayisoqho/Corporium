import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import server
import test_sentence_dictionary as sd


class MorphemePickerSearchTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','api','source','detail','args'):
        locals()[name]=getattr(sd.SentenceDictionaryTests,name)

    def search(self,q,scope='entry',**params):
        return self.api('morphemes?'+urlencode(dict(q=q,search=json.dumps(dict(scope=scope)),**params)))

    def morpheme(self,form,**body):
        return self.api('morpheme-save',dict(form=form,body=body))

    def link(self,m,kind):
        src=self.source(kind,[(m['form'],m['body']['gloss'])])
        self.api('segmentation-link',dict(**self.args(src),word=0,key='@word',link_revision=0,
            lexeme_id=m['id'],lexeme_revision=m['revision'],usage_id='@morpheme',sense_id='@main'))
        return src

    def test_own_writing_matches_but_associated_example_translation_does_not(self):
        writing=self.api('writing-save',dict(name='本字',font='Junicode'))['id']
        noise=self.morpheme('neg',gloss='NEG',entry_type='affix',affix_position='infix')
        target=self.morpheme('fuo',gloss='speech',writings=[dict(type_id=writing,text='话')])
        for kind in ('corpus','independent'):
            src=self.link(noise,kind)
            d=self.detail(src)
            # Keep the association while giving its sentence an unrelated word.
            body=d['body'];body.update(translation='说话的例句',notes=body.get('notes',''))
            self.api('example-save' if kind=='independent' else 'save',{**({'body':body} if kind=='independent' else body),'id':src['id'],'revision':d['revision']})
        self.assertEqual({r['id'] for r in self.search('话','all')['items']},{noise['id'],target['id']})
        self.assertEqual([r['id'] for r in self.search('话')['items']],[target['id']])

    def test_inline_examples_and_media_are_excluded_from_picker(self):
        m=self.morpheme('noise',gloss='NEG',examples=[dict(translation='例句专用话')],media=[dict(caption='媒体专用声')])
        for query in ('例句专用话','媒体专用声'):
            self.assertEqual(self.search(query,'all')['total'],1)
            self.assertEqual(self.search(query)['total'],0)
        self.assertEqual(self.search('NEG')['items'][0]['id'],m['id'])

    def test_own_gloss_reading_variant_definition_and_writing_remain_searchable(self):
        writing=self.api('writing-save',dict(name='本字',font='Junicode'))['id']
        m=self.morpheme('base',gloss='SPEECH',readings=['école'],variants=[dict(form='alternate',pronunciation='reading')],
            writings=[dict(type_id=writing,text='话')],senses=[dict(id='sense',gloss='utterance',definition='spoken language')])
        for query in ('base','speech','e\u0301COLE','alternate','reading','话','utterance','spoken language'):
            self.assertEqual([r['id'] for r in self.search(query)['items']],[m['id']],query)
        other=self.api('save-language',dict(name='Other',metadata={}))['id']
        self.assertEqual(self.search('话',language=other)['total'],0)

    def test_picker_filter_is_applied_before_pagination(self):
        for n in range(4):self.morpheme('a'+str(n),gloss='NEG',examples=[dict(translation='话')])
        expected=[self.morpheme(f'z{n:02}',gloss='话')['id'] for n in range(12)]
        for page in (1,2):
            result=self.search('话',page=page,page_size=10)
            self.assertEqual((result['total'],result['pages'],result['page']),(12,2,page))
            self.assertEqual([r['id'] for r in result['items']],expected[(page-1)*10:page*10])

    def test_entry_scope_does_not_read_sentence_or_annotation_bodies(self):
        self.morpheme('base',gloss='ROOT')
        with patch('dictionary_search.example_rows',side_effect=AssertionError('picker read evidence')):
            self.assertEqual(self.search('ROOT')['total'],1)
        with server.connect(audit=False) as db:
            import morpheme_registry
            statements=[];db.set_trace_callback(statements.append)
            morpheme_registry.listing(db,'ordos','ROOT',search={'scope':'entry'})
        self.assertFalse(any('FROM dictionary_examples' in s or 'FROM annotation_cells' in s for s in statements))


if __name__=='__main__':unittest.main()
