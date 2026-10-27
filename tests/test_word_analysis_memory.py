"""Whole-analysis reuse exercises real routes and undo in isolated projects."""
import json
import unittest

import server
import word_analysis_memory as memory
from test_sentence_dictionary import SentenceDictionaryTests as _Fixtures


class WordAnalysisMemoryTests(unittest.TestCase):
    setUp = _Fixtures.setUp
    tearDown = _Fixtures.tearDown
    call = _Fixtures.call
    api = _Fixtures.api
    source = _Fixtures.source
    detail = _Fixtures.detail
    args = _Fixtures.args
    entry = _Fixtures.entry
    complete = _Fixtures.complete
    undo = _Fixtures.undo

    def linked(self, kind='corpus', form='home-ka'):
        self.entry('home', '家'); self.entry('ka', 'LOC')
        src = self.source(kind, [(form, '')])
        self.complete(src)
        return src

    def reuse(self, dst, candidate=0):
        args = self.args(dst)
        p = self.api('sentence-gloss-preview', args)
        c = p['analyses'][0]['candidates'][candidate]
        self.assertFalse(p['analyses'][0]['automatic'])
        self.api('sentence-gloss-apply', dict(**args, token=p['token'],
            choices=[dict(word=0, key='@analysis', candidate_id=c['id'])]))
        return c

    def test_cross_source_reuse_identity_layers_links_undo_and_live_meanings(self):
        for source_kind in ('corpus', 'independent'):
            for dest_kind in ('corpus', 'independent'):
                with self.subTest(source=source_kind, dest=dest_kind):
                    # Use a distinct surface per pair to isolate candidate sets.
                    stem = 'home'+source_kind+dest_kind
                    self.entry(stem, '家'); self.entry('ka'+stem, 'LOC')
                    src = self.source(source_kind, [(stem+'-ka'+stem, '')]); self.complete(src)
                    dst = self.source(dest_kind, [(stem+'ka'+stem, ''), ('keep', '保留')])
                    before = self.detail(dst)
                    layer = self.api('layer-save', dict(name='Layer '+stem, font='Junicode'))['id']
                    before = self.detail(dst)
                    self.api('annotation-save', dict(**dst, revision=before['revision'], layers=before['layers'], before=[],
                        cells=[dict(unit_id=before['words'][0]['id'], layer_id=layer, value='local')]))
                    c = self.reuse(dst)
                    self.assertEqual(c['gloss'], '家-LOC')
                    after = self.detail(dst)
                    self.assertEqual(after['words'][0]['id'], before['words'][0]['id'])
                    self.assertEqual(after['body']['words'][1]['gloss'], '保留')
                    self.assertEqual(after['cells'][0]['value'], 'local')
                    self.assertEqual(after['body']['words'][0]['form'], stem+'-ka'+stem)
                    self.assertEqual(after['body']['words'][0]['gloss'], '家-LOC')
                    self.undo(); self.assertEqual(self.detail(dst)['body']['words'][0]['gloss'], '')
                    self.undo(True); self.assertEqual(self.detail(dst)['body']['words'][0]['gloss'], '家-LOC')
                    target = self.api('lexeme?id='+c['links'][0]['lexeme_id'])
                    target['body']['usages'][0]['senses'][0]['short_gloss'] = '新义'
                    self.api('lexeme-save', target)
                    self.assertIn('新义', self.detail(dst)['body']['words'][0]['gloss'])

    def test_boundaries_normalization_tones_and_explicit_structure(self):
        src = self.linked(form='home=ka')
        dst = self.source('independent', [('homeka', '')])
        self.assertTrue(self.api('sentence-gloss-preview', self.args(dst))['analyses'])
        self.assertFalse(self.api('sentence-gloss-preview', self.args(dst, boundaries='-+'))['analyses'])
        wrong = self.source('independent', [('home-ka', '')])
        self.assertFalse(self.api('sentence-gloss-preview', self.args(wrong))['analyses'])
        tone = self.source('independent', [('homeka²', '')])
        self.assertFalse(self.api('sentence-gloss-preview', self.args(tone))['analyses'])
        self.assertEqual(memory.form_key('ǰi-=+'), memory.form_key('ǰi'))
        self.assertEqual(memory.form_key('a~a'), memory.form_key('aa'))
        self.assertNotEqual(memory.form_key('a~a','-=+'), memory.form_key('aa','-=+'))

    def test_nonempty_and_existing_links_are_protected(self):
        self.linked()
        dst = self.source('independent', [('homeka', '本句')])
        self.assertFalse(self.api('sentence-gloss-preview', self.args(dst))['analyses'])
        dst = self.source('corpus', [('homeka', '')])
        x = self.entry('other', 'Other');u = x['body']['usages'][0]
        self.api('segmentation-link', dict(**self.args(dst), word=0, key='@word', lexeme_id=x['id'],
            lexeme_revision=x['revision'], usage_id=u['id'], sense_id=u['senses'][0]['id']))
        self.assertFalse(self.api('sentence-gloss-preview', self.args(dst))['analyses'])

    def test_distinct_segmentations_keep_candidates_and_selection_is_exclusive(self):
        self.linked(form='home-ka')
        src = self.source('independent', [('home=ka', '')]); self.complete(src)
        dst = self.source('corpus', [('homeka', '')]); args=self.args(dst)
        p = self.api('sentence-gloss-preview', args)
        self.assertEqual({c['form'] for c in p['analyses'][0]['candidates']}, {'home-ka', 'home=ka'})
        self.entry('homeka', 'whole')
        p = self.api('sentence-gloss-preview', args)
        choices = [dict(word=0,key='@analysis',candidate_id=p['analyses'][0]['candidates'][0]['id']),
                   dict(word=0,key='@word',candidate_id=p['rows'][0]['candidates'][0]['id'])]
        status, value=self.call('/api/sentence-gloss-apply',dict(**args,token=p['token'],choices=choices))
        self.assertEqual(status,400,value)
        self.assertEqual(self.detail(dst)['body']['words'][0]['form'],'homeka')

    def test_source_link_or_meaning_change_invalidates_plan(self):
        src=self.linked();dst=self.source('independent',[('homeka','')]);args=self.args(dst)
        p=self.api('sentence-gloss-preview',args);c=p['analyses'][0]['candidates'][0]
        x=self.api('lexeme?id='+c['links'][0]['lexeme_id']);x['body']['usages'][0]['senses'][0]['short_gloss']='Changed';self.api('lexeme-save',x)
        status,_=self.call('/api/sentence-gloss-apply',dict(**args,token=p['token'],choices=[dict(word=0,key='@analysis',candidate_id=c['id'])]))
        self.assertEqual(status,400)
        self.assertEqual(self.detail(dst)['body']['words'][0]['gloss'],'')
        p=self.api('sentence-gloss-preview',args)
        self.assertIn('Changed',p['analyses'][0]['candidates'][0]['gloss'])

    def test_local_overrides_and_partial_or_stale_associations_are_not_learned(self):
        src=self.linked();dst=self.source('independent',[('homeka','')])
        with server.connect(audit=False) as db:
            db.execute("UPDATE gloss_bindings SET mode='override',override_text='local',revision=revision+1 WHERE owner_id=?",(src['id'],))
        self.assertFalse(self.api('sentence-gloss-preview',self.args(dst))['analyses'])
        with server.connect(audit=False) as db:
            db.execute("UPDATE gloss_bindings SET mode='inherit',override_text=NULL WHERE owner_id=?",(src['id'],))
            link=db.execute('SELECT l.id FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE u.entry_id=? LIMIT 1',(src['id'],)).fetchone()[0]
            db.execute('INSERT INTO lexical_reviews VALUES(?,?)',(link,'review'))
        self.assertFalse(self.api('sentence-gloss-preview',self.args(dst))['analyses'])

    def test_index_incremental_updates_delete_restore_and_backup_exclusion(self):
        src=self.linked();dst=self.source('independent',[('homeka','')])
        self.assertTrue(self.api('sentence-gloss-preview',self.args(dst))['analyses'])
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM word_analysis_dirty').fetchone()[0],0)
            db.execute('UPDATE entries SET body=json_set(body,\'$.words[0].form\',\'other\') WHERE id=?',(src['id'],))
            self.assertEqual(db.execute('SELECT count(*) FROM word_analysis_dirty').fetchone()[0],1)
        self.assertFalse(self.api('sentence-gloss-preview',self.args(dst))['analyses'])
        backup=self.api('backup')
        self.assertNotIn('word_analysis_index',json.dumps(list(backup)))

    def test_variant_and_features_are_copied_with_meaning_identity(self):
        tag=self.api('grammar-save',dict(symbol='SG',explanation='single'))['id']
        self.entry('home','家',variants=[dict(form='hom')])
        self.entry('ka','LOC',features=[tag])
        src=self.source('independent',[('hom-ka','')]);self.complete(src)
        p=self.api('sentence-gloss-preview',self.args(self.source('corpus',[('homka','')])) )
        target=p['analyses'][0]['candidates'][0]['links'][1]
        self.api('segmentation-link',dict(**self.args(src),word=0,**{**target,'features':[tag]}))
        dst=self.source('corpus',[('homka','')]);c=self.reuse(dst)
        self.assertTrue(c['links'][0]['form_id'])
        self.assertEqual(c['links'][1]['features'],[tag])
        self.assertEqual(self.detail(dst)['body']['words'][0]['gloss'],'家-LOC.SG')

    def test_language_isolation_and_source_deletion_refresh(self):
        src=self.linked();dst=self.source('independent',[('homeka','')])
        self.assertTrue(self.api('sentence-gloss-preview',self.args(dst))['analyses'])
        lid=self.api('save-language',dict(name='Other',metadata={}))['id']
        with server.connect(audit=False) as db:
            db.execute('UPDATE texts SET language_id=? WHERE id=(SELECT text_id FROM entries WHERE id=?)',(lid,src['id']))
        self.assertFalse(self.api('sentence-gloss-preview',self.args(dst))['analyses'])
        with server.connect(audit=False) as db:
            db.execute('DELETE FROM entries WHERE id=?',(src['id'],))
        self.api('sentence-gloss-preview',self.args(dst))
        with server.connect(audit=False) as db:
            self.assertFalse(db.execute('SELECT 1 FROM word_analysis_index WHERE owner_id=?',(src['id'],)).fetchone())

    def test_same_gloss_different_meanings_remain_distinguishable(self):
        x=self.entry('home','house');x['body']['usages'][0]['senses'].append(dict(short_gloss='house',definition='other sense'))
        x=self.api('lexeme-save',x);self.entry('ka','LOC')
        senses=x['body']['usages'][0]['senses']
        for kind,sense in zip(('corpus','independent'),senses):
            src=self.source(kind,[('home-ka','')]);args=self.args(src);p=self.api('sentence-gloss-preview',args)
            choices=[]
            for row in p['rows']:
                c=next((c for c in row['candidates'] if c['sense_id']==sense['id']),row['candidates'][0])
                choices.append(dict(word=row['word'],key=row['key'],candidate_id=c['id']))
            self.api('sentence-gloss-apply',dict(**args,token=p['token'],choices=choices))
        dst=self.source('independent',[('homeka','')]);p=self.api('sentence-gloss-preview',self.args(dst));cs=p['analyses'][0]['candidates']
        self.assertEqual(len(cs),2)
        self.assertNotEqual(cs[0]['meanings'],cs[1]['meanings'])
        self.assertEqual({c['links'][0]['sense_id'] for c in cs},{s['id'] for s in senses})

    def test_failed_second_link_rolls_back_entire_analysis(self):
        from unittest.mock import patch
        import segmentation
        self.linked();dst=self.source('independent',[('homeka','')]);args=self.args(dst);p=self.api('sentence-gloss-preview',args);c=p['analyses'][0]['candidates'][0]
        real=segmentation.link;calls=[]
        def fail(db,b,lid):
            calls.append(b)
            if len(calls)==2:raise ValueError('simulated failure')
            return real(db,b,lid)
        before=self.detail(dst);undo=self.api('undo-state')
        with patch.object(segmentation,'link',fail):
            status,_=self.call('/api/sentence-gloss-apply',dict(**args,token=p['token'],choices=[dict(word=0,key='@analysis',candidate_id=c['id'])]))
        self.assertEqual(status,400)
        self.assertEqual(self.detail(dst),before)
        self.assertEqual(self.api('undo-state'),undo)

    def test_punctuation_is_preserved_and_different_punctuation_does_not_match(self):
        self.linked(form='home-ka!')
        wrong=self.source('independent',[('homeka?','')])
        self.assertFalse(self.api('sentence-gloss-preview',self.args(wrong))['analyses'])
        dst=self.source('independent',[('homeka!','')]);self.reuse(dst)
        self.assertEqual(self.detail(dst)['body']['words'][0]['form'],'home-ka!')

    def test_shared_morpheme_associations_are_reused(self):
        self.api('morpheme-save',dict(form='home',body=dict(gloss='house')))
        self.api('morpheme-save',dict(form='-ka',body=dict(gloss='LOC')))
        src=self.source('corpus',[('home-ka','')]);self.complete(src)
        dst=self.source('independent',[('homeka','')]);c=self.reuse(dst)
        self.assertEqual(self.detail(dst)['body']['words'][0]['gloss'],'house-LOC')
        self.assertTrue(all(self.api('lexeme?id='+t['lexeme_id'])['target_kind']=='morpheme' for t in c['links']))


del _Fixtures


if __name__ == '__main__':
    unittest.main()
