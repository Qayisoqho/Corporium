"""Counts pages retain only requested hits and preserve immutable snapshots."""
import base64
import copy
import json
import unittest
import zlib
from unittest.mock import patch
import analysis_payload as payload
import analysis_workspace as analysis
import long_tasks


class StatisticsPayloadTests(unittest.TestCase):
    def setUp(self):
        with payload._statistics_lock:payload._statistics.clear();payload._statistics_bytes=0
        self.value=dict(hits=[dict(entry_id='e'+str(i),word_position=i,value='é',dimensions=dict(form=['na'])) for i in range(12)],
                        vocabulary=dict(forms=[dict(key='na',form='na',indices=[0,2,5],count=3)],morphemes=[]),statistics=dict(words=12,types=1,case=True),records=dict(e0=dict(body=dict(words=[dict(form='na',gloss='R')]))))
        self.encoded=analysis.pack(self.value)

    def test_metadata_is_equivalent_without_retaining_all_hit_objects(self):
        with patch.object(payload.HitPool,'apply',side_effect=AssertionError('metadata retained a hit')):
            result=payload.statistics_metadata(self.encoded)
        self.assertEqual(result,{k:self.value[k] for k in ('statistics','vocabulary')})

    def test_selected_hits_keep_order_duplicates_and_legacy_indexing(self):
        for indices in ([5,0,5,2],[],[-1,0],[True,False]):
            with self.subTest(indices=indices):
                expected=[{**self.value['hits'][i],'index':i} for i in indices]
                self.assertEqual(payload.selected_hits(self.encoded,indices),expected)
        with self.assertRaises(IndexError):payload.selected_hits(self.encoded,[99])
        with self.assertRaises(TypeError):payload.selected_hits(self.encoded,[1.0])

    def test_completed_metadata_is_owned_and_keyed_by_entire_payload_content(self):
        expected=payload.statistics_metadata(self.encoded)
        with patch.object(payload,'read',side_effect=AssertionError('unchanged metadata was decoded again')):
            result=payload.statistics_metadata(self.encoded);result['vocabulary']['forms'][0]['indices'].clear()
            self.assertEqual(payload.statistics_metadata(self.encoded),expected)
        changed=copy.deepcopy(self.value);changed['statistics']['words']=99
        self.assertEqual(payload.statistics_metadata(analysis.pack(changed))['statistics']['words'],99)

    def test_first_read_validates_nonselected_data_and_does_not_cache_failures(self):
        malformed=base64.b64encode(zlib.compress((analysis.encode(self.value)+' trailing').encode('utf8'))).decode()
        with self.assertRaises(ValueError):payload.statistics_metadata(malformed)
        self.assertFalse(payload._statistics)
        self.assertEqual(payload.statistics_metadata(self.encoded)['statistics']['words'],12)

    def test_budget_fallback_and_cancelled_cache_hit_keep_exact_results(self):
        with patch.object(payload,'STATISTICS_LIMIT',1):
            self.assertEqual(payload.statistics_metadata(self.encoded)['statistics']['words'],12);self.assertFalse(payload._statistics)
        expected=payload.statistics_metadata(self.encoded)
        with patch.object(long_tasks,'checkpoint',side_effect=long_tasks.Cancelled('cancelled')):
            with self.assertRaises(long_tasks.Cancelled):payload.statistics_metadata(self.encoded)
        self.assertEqual(payload.statistics_metadata(self.encoded),expected)

    def test_old_statistics_without_vocabulary_remain_readable(self):
        old=analysis.pack(dict(hits=[],statistics=dict(words=0,rows=[])))
        self.assertEqual(payload.statistics_metadata(old),dict(statistics=dict(words=0,rows=[])))

    def test_validated_selection_stops_before_unneeded_frozen_cards(self):
        value=copy.deepcopy(self.value);value['records']['e0']['marker']='unneeded-card';encoded=analysis.pack(value)
        payload.statistics_metadata(encoded);original=payload.Reader.value
        def bounded(reader,*a,**kw):
            value=original(reader,*a,**kw)
            if isinstance(value,dict) and value.get('marker')=='unneeded-card':raise AssertionError('unneeded frozen card decoded')
            return value
        with patch.object(payload.Reader,'value',bounded):
            self.assertEqual(payload.selected_hits(encoded,[5,0,5],validated=True),[{**self.value['hits'][i],'index':i} for i in (5,0,5)])
        malformed=base64.b64encode(zlib.compress((analysis.encode(value)+' trailing').encode())).decode()
        with self.assertRaises(ValueError):payload.selected_hits(malformed,[0])
