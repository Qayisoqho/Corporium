import test_server
import unittest
import json


class OrganizationTests(unittest.TestCase):
    setUp = test_server.APITests.setUp
    tearDown = test_server.APITests.tearDown
    call = test_server.APITests.call
    def test_split_order_identity_and_undo(self):
        tid,entries=self.seed('Split',3)
        payload={'source_id':tid,'ids':[entries[2]['id'],entries[0]['id']],'title':'New'}
        self.assertEqual(self.call('/api/split',{**payload,'title':' '})[0],400)
        code,result=self.call('/api/split',payload);self.assertEqual(code,200,result)
        moved=self.call('/api/entries?text='+result['id'])[1]['items']
        self.assertEqual([e['id'] for e in moved],[entries[0]['id'],entries[2]['id']])
        self.assertEqual(moved[0]['words'][0]['unit_id'],entries[0]['words'][0]['unit_id'])
        self.assertEqual([e['position'] for e in moved],[1,2])
        self.assertEqual(self.call('/api/split',payload)[0],400)
        self.assertEqual(len(self.call('/api/texts')[1]),2)
        state=self.call('/api/undo-state')[1]
        self.assertEqual(self.call('/api/undo',{'generation':state['generation']})[0],200)
        self.assertEqual(len(self.call('/api/texts')[1]),1)
        self.assertEqual([e['id'] for e in self.call('/api/entries?text='+tid)[1]['items']],[e['id'] for e in entries])
        state=self.call('/api/undo-state')[1]
        self.assertEqual(self.call('/api/redo',{'generation':state['generation']})[0],200)
        self.assertEqual(self.call('/api/entries?text='+result['id'])[1]['total'],2)
    def seed(self,title,n):
        r=self.call('/api/import',{'title':title,'source':title+'.typ','content':'\n'.join(f'#pass([{title}{i}], (([word],[tag]),), [{title}{i}])' for i in range(n))})[1]
        return r['id'],self.call('/api/entries?text='+r['id'])[1]['items']

    def test_delete_confirmation_order_and_backup(self):
        tid,entries=self.seed('A',3)
        payload={'id':entries[1]['id'],'text_id':tid,'revision':1}
        self.assertEqual(self.call('/api/delete-entry',payload)[0],400)
        status,r=self.call('/api/delete-entry',{**payload,'confirmed':True})
        self.assertEqual(status,200)
        left=self.call('/api/entries?text='+tid)[1]['items']
        self.assertEqual([e['translation'] for e in left],['A0','A2'])
        self.assertEqual([e['position'] for e in left],[1,2])
        from pathlib import Path
        backup=json.loads((Path(self.temp.name)/'backups'/r['backup']).read_text(encoding='utf-8'))
        self.assertEqual(len(backup['entries']),3)
        self.assertEqual(self.call('/api/delete-text',{'id':tid,'count':3,'confirmed':True})[0],400)
        self.assertEqual(self.call('/api/delete-text',{'id':tid,'count':2,'confirmed':True})[0],200)
        self.assertEqual(self.call('/api/texts')[1],[])

    def test_move_positions_and_history(self):
        aid,a=self.seed('A',4);bid,b=self.seed('B',2)
        self.call('/api/save',{**a[2],'notes':'keep'})
        # Deliberately reverse clicked IDs: retain source order.
        status,r=self.call('/api/move',{'source_id':aid,'target_id':bid,'ids':[a[2]['id'],a[0]['id']],'where':'before','before_id':b[1]['id']})
        self.assertEqual(status,200)
        dest=self.call('/api/entries?text='+bid)[1]['items']
        self.assertEqual([e['translation'] for e in dest],['B0','A0','A2','B1'])
        self.assertEqual(dest[2]['notes'],'keep')
        self.assertEqual(dest[2]['id'],a[2]['id'])
        self.assertEqual(dest[2]['origin']['title'],'A')
        self.assertEqual(len(self.call('/api/history?id='+a[2]['id'])[1]),1)
        self.assertEqual([e['position'] for e in self.call('/api/entries?text='+aid)[1]['items']],[1,2])
        self.assertEqual(self.call('/api/move',{'source_id':aid,'target_id':bid,'ids':[a[0]['id']],'where':'end'})[0],400)
        self.call('/api/move',{'source_id':aid,'target_id':bid,'ids':[a[1]['id']],'where':'start'})
        self.call('/api/move',{'source_id':aid,'target_id':bid,'ids':[a[3]['id']],'where':'end'})
        dest=self.call('/api/entries?text='+bid)[1]['items']
        self.assertEqual([e['translation'] for e in dest],['A1','B0','A0','A2','B1','A3'])
        self.assertEqual(self.call('/api/entries?text='+aid)[1]['total'],0)

    def test_merge_reverse_order_and_invalid_anchor(self):
        aid,a=self.seed('A',2);bid,b=self.seed('B',3)
        self.assertEqual(self.call('/api/move',{'source_id':aid,'target_id':bid,'ids':[a[0]['id']],'where':'before','before_id':'missing'})[0],400)
        self.assertEqual(self.call('/api/entries?text='+aid)[1]['total'],2)
        status,r=self.call('/api/merge',{'first_id':bid,'second_id':aid,'title':'Combined','counts':[3,2]})
        self.assertEqual(status,200)
        result=self.call('/api/entries?text='+bid)[1]['items']
        self.assertEqual([e['translation'] for e in result],['B0','B1','B2','A0','A1'])
        self.assertEqual([e['id'] for e in result],[e['id'] for e in b+a])
        self.assertEqual(len(self.call('/api/texts')[1]),1)
        original=self.call('/api/export?id='+bid+'&original=true')[1]
        self.assertIn('A0',original);self.assertIn('B0',original)
