import undo_codec
import json
from pathlib import Path
import unittest
import test_server
import server
import journal
from unittest.mock import patch
from restore_backup import restore


class JournalTests(unittest.TestCase):
    setUp = test_server.APITests.setUp
    tearDown = test_server.APITests.tearDown
    call = test_server.APITests.call

    def test_chunk_encoded_journal_keeps_text_and_all_unicode(self):
        value='组合 e\u0301、汉字、𝒙🙂、引号"和换行\n'
        self.new(value)
        with server.connect(audit=False) as db:
            row=db.execute('SELECT typeof(changes),changes FROM undo_steps ORDER BY id DESC LIMIT 1').fetchone()
            self.assertEqual(row[0],'text')
            changes=undo_codec.decode(row[1])
            self.assertEqual(json.loads(journal.encode_changes(changes)),changes)
        self.command('undo');self.command('redo')
        self.assertEqual(self.call('/api/texts')[1][0]['title'],value)

    def command(self, name, **extra):
        state=self.call('/api/undo-state')[1]
        status,result=self.call('/api/'+name,{'generation':state['generation'],**extra})
        self.assertEqual(status,200,result)
        return result

    def new(self,title):
        return self.call('/api/new-text',{'title':title})[1]['id']

    def test_current_unit_snapshots_restore_without_reanalysis_and_old_history_reconciles(self):
        self.new('unit snapshots')
        original=self.call('/api/entries')[1]['items'][0]
        changed={**original,'words':[dict(form='word',gloss='词')],'notes':''}
        self.assertEqual(self.call('/api/save',changed)[0],200)
        with server.connect(audit=False) as db:
            step=db.execute('SELECT id,changes FROM undo_steps ORDER BY id DESC LIMIT 1').fetchone()
            delta=undo_codec.decode(step['changes'])
            self.assertTrue(any(c.get('units_complete') for c in delta if c['table']=='entries'))
        with patch('lexicon.sync_entry',side_effect=AssertionError('complete captured snapshots must not be rebuilt')):
            self.command('undo');self.command('redo')
        self.assertEqual(self.call('/api/entries')[1]['items'][0]['words'][0]['form'],'word')
        with server.connect(audit=False) as db:
            for c in delta:c.pop('units_complete',None)
            db.execute('UPDATE undo_steps SET changes=? WHERE id=?',(json.dumps(delta),step['id']))
        with patch('lexicon.sync_entry',wraps=server.lexicon.sync_entry) as sync:
            self.command('undo');self.assertTrue(sync.called)

    def test_edit_undo_redo_branch_and_conflict(self):
        self.new('A')
        original=self.call('/api/entries')[1]['items'][0]
        self.call('/api/save',{**original,'translation':'edited','notes':''})
        self.command('undo')
        self.assertEqual(self.call('/api/entries')[1]['items'][0]['translation'],'')
        self.assertEqual(self.call('/api/save',{**original,'notes':'stale'})[0],409)
        self.command('redo')
        self.assertEqual(self.call('/api/entries')[1]['items'][0]['translation'],'edited')
        self.command('undo')
        self.new('B')
        self.assertIsNone(self.call('/api/undo-state')[1]['redo'])
        self.assertEqual(self.call('/api/undo',{'generation':0})[0],400)

    def test_delete_restore_and_backup_roundtrip(self):
        tid=self.new('A')
        self.call('/api/delete-text',{'id':tid,'count':1,'confirmed':True})
        self.assertEqual(self.call('/api/texts')[1],[])
        self.command('undo')
        self.assertEqual(self.call('/api/texts')[1][0]['id'],tid)
        backup=Path(self.temp.name)/'backup.json'
        backup.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8')
        dest=Path(self.temp.name)/'restored.db'
        restore(backup,dest)
        server.DB=dest
        self.command('redo')
        self.assertEqual(self.call('/api/texts')[1],[])
        self.command('undo')
        self.assertEqual(self.call('/api/entries')[1]['total'],1)

    def test_limits_rollback_and_redo_chain(self):
        self.command('undo-limit',limit=10)
        for i in range(13):self.new(str(i))
        state=self.call('/api/undo-state')[1]
        self.assertEqual(len(state['steps']),10)
        self.call('/api/delete-text',{'id':'missing','count':0,'confirmed':True})
        self.assertEqual(self.call('/api/undo-state')[1],state)
        for i in range(10):self.command('undo')
        self.assertEqual(len(self.call('/api/texts')[1]),3)
        for i in range(10):self.command('redo')
        self.assertEqual(len(self.call('/api/texts')[1]),13)

    def test_merge_and_folder_delete(self):
        a=self.new('A');b=self.new('B')
        status,folder=self.call('/api/save-folder',{'name':'调查','metadata':{}})
        self.assertEqual(status,200)
        fid=folder['id']
        self.call('/api/save-text-info',{'id':b,'revision':0,'title':'B','folder_id':fid,'metadata':{'speaker':'someone'}})
        self.call('/api/delete-folder',{'id':fid,'revision':1,'confirmed':True})
        self.command('undo')
        self.assertEqual(self.call('/api/texts')[1][1]['folder_id'],fid)
        status,result=self.call('/api/merge',{'first_id':a,'second_id':b,'counts':[1,1],'title':'AB'})
        self.assertEqual(status,200,result)
        self.command('undo')
        self.assertEqual([t['title'] for t in self.call('/api/texts')[1]],['A','B'])
        self.assertEqual(self.call('/api/texts')[1][1]['folder_id'],fid)
        self.command('redo')
        self.assertEqual(self.call('/api/texts')[1][0]['count'],2)

    def test_move_is_one_step_and_survives_restart(self):
        a=self.new('A');b=self.new('B')
        entry=self.call('/api/entries?text='+a)[1]['items'][0]
        status,result=self.call('/api/move',{'source_id':a,'target_id':b,'ids':[entry['id']],'where':'start'})
        self.assertEqual(status,200,result)
        self.assertEqual(len(self.call('/api/undo-state')[1]['steps']),3)
        server.init()
        self.command('undo')
        self.assertEqual(self.call('/api/entries?text='+a)[1]['total'],1)
        self.command('redo')
        moved=self.call('/api/entries?text='+b)[1]['items']
        self.assertEqual(moved[0]['id'],entry['id'])
        self.assertEqual([e['position'] for e in moved],[1,2])

    def test_shrink_limit_with_partially_undone_chain(self):
        for i in range(20):self.new(str(i))
        for i in range(15):self.command('undo')
        self.command('undo-limit',limit=10)
        for i in range(5):self.command('redo')
        self.assertEqual(len(self.call('/api/texts')[1]),10)
        self.assertIsNone(self.call('/api/undo-state')[1]['redo'])
        for i in range(10):self.command('undo')
        self.assertEqual(self.call('/api/texts')[1],[])
