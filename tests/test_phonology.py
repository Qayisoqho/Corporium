import copy
import unittest
import phonology
import test_morpheme_registry

def inventory():
    return dict(initials=[dict(id='m',label='m',matches=['m']),dict(id='zero',label='零声母',matches=[''])],finals=[dict(id='a',label='a',matches=['a'])],tones=[dict(id='55',label='阴平',matches=['55','⁵⁵','˥']),dict(id='21',label='阳平',matches=['21'])])

class PhonologyTests(unittest.TestCase):
    for helper in ('setUp','tearDown','call','seed','entries','undo','fixture','link','assign'):
        locals()[helper]=getattr(test_morpheme_registry.MorphemeRegistryTests,helper)

    def settings(self,values=None):
        token=self.call('/api/homophone-phonology?language=ordos')[1]['token']
        code,data=self.call('/api/homophone-phonology-save',dict(action='settings',token=token,**(values or inventory())))
        self.assertEqual(code,200,data);return data

    def confirm(self,reading,**choice):
        token=self.call('/api/homophone-phonology?language=ordos')[1]['token']
        return self.call('/api/homophone-phonology-save',dict(action='classify',token=token,reading=reading,initials='m',finals='a',tones='55',**choice))

    def test_matching_ambiguity_and_original_preservation(self):
        config={**inventory(),'assignments':{}}
        self.assertEqual(phonology.classify('ma⁵⁵',config)['state'],'candidate')
        self.assertEqual(phonology.classify('a˥',config)['choice']['initials'],'zero')
        self.assertEqual(phonology.classify('ma55ma55',config)['state'],'unmatched')
        self.assertEqual(phonology.classify('ma',config)['state'],'unmatched')
        config['initials'].append(dict(id='other',label='another',matches=['m']))
        self.assertEqual(phonology.classify('ma55',config)['state'],'ambiguous')

    def test_confirmation_staleness_reorder_and_undo(self):
        self.settings();self.assertEqual(self.confirm('ma55')[0],200)
        data=self.call('/api/homophone-phonology?language=ordos')[1]
        self.assertEqual(phonology.classify('ma55',data)['state'],'confirmed')
        values=inventory();values['tones'].reverse();data=self.settings(values)
        self.assertEqual(phonology.classify('ma55',data)['state'],'confirmed')
        values['finals'][0]['matches']=['ɑ'];data=self.settings(values)
        self.assertEqual(phonology.classify('ma55',data)['state'],'stale')
        self.assertEqual(self.undo()[0],200)
        data=self.call('/api/homophone-phonology?language=ordos')[1]
        self.assertEqual(phonology.classify('ma55',data)['state'],'confirmed')
        code,_=self.call('/api/homophone-phonology-save',dict(action='classify',token=data['token'],reading='ma55',reset=True))
        self.assertEqual(code,200)
        self.assertEqual(phonology.classify('ma55',self.call('/api/homophone-phonology?language=ordos')[1])['state'],'candidate')

    def test_language_isolation_tokens_and_validation(self):
        data=self.settings();self.assertEqual(self.confirm('ma55')[0],200)
        self.assertEqual(self.call('/api/homophone-phonology-save',dict(action='settings',token=data['token'],**inventory()))[0],400)
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/homophone-phonology?language='+other)[1]['initials'],[])
        self.assertEqual(self.call('/api/homophone-phonology?language=all')[0],400)
        bad=inventory();bad['finals'][0]['matches']=['']
        with self.assertRaises(ValueError):phonology.inventory(bad)
        data=self.call('/api/homophone-phonology?language=ordos')[1]
        self.assertEqual(self.call('/api/homophone-phonology-save',dict(action='classify',token=data['token'],reading='ma55',initials='nonexistent',finals='a',tones='55'))[0],400)

    def test_table_order_pending_and_source_words(self):
        _,x=self.fixture()
        m=self.call('/api/morpheme-save',dict(form='ma',body=dict(readings=['ma55','a21','unknown'],gloss='test')))[1]
        self.assign(x,create=None,morpheme_id=m['id'],morpheme_revision=m['revision'])
        self.settings();self.confirm('ma55')
        data=self.call('/api/homophones?language=ordos&view=phonology')[1]
        self.assertEqual(data['blocks'][0]['final']['id'],'a')
        self.assertEqual(data['blocks'][0]['rows'][0]['cells'][0]['tone']['id'],'55')
        self.assertEqual(data['pending_total'],2)
        empty=self.call('/api/homophones?language=ordos&view=phonology&empty=true')[1]
        self.assertEqual(len(empty['blocks'][0]['rows']),2)
        self.assertEqual(len(empty['blocks'][0]['rows'][0]['cells']),2)
        words=self.call('/api/homophone-words?language=ordos&identity='+m['id'])[1]['words']
        self.assertEqual(words[0]['id'],x['id'])
        page=self.call('/api/homophone-words?language=ordos&identity='+m['id']+'&page=999')[1]
        self.assertEqual((page['page'],page['pages'],page['total']),(1,1,1))
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/homophone-words?language='+other+'&identity='+m['id'])[0],400)

    def test_inventory_and_confirmations_exchange(self):
        self.settings();self.confirm('ma55')
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',dict(name='Copy',metadata={}))[1]['id']
        code,result=self.call('/api/import-language',dict(_language=other,bundle=bundle))
        self.assertEqual(code,200,result)
        data=self.call('/api/homophone-phonology?language='+other)[1]
        self.assertEqual(data['initials'],inventory()['initials'])
        self.assertEqual(phonology.classify('ma55',data)['state'],'confirmed')

    def test_matrix_pagination_keeps_final_groups_together(self):
        cfg={**inventory(),'assignments':{}};cfg['finals']=[dict(id=str(i),label=str(i),matches=[str(i)]) for i in range(12)]
        for i in range(12):
            choice=dict(initials='m',finals=str(i),tones='55');cfg['assignments'][f'm{i}55']={**choice,'signature':phonology.signature(cfg,choice)}
        groups=[dict(reading=f'm{i}55',items=[]) for i in range(12)]
        data=phonology.arrange(groups,cfg,dict(page='2'))
        self.assertEqual([b['final']['id'] for b in data['blocks']],['10','11'])

    def test_final_page_sizes_all_and_page_bounds_keep_groups_complete(self):
        cfg={**inventory(),'assignments':{}};cfg['finals']=[dict(id=str(i),label=str(i),matches=[str(i)]) for i in range(57)]
        groups=[]
        for i in range(57):
            choice=dict(initials='m',finals=str(i),tones='55');reading=f'm{i}55'
            cfg['assignments'][reading]={**choice,'signature':phonology.signature(cfg,choice)}
            groups.append(dict(reading=reading,items=[dict(identity=f'{i}-a'),dict(identity=f'{i}-b')]))
        for size,expected,pages in [('10',range(10,20),6),('20',range(20,40),3),('50',range(50,57),2),('all',range(57),1)]:
            with self.subTest(size=size):
                data=phonology.arrange(copy.deepcopy(groups),cfg,dict(page='2',page_size=size))
                self.assertEqual([b['final']['id'] for b in data['blocks']],[str(i) for i in expected])
                self.assertEqual((data['pages'],data['final_total']),(pages,57))
                self.assertTrue(all(len(g['items'])==2 for b in data['blocks'] for r in b['rows'] for c in r['cells'] for g in c['groups']))
        last=phonology.arrange(copy.deepcopy(groups),cfg,dict(page='999',page_size='20'))
        self.assertEqual((last['page'],len(last['blocks'])),(3,17))
        for size in ('0','-1','15','100','20.5','bad',None):
            with self.subTest(invalid=size),self.assertRaises(ValueError):phonology.arrange([],cfg,dict(page_size=size))

    def test_final_page_sizes_include_visible_empty_groups_and_handle_empty_results(self):
        cfg={**inventory(),'assignments':{}};cfg['finals']=[dict(id=str(i),label=str(i),matches=[str(i)]) for i in range(23)]
        empty=phonology.arrange([],cfg,dict(page_size='all'))
        self.assertEqual((empty['page'],empty['pages'],empty['blocks'],empty['final_total']),(1,1,[],0))
        shown=phonology.arrange([],cfg,dict(page_size='20',page='2',empty='true'))
        self.assertEqual((shown['page'],shown['pages'],len(shown['blocks']),shown['final_total']),(2,2,3,23))
        all_rows=phonology.arrange([],cfg,dict(page_size='all',empty='true'))
        self.assertEqual((all_rows['page_size'],len(all_rows['blocks'])),('all',23))

    def test_second_homographic_morpheme_stays_in_the_same_paginated_cell(self):
        values=inventory();values['finals']=[dict(id=str(i),label=str(i),matches=[str(i)]) for i in range(12)]
        self.settings(values)
        saved=[]
        for i in range(12):
            code,m=self.call('/api/morpheme-save',dict(form=f'm{i}55',body=dict(readings=[f'm{i}55'],gloss=f'义项{i}')))
            self.assertEqual(code,200,m);saved.append(m)
            token=self.call('/api/homophone-phonology?language=ordos')[1]['token']
            code,result=self.call('/api/homophone-phonology-save',dict(action='classify',token=token,reading=f'm{i}55',initials='m',finals=str(i),tones='55'))
            self.assertEqual(code,200,result)
        def cell(**filters):
            from urllib.parse import urlencode
            code,data=self.call('/api/homophones?'+urlencode(dict(language='ordos',view='phonology',page=2,**filters)))
            self.assertEqual(code,200,data)
            group=next(g for b in data['blocks'] for r in b['rows'] for c in r['cells'] for g in c['groups'] if g['reading']=='m1155')
            return data,group
        before,group=cell();self.assertEqual((before['page'],before['pages'],len(group['items'])),(2,2,1))
        code,second=self.call('/api/morpheme-save',dict(form='m1155',body=dict(readings=['m1155'],gloss='另一个语素')))
        self.assertEqual(code,200,second)
        after,group=cell();self.assertEqual((after['page'],after['pages']),(2,2))
        self.assertEqual({r['identity'] for r in group['items']},{saved[-1]['id'],second['id']})
        self.assertEqual({r['number'] for r in group['items']},{1,2})
        self.assertEqual(group['classification']['state'],'confirmed')
        filtered,group=cell(only_multiple='true');self.assertEqual((filtered['page'],len(group['items'])),(1,2))
        for size in ('20','50','all'):
            data,group=cell(page_size=size);self.assertEqual((data['page'],data['pages'],len(data['blocks']),len(group['items'])),(1,1,12,2))
        self.assertEqual(self.call('/api/homophones?language=ordos&view=phonology&page_size=15')[0],400)

if __name__=='__main__':unittest.main()
