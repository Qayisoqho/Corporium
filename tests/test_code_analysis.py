import unittest
from urllib.parse import urlencode
import test_code_switching
import test_lexicon


class CodeAnalysisTests(unittest.TestCase):
    for _name in ('setUp', 'tearDown', 'call', 'api', 'seed', 'detail', 'mark', 'undo'):
        locals()[_name] = getattr(test_code_switching.CodeSwitchingTests, _name)

    def run_query(self, value='', **scope):
        return self.api('analysis-run', dict(query=dict(scope=dict(source='all', **scope), conditions=[dict(field='form', value=value)])))

    def result(self, run, **kwargs):
        return self.api('analysis-result?' + urlencode(dict(id=run['id'], **kwargs)))

    def test_code_scope_and_hit_sentence_statistics_across_both_sources(self):
        self.seed()
        for kind in ('corpus', 'independent'): self.mark(kind=kind)
        run = self.run_query(code_mode='mixed', code_id=self.zh)
        self.assertEqual(run['query']['scope']['code_id'], self.zh)
        self.assertEqual(run['summary']['hits'], 2)
        self.assertEqual(self.run_query()['summary']['hits'],8)
        self.assertEqual(self.run_query('ni',code_mode='mixed')['summary']['hits'],2)
        self.assertEqual(run['summary']['scope_sentences'], 2)
        self.assertEqual(run['summary']['code_summary']['mixed'], 2)
        self.assertEqual(run['summary']['code_summary']['languages'], [dict(id=self.zh, name='汉语', sentences=2)])
        self.assertEqual(self.run_query('ni', code_id=self.zh)['summary']['code_summary']['mixed'], 2)
        self.assertEqual(self.run_query('absent', code_id=self.zh)['summary']['code_summary']['marked'], 0)
        self.assertEqual(self.run_query(code_id=self.ru)['summary']['scope_sentences'], 0)
        self.assertEqual(self.run_query(code_id='deleted-code')['summary']['hits'], 0)
        for source in ('corpus', 'independent'):
            query=dict(scope=dict(source=source,code_mode='mixed'),conditions=[dict(field='form',value='ni')])
            found=self.api('analysis-run',dict(query=query))
            self.assertEqual(found['summary']['sentences'],1)
        self.assertEqual(self.run_query(text_id=self.tid, code_id=self.zh)['summary']['sentences'], 1)
        self.assertEqual(self.run_query(sentence_language='nonexistent', code_id=self.zh)['summary']['hits'], 0)
        for item in self.result(run)['items']:
            self.assertEqual(item['word'],-1)
            words = item['record']['body']['words']
            self.assertFalse(words[1]['code_mark']['end'])
            self.assertTrue(words[2]['code_mark']['end'])

    def test_saved_scope_cache_snapshot_and_undo_follow_code_changes(self):
        self.seed(); self.mark()
        run=self.run_query(code_mode='mixed',code_id=self.zh)
        self.assertTrue(self.run_query(code_mode='mixed',code_id=self.zh)['cached'])
        for kind in ('scope', 'query'):
            saved=self.api('analysis-save',dict(kind=kind,name=kind,query=run['query']))
            entry=next(r for r in self.api('analysis-records')['saved'] if r['id']==saved['id'])
            scope=entry['body']['scope'] if kind=='scope' else entry['body']['query']['scope']
            self.assertEqual(scope['code_id'],self.zh);self.assertEqual(scope['code_mode'],'mixed')
        snap=self.api('analysis-save',dict(kind='snapshot',name='fixed',run_id=run['id']))
        self.mark(span=self.detail()['spans'][0]['id'], code='ru')
        self.assertTrue(self.result(run)['stale'])
        fresh=self.run_query(code_mode='mixed',code_id=self.zh)
        self.assertFalse(fresh['cached']);self.assertEqual(fresh['summary']['hits'],0)
        frozen=self.result(snap,snapshot='true')
        self.assertEqual(frozen['summary']['code_summary']['languages'][0]['name'],'汉语')
        self.assertEqual(frozen['items'][0]['record']['body']['words'][2]['code_mark']['short'],'ZH')
        self.undo()
        self.assertEqual(self.run_query(code_mode='mixed',code_id=self.zh)['summary']['sentences'],1)
        other=self.api('save-language',dict(name='Other',metadata={}))['id']
        isolated=self.api('analysis-run',dict(query=run['query'],_language=other))
        self.assertEqual(isolated['summary']['scope_sentences'],0)
        self.assertEqual(self.call('/api/analysis-run',dict(query=dict(scope=dict(code_mode='invalid'),conditions=[dict(field='form')])))[0],400)

    def test_marked_review_and_mixed_filters_have_distinct_meanings(self):
        self.seed();self.mark(indexes=(0,1,2,3))
        self.assertEqual(self.run_query(code_mode='marked')['summary']['sentences'],1)
        self.assertEqual(self.run_query(code_mode='mixed')['summary']['sentences'],0)
        self.assertEqual(self.run_query(code_mode='review')['summary']['sentences'],0)
        d=self.api('annotations?kind=corpus&id='+self.eid);d['body']['words'][1]['form']='changed'
        self.api('inline-save',dict(kind='corpus',id=self.eid,revision=d['revision'],before=d['cells'],layers=d['layers'],slot_ids=[w['id'] for w in d['words']],body=d['body'],cells=[]))
        run=self.run_query(code_mode='review',code_id=self.zh)
        self.assertEqual(run['summary']['sentences'],1)
        self.assertEqual(run['summary']['code_summary']['review'],1)

    def test_range_end_labels_skip_boundary_gaps_and_follow_current_identities(self):
        self.seed()
        d=self.api('annotations?kind=corpus&id='+self.eid)
        d['body']['words'].insert(2,dict(form='#',gloss='#'));ids=[w['id'] for w in d['words']];ids.insert(2,'new:boundary')
        self.api('inline-save',dict(kind='corpus',id=self.eid,revision=d['revision'],before=d['cells'],layers=d['layers'],slot_ids=ids,body=d['body'],cells=[]))
        self.mark(indexes=(1,3))
        marked={w['code_unit']:w['code_mark'] for w in self.api('entries')['items'][0]['words'] if w.get('code_mark')};words=self.detail()['words']
        self.assertFalse(marked[words[1]['id']]['end']);self.assertTrue(marked[words[3]['id']]['end'])
        d=self.api('annotations?kind=corpus&id='+self.eid);d['body']['words'][2]['form']='inserted'
        self.api('inline-save',dict(kind='corpus',id=self.eid,revision=d['revision'],before=d['cells'],layers=d['layers'],slot_ids=[w['id'] for w in d['words']],body=d['body'],cells=[]))
        marked={w['code_unit']:w['code_mark'] for w in self.api('entries')['items'][0]['words'] if w.get('code_mark')}
        self.assertTrue(marked[words[1]['id']]['end']);self.assertTrue(marked[words[3]['id']]['end'])


class ReferenceCountTests(unittest.TestCase):
    for _name in ('setUp','tearDown','call','seed','word','entries','link'):
        locals()[_name]=getattr(test_lexicon.LexiconTests,_name)

    def test_unfiltered_reference_count_is_distinct_from_zero_filtered_results(self):
        entry=self.seed();lexeme=self.word();path='/api/lexeme-examples?id='+lexeme['id']
        self.assertEqual(self.call(path)[1]['reference_total'],0)
        self.link(entry['words'][0]['unit_id'],lexeme)
        filtered=self.call(path+'&kind=morpheme')[1]
        self.assertEqual(filtered['total'],0);self.assertEqual(filtered['reference_total'],1)
        filtered=self.call(path+'&form_id='+lexeme['body']['variants'][0]['id'])[1]
        self.assertEqual(filtered['total'],0);self.assertEqual(filtered['reference_total'],1)


if __name__=='__main__':unittest.main()
