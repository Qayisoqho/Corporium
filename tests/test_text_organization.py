import base64
import unittest
import test_lexicon
import server

class TextOrganizationTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    undo=test_lexicon.LexiconTests.undo

    def text(self,name):return self.call('/api/new-text',dict(title=name,empty=True))[1]['id']
    def listing(self):return self.call('/api/texts?language=ordos')[1]
    def move(self,tid,folder='',before=None,snapshot=None):
        if snapshot is None:snapshot=[dict(id=t['id'],folder_id=t['folder_id'] or '',revision=t['info_revision']) for t in self.listing()]
        return self.call('/api/organize-text',dict(id=tid,folder_id=folder,before_id=before,snapshot=snapshot))

    def test_folder_reorder_undo_and_metadata_preservation(self):
        a=self.text('A');b=self.text('B');c=self.text('C');f=self.call('/api/save-folder',dict(name='Folder',metadata={}))[1]['id']
        self.assertEqual(self.move(c,before=a)[0],200);self.assertEqual([t['id'] for t in self.listing()],[c,a,b])
        self.assertEqual(self.move(a,f)[0],200);self.assertEqual(next(t for t in self.listing() if t['id']==a)['folder_id'],f)
        self.assertEqual(self.undo()[0],200);self.assertFalse(next(t for t in self.listing() if t['id']==a)['folder_id'])
        self.assertEqual(self.undo('redo')[0],200)
        t=next(t for t in self.listing() if t['id']==c)
        self.assertEqual(self.call('/api/save-text-info',dict(id=c,revision=t['info_revision'],title='C edited',source='',folder_id='',metadata={'notes':'preserve'}))[0],200)
        self.assertEqual([t['id'] for t in self.listing()],[c,b,a])
        self.assertEqual(self.move(c,f,before=a)[0],200);self.assertEqual([t['id'] for t in self.listing() if t['folder_id']==f],[c,a])
        self.assertIn('preserve',next(t for t in self.listing() if t['id']==c)['metadata'])

    def test_stale_cross_language_and_library_rejected_without_changes(self):
        a=self.text('A');b=self.text('B');snapshot=[dict(id=t['id'],folder_id=t['folder_id'] or '',revision=t['info_revision']) for t in self.listing()]
        self.assertEqual(self.move(b,before=a)[0],200);before=self.listing()
        self.assertEqual(self.move(a,before=b,snapshot=snapshot)[0],400)
        self.assertEqual(self.move(a,'@library')[0],400)
        lang=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id'];folder=self.call('/api/save-folder',dict(name='Foreign',metadata={},_language=lang))[1]['id']
        self.assertEqual(self.move(a,folder)[0],400);self.assertEqual(self.listing(),before)

    def test_typst_export_language_scope_and_literal_text(self):
        r=self.call('/api/import',dict(title='Text',content='#pass([ipa], (([a],[A]),), [translation])'))[1]
        code,out=self.call('/api/text-export',dict(id=r['id']));self.assertEqual(code,200,out);self.assertIn('translation',base64.b64decode(out['data']).decode())
        other=self.call('/api/save-language',dict(name='Other',metadata={}))[1]['id']
        self.assertEqual(self.call('/api/text-export',dict(id=r['id'],_language=other))[0],400)

    def test_copy_to_new_sentence_in_other_text_or_library_move_blocked(self):
        tid=self.call('/api/import',dict(title='Source',content='#pass([ipa], (([a],[A]),), [])'))[1]['id'];dest=self.text('Target')
        with server.connect(audit=False) as db:rid=db.execute('SELECT id FROM entries WHERE text_id=?',(tid,)).fetchone()[0]
        s=self.call('/api/word-transfer-snapshot?kind=corpus&id='+rid)[1]
        payload=dict(source=dict(kind='corpus',id=rid,token=s['transfer_token']),target=dict(kind='corpus',new=True,text_id=dest),slots=[s['words'][0]['id']],position=0,mode='move',confirmed=True)
        self.assertEqual(self.call('/api/word-transfer',payload)[0],400)
        payload['mode']='copy';code,r=self.call('/api/word-transfer',payload);self.assertEqual(code,200,r)
        with server.connect(audit=False) as db:self.assertEqual(db.execute('SELECT text_id FROM entries WHERE id=?',(r['target']['id'],)).fetchone()[0],dest)
        self.assertEqual(self.call('/api/text-export',dict(id=dest))[0],200)
        payload['target']=dict(kind='independent',new=True);code,r=self.call('/api/word-transfer',payload);self.assertEqual(code,200,r);self.assertEqual(r['target']['kind'],'independent')
        s=self.call('/api/word-transfer-snapshot?kind=independent&id='+r['target']['id'])[1];payload.update(source=dict(kind='independent',id=s['id'],token=s['transfer_token']),target=dict(kind='corpus',text_id=dest,new=True),slots=[s['words'][0]['id']])
        self.assertEqual(self.call('/api/word-transfer',payload)[0],200)

if __name__=='__main__':unittest.main()
