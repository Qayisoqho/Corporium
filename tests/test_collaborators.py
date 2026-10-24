import json
import unittest
import server
import collaborators
import test_timeline as base

class CollaboratorTests(unittest.TestCase):
    setUp=base.TimelineTests.setUp
    tearDown=base.TimelineTests.tearDown
    call=base.TimelineTests.call
    detail=base.TimelineTests.detail
    mutation=base.TimelineTests.mutation
    add=base.TimelineTests.add
    undo=base.TimelineTests.undo
    def person(self,name='甲',**meta):
        code,r=self.call('/api/timeline-speaker-save',dict(name=name,metadata=meta));self.assertEqual(code,200,r);return r['id']
    def links(self,kind='corpus',rid=None):
        rid=rid or self.eids[0];return self.call('/api/collaborator-links?kind='+kind+'&ids='+rid)[1][rid]
    def assign(self,people,kind='corpus',rid=None,mode='manual'):
        rid=rid or self.eids[0];return self.call('/api/collaborator-save',dict(kind=kind,id=rid,revision=self.links(kind,rid)['revision'],people=people,mode=mode))
    def test_multiple_text_roles_and_reference_delete_guard(self):
        a,b=self.person(),self.person('乙',classes=['转写人','自定义类'])
        refs=[dict(person_id=a,role='发言人'),dict(person_id=b,role='发言人'),dict(person_id=b,role='转写人')]
        self.assertEqual(self.assign(refs,'text',self.tid)[0],200)
        self.assertEqual(self.links('text',self.tid)['effective'],refs)
        p=next(p for p in self.call('/api/collaborators')[1]['speakers'] if p['id']==a)
        self.assertEqual(self.call('/api/timeline-speaker-delete',dict(record_id=a,revision=p['revision'],confirmed=True))[0],400)
        with server.connect(audit=False) as db:self.assertEqual(collaborators.text_names(db)[self.tid],'甲、乙')
    def test_timeline_inheritance_manual_override_conflict_and_undo(self):
        a,b=self.person(),self.person('乙');root=self.detail()['tracks'][0]
        self.mutation('track',track_id=root['id'],name='句子',speaker_id=a);self.add()
        self.assertEqual(self.links()['effective'][0]['person_id'],a)
        self.mutation('track',name='另一发言人',kind='sentence',speaker_id=b)
        other=next(t for t in self.detail()['tracks'] if t['id']!=root['id']);self.add(track=other['id'])
        self.assertTrue(self.links()['conflict'])
        self.assertEqual(self.assign([dict(person_id=b,role='发言人')])[0],200)
        self.assertFalse(self.links()['conflict']);self.assertEqual(self.links()['effective'][0]['person_id'],b)
        self.assertEqual(self.undo()[0],200);self.assertTrue(self.links()['conflict'])
        self.assertEqual(self.assign([],mode='manual')[0],200);self.assertEqual(self.links()['effective'],[])
        self.assertEqual(self.assign([dict(person_id='',role='发言人')],mode='auto')[0],200);self.assertTrue(self.links()['conflict'])
    def test_revision_scope_and_bad_person_rejected(self):
        p=self.person();args=dict(kind='corpus',id=self.eids[0],revision=0,people=[dict(person_id=p,role='发言人')])
        self.assertEqual(self.call('/api/collaborator-save',args)[0],200)
        self.assertEqual(self.call('/api/collaborator-save',args)[0],400)
        self.assertEqual(self.assign([dict(person_id='missing',role='发言人')])[0],400)
        lid=self.call('/api/save-language',dict(name='other'))[1]['id'];args['_language']=lid
        self.assertEqual(self.call('/api/collaborator-save',args)[0],400)
    def test_profile_writing_types_validation_and_delete_protection(self):
        code,t=self.call('/api/writing-save',dict(name='姓名音标',font='IPAPANNEW'));self.assertEqual(code,200,t)
        self.person(fields=[dict(name='姓名 IPA',value='aː',type_id=t['id'])],classes=['发言人'])
        self.assertEqual(self.call('/api/writing-delete',dict(id=t['id'],revision=t['revision'],confirmed=True))[0],400)
        self.assertEqual(self.call('/api/timeline-speaker-save',dict(name='坏引用',metadata={'fields':[dict(name='IPA',value='a',type_id='missing')]}))[0],400)
    def test_legacy_person_fields_preserved_once(self):
        old={'speakers':'甲、乙','speaker_home':'某地','transcriber':'丙','date':'2020'}
        with server.connect(audit=False) as db:
            db.execute('INSERT INTO text_info(text_id,metadata) VALUES(?,?)',(self.tid,json.dumps(old)))
            collaborators.initialize(db)
            m=json.loads(db.execute('SELECT metadata FROM text_info WHERE text_id=?',(self.tid,)).fetchone()[0]);self.assertNotIn('speakers',m);self.assertEqual(m['legacy_people']['speakers'],'甲、乙');self.assertEqual(m['date'],'2020')
            revision=db.execute('SELECT revision FROM text_info WHERE text_id=?',(self.tid,)).fetchone()[0];collaborators.initialize(db)
            self.assertEqual(db.execute('SELECT revision FROM text_info WHERE text_id=?',(self.tid,)).fetchone()[0],revision)
    def test_language_exchange_remaps_people_writings_text_and_sentence(self):
        t=self.call('/api/writing-save',dict(name='姓名音标',font='IPAPANNEW'))[1]
        other=self.call('/api/save-language',dict(name='另一参与语言'))[1]['id']
        a=self.person(language_ids=['ordos',other],fields=[dict(name='姓名 IPA',value='aː',type_id=t['id'])]);refs=[dict(person_id=a,role='发言人')]
        self.assign(refs,'text',self.tid);self.assign(refs)
        bundle=self.call('/api/export-language?language=ordos')[1]
        lid=self.call('/api/save-language',dict(name='导入目标'))[1]['id']
        code,r=self.call('/api/import-language',dict(bundle=bundle,_language=lid));self.assertEqual(code,200,r)
        linked=self.links('text',r['id']);pid=linked['people'][0]['person_id'];self.assertNotEqual(pid,a)
        with server.connect(audit=False) as db:
            m=json.loads(db.execute('SELECT metadata FROM timeline_speakers WHERE id=?',(pid,)).fetchone()[0]);self.assertNotEqual(m['fields'][0]['type_id'],t['id']);self.assertEqual(m['language_ids'],[lid,other]);collaborators.validate(db)
    def test_independent_example_multiple_speakers(self):
        with server.connect(audit=False) as db:
            db.execute("INSERT INTO dictionary_examples(id,language_id,body) VALUES('standalone','ordos',?)",(json.dumps(dict(ipa='a',words=[],targets=[])),))
        a,b=self.person(),self.person('乙');refs=[dict(person_id=a,role='发言人'),dict(person_id=b,role='发言人')]
        self.assertEqual(self.assign(refs,'independent','standalone')[0],200)
        self.assertEqual(self.links('independent','standalone')['effective'],refs)
    def test_delete_sentence_cleans_assignment_and_undo_restores(self):
        a=self.person();self.assign([dict(person_id=a,role='发言人')])
        with server.connect(audit=False) as db:row=dict(db.execute('SELECT * FROM entries WHERE id=?',(self.eids[0],)).fetchone())
        code,r=self.call('/api/delete-entry',dict(id=row['id'],text_id=row['text_id'],revision=row['revision'],confirmed=True));self.assertEqual(code,200,r)
        self.assertEqual(self.links()['people'],[]);self.assertEqual(self.undo()[0],200);self.assertEqual(self.links()['people'][0]['person_id'],a)
    def test_text_split_merge_and_sentence_copy_keep_references(self):
        a=self.person();refs=[dict(person_id=a,role='发言人')];self.assign(refs,'text',self.tid);self.assign(refs)
        code,r=self.call('/api/split',dict(source_id=self.tid,title='split',ids=[self.eids[1]]));self.assertEqual(code,200,r);other=r['id']
        self.assertEqual(self.links('text',other)['people'],refs)
        code,r=self.call('/api/merge',dict(first_id=self.tid,second_id=other,title='merged',counts=[1,1]));self.assertEqual(code,200,r)
        self.assertEqual(self.links('text',self.tid)['people'],refs)
        with server.connect(audit=False) as db:
            records=[dict(r) for r in db.execute('SELECT * FROM entries WHERE text_id=? ORDER BY position',(self.tid,))]
        code,r=self.call('/api/duplicate-entry',dict(id=self.eids[0],text_id=self.tid,revision=records[0]['revision'],order=[r['id'] for r in records],where='end'));self.assertEqual(code,200,r)
        self.assertEqual(self.links('corpus',r['id'])['people'],refs)
    def test_backup_restores_collaborators_and_type_replacement(self):
        from pathlib import Path
        from restore_backup import restore
        import sqlite3
        from contextlib import closing
        t=self.call('/api/writing-save',dict(name='姓名音标',font='IPAPANNEW'))[1]
        z=self.call('/api/writing-save',dict(name='另一书写',font='Junicode'))[1]
        a=self.person(fields=[dict(name='姓名',value='a',type_id=t['id'])]);self.assign([dict(person_id=a,role='发言人')])
        code,r=self.call('/api/writing-delete',dict(id=t['id'],revision=t['revision'],replacement_id=z['id'],confirmed=True));self.assertEqual(code,200,r)
        p=next(p for p in self.call('/api/collaborators')[1]['speakers'] if p['id']==a);self.assertEqual(json.loads(p['metadata'])['fields'][0]['type_id'],z['id'])
        backup=self.call('/api/backup')[1];path=Path(self.temp.name)/'people.json';path.write_text(json.dumps(backup),encoding='utf-8');target=Path(self.temp.name)/'restored.sqlite3';restore(path,target)
        with closing(sqlite3.connect(target)) as db:
            db.row_factory=sqlite3.Row;collaborators.validate(db);self.assertEqual(db.execute('SELECT COUNT(*) FROM collaborator_assignments').fetchone()[0],1)
