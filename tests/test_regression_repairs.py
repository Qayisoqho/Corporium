"""Real regressions: copied sense bindings and explicit edits of linked slots."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
import unittest
import server
import long_tasks
import test_dictionary_gloss_sync as legacy
import test_long_task_writes as write_tasks


class RegressionRepairTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','seed','entries','undo','api','word','example','detail','link'):
        locals()[name]=getattr(legacy.DictionaryGlossSyncTests,name)
    for name in ('submit','wait','snapshot'):
        locals()[name]=getattr(write_tasks.WriteTasks,name)

    def bound_sentence(self):
        e=self.seed('#pass([ipa], (([home-n],[家-GEN]),([free],[])), [translation])')
        whole=self.word('home-n',['家-GEN']);child=self.word('n',['GEN'])
        self.link(e,whole,'@word');self.link(e,child,'1:host')
        d=self.api('annotations?kind=corpus&id='+e['id'])
        source=next(r for r in d['body']['words'][0]['gloss_sources'] if r['key']=='1:host')
        self.api('gloss-source-save',dict(kind='corpus',id=e['id'],revision=d['revision'],binding_id=source['id'],binding_revision=source['revision'],gloss_revision=d['body']['gloss_revision'],mode='override',value='POSS'))
        whole=self.change(whole,'住所-GEN')
        return self.entries()[0],whole,child

    def change(self,x,label):
        x=self.api('lexeme?id='+x['id']);x['body']['usages'][0]['senses'][0]['short_gloss']=label
        return self.api('lexeme-save',x)

    def assert_copy(self,a,b):
        self.assertNotEqual(a['id'],b['id'])
        self.assertEqual([w['gloss'] for w in a['words']],['住所-POSS',''])
        self.assertEqual([w['gloss'] for w in b['words']],['住所-POSS',''])
        self.assertNotEqual(a['words'][0]['unit_id'],b['words'][0]['unit_id'])
        self.assertEqual({r['key']:r['mode'] for r in b['words'][0]['gloss_sources']},{'@word':'inherit','1:host':'override'})
        with server.connect(audit=False) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            src={r[0] for r in db.execute('SELECT id FROM corpus_units WHERE entry_id=?',(a['id'],))}
            dst={r[0] for r in db.execute('SELECT id FROM corpus_units WHERE entry_id=?',(b['id'],))}
            self.assertEqual(len(src),len(dst));self.assertTrue(src.isdisjoint(dst))

    def test_duplicate_bound_morpheme_after_meaning_change_keeps_modes(self):
        e,whole,child=self.bound_sentence()
        r=self.api('duplicate-entry',dict(id=e['id'],text_id=e['text_id'],revision=e['revision'],order=[e['id']],where='end'))
        a,b=self.entries();self.assertEqual(b['id'],r['id']);self.assert_copy(a,b)
        self.change(whole,'房屋-GEN');self.change(child,'DAT')
        self.assertEqual([r['words'][0]['gloss'] for r in self.entries()],['房屋-POSS']*2)
        # Removing both meaning edits and the copy restores just the source.
        for _ in range(3):self.assertEqual(self.undo()[0],200)
        self.assertEqual([r['id'] for r in self.entries()],[e['id']])
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.entries()[1]['id'],r['id'])

    def test_batch_copy_bound_morpheme_cancel_rollback_retry_and_undo(self):
        import gloss_inheritance
        e,whole,child=self.bound_sentence()
        target=self.api('new-text',dict(title='Target',empty=True))['id']
        payload=dict(source_id=e['text_id'],target_id=target,ids=[e['id']],where='end')
        before=self.snapshot();folder=Path(self.temp.name)/'backups';files={p.name for p in folder.glob('*')};observed=[]
        original=gloss_inheritance.copy_binding
        def cancel_after_copy(db,*args,**kwargs):
            result=original(db,*args,**kwargs)
            observed.append(db.execute('SELECT COUNT(*) FROM gloss_bindings').fetchone()[0])
            job=long_tasks.CURRENT.get();long_tasks.cancel(job['project'],job['id']);long_tasks.checkpoint()
            return result
        with patch('gloss_inheritance.copy_binding',cancel_after_copy):state=self.wait(self.submit('copy-entries',payload))
        self.assertEqual(state['state'],'cancelled',state);self.assertTrue(observed)
        self.assertEqual(self.snapshot(),before);self.assertEqual({p.name for p in folder.glob('*')},files)
        state=self.wait(self.submit('copy-entries',payload));self.assertEqual(state['state'],'done',state)
        copied=self.api('entries?text='+target)['items'][0];self.assert_copy(self.api('entries?text='+e['text_id'])['items'][0],copied)
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.api('entries?text='+target)['total'],0)
        self.assertEqual(self.undo('redo')[0],200)
        self.assertEqual(self.api('entries?text='+target)['items'][0]['id'],copied['id'])

    def test_explicit_linked_slot_edit_keeps_blank_override_and_retired_evidence(self):
        e,whole,child=self.bound_sentence();old=e['words'][0]['unit_id']
        layer=self.api('layer-save',dict(name='Research',font='Junicode',style='normal',size=100,visible=True,searchable=True,position=0))
        d=self.api('annotations?kind=corpus&id='+e['id'])
        # Attach a real layer before changing both rows of a linked word.
        self.api('annotation-save',dict(kind='corpus',id=e['id'],revision=d['revision'],before=d['cells'],layers=d['layers'],cells=[dict(unit_id=old,layer_id=layer['id'],value='KEEP')]))
        d=self.api('annotations?kind=corpus&id='+e['id']);before=copy.deepcopy(d)
        d['body']['words'][0].update(form='。',gloss='')
        self.api('inline-save',dict(kind='corpus',id=e['id'],revision=d['revision'],before=d['cells'],cells=d['cells'],layers=d['layers'],body=d['body'],slot_ids=[w['id'] for w in d['words']]))
        edited=self.entries()[0]['words'][0]
        self.assertEqual((edited['form'],edited['gloss'],edited['unit_type'],edited['unit_id']),('。','','word',old))
        self.assertEqual([(r['key'],r['mode']) for r in edited['gloss_sources']],[('@word','override')])
        self.assertEqual(self.api('annotations?kind=corpus&id='+e['id'])['cells'],before['cells'])
        self.assertTrue(self.api('lexeme-examples?id='+child['id'])['items'][0]['needs_review'])
        self.change(whole,'房屋-GEN');self.assertEqual(self.entries()[0]['words'][0]['gloss'],'')
        self.assertEqual(self.undo()[0],200);self.assertEqual(self.undo()[0],200)
        restored=self.entries()[0]['words'][0];self.assertEqual((restored['form'],restored['gloss'],restored['unit_id']),('home-n','住所-POSS',old))
        self.assertEqual(self.undo('redo')[0],200);self.assertEqual(self.entries()[0]['words'][0]['gloss'],'')

if __name__=='__main__':unittest.main()
