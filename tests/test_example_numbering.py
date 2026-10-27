import copy
import json
import sqlite3
import unittest
from pathlib import Path
from contextlib import closing
import test_server
import server
import example_numbering
import language_exchange
import languages
import project_backup
from restore_backup import restore


class ExampleNumberingTests(unittest.TestCase):
    setUp=test_server.APITests.setUp
    tearDown=test_server.APITests.tearDown
    call=test_server.APITests.call

    def example(self, text='one', lid='ordos'):
        code,result=self.call('/api/example-save',dict(_language=lid,body=dict(ipa=text,translation=text,words=[dict(form=text,gloss='词')])) )
        self.assertEqual(code,200,result)
        return result

    def record(self, eid):
        code,result=self.call('/api/independent-example?language=all&id='+eid)
        self.assertEqual(code,200,result);return result

    def delete(self, eid):
        row=self.record(eid)
        code,result=self.call('/api/example-delete',dict(id=eid,revision=row['revision'],confirmed=True,_language=row['owner_language']))
        self.assertEqual(code,200,result)

    def undo(self, redo=False):
        generation=self.call('/api/undo-state')[1]['generation']
        code,result=self.call('/api/'+('redo' if redo else 'undo'),dict(generation=generation))
        self.assertEqual(code,200,result)

    def library(self, suffix=''):
        code,result=self.call('/api/example-groups-library?language=ordos'+suffix)
        self.assertEqual(code,200,result);return result

    def test_upgrade_backfills_in_original_order_without_changing_sentences_or_references(self):
        ids=[self.example(str(i))['id'] for i in range(3)]
        with server.connect() as db:
            before=[tuple(r) for r in db.execute('SELECT rowid,* FROM dictionary_examples ORDER BY rowid')]
            db.execute('DROP TABLE example_numbers');db.execute('DROP TABLE example_number_counters')
        server.init()
        with server.connect() as db:
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT rowid,* FROM dictionary_examples ORDER BY rowid')])
        self.assertEqual([self.record(e)['library_number'] for e in ids],[1,2,3])
        snapshots=list((server.DB.parent/'backups').glob('*.sqlite3'));self.assertTrue(snapshots)
        with closing(sqlite3.connect(snapshots[-1])) as old:
            self.assertIsNone(old.execute("SELECT name FROM sqlite_master WHERE name='example_numbers'").fetchone())
        server.init();self.assertEqual([self.record(e)['library_number'] for e in ids],[1,2,3])

    def test_number_is_language_local_and_ignores_any_client_supplied_number(self):
        first=self.example();self.assertEqual(first['library_number'],1)
        with server.connect() as db:db.execute("INSERT INTO languages VALUES('other','Other','{}',1)")
        self.assertEqual(self.example(lid='other')['library_number'],1)
        code,row=self.call('/api/example-save',dict(body=dict(ipa='two',words=[],library_number=1),library_number=1))
        self.assertEqual(code,200,row);self.assertEqual(row['library_number'],2)
        self.assertNotIn('library_number',row['body'])

    def test_delete_and_undo_creation_never_make_a_reserved_number_available_to_another_sentence(self):
        a,b=[self.example(str(i)) for i in range(2)]
        self.delete(b['id']);self.assertEqual(self.example('c')['library_number'],3)
        self.undo();self.undo();self.assertEqual(self.record(b['id'])['library_number'],2)
        self.undo(True);self.assertEqual(self.example('d')['library_number'],4)
        self.assertEqual(self.record(a['id'])['library_number'],1)

    def test_redo_creation_recovers_its_original_number(self):
        row=self.example();self.undo();self.undo(True)
        self.assertEqual(self.record(row['id'])['library_number'],1)
        self.assertEqual(self.example()['library_number'],2)

    def test_group_order_sorting_filter_and_content_changes_do_not_change_numbers(self):
        rows=[self.example(str(i)) for i in range(5)]
        code,g=self.call('/api/example-group-save',dict(body=dict(numbering='letters'),members=[dict(example_id=rows[i]['id'],role=role) for i,role in [(3,'Q'),(0,'A')]]))
        self.assertEqual(code,200,g)
        self.assertEqual([m['record']['library_number'] for m in g['members']],[4,1])
        asc=self.library()['items'];desc=self.library('&sort_order=added-desc')['items']
        self.assertEqual(asc[0]['id'],g['id']);self.assertEqual([r['id'] for r in desc],list(reversed([r['id'] for r in asc])))
        self.assertEqual([m['role'] for m in desc[-1]['group']['members']],['Q','A'])
        filtered=self.library('&q=2&field=ipa')['items'];self.assertEqual(filtered[0]['body']['library_number'],3)
        row=self.record(rows[3]['id']);row['body']['translation']='changed'
        code,saved=self.call('/api/example-save',dict(id=row['id'],revision=row['revision'],body=row['body']))
        self.assertEqual(code,200,saved);self.assertEqual(saved['library_number'],4)
        self.assertEqual(self.call('/api/example-groups-library?sort_order=bad')[0],400)

    def test_pagination_does_not_restart_numbering(self):
        for i in range(22):self.example(str(i))
        self.assertEqual([x['body']['library_number'] for x in self.library('&page=2')['items']],[21,22])
        self.assertEqual([x['body']['library_number'] for x in self.library('&sort_order=added-desc&page=2')['items']],[2,1])

    def test_language_exchange_preserves_gaps_highwater_and_remaps_identity(self):
        rows=[self.example(str(i)) for i in range(4)];self.delete(rows[1]['id']);self.delete(rows[-1]['id'])
        with server.connect() as db:
            bundle=language_exchange.export_bundle(db,'ordos')
            self.assertEqual([e['library_number'] for e in bundle['dictionary_examples']],[1,3])
            self.assertEqual(bundle['example_number_next'],5)
            db.execute("INSERT INTO languages VALUES('copy','Copy','{}',1)")
            languages.import_bundle(db,bundle,'copy')
            imported=list(db.execute("SELECT d.id,n.number FROM dictionary_examples d JOIN example_numbers n ON n.id=d.id AND n.language_id=d.language_id WHERE d.language_id='copy' ORDER BY n.ordering"))
            self.assertEqual([r['number'] for r in imported],[1,3]);self.assertFalse({r['id'] for r in imported}&{r['id'] for r in rows})
        self.assertEqual(self.example(lid='copy')['library_number'],5)
        self.assertEqual(self.example()['library_number'],5)

    def test_legacy_language_import_numbers_in_bundle_order_and_invalid_numbers_roll_back(self):
        self.example('a');self.example('b')
        with server.connect() as db:bundle=language_exchange.export_bundle(db,'ordos')
        legacy=copy.deepcopy(bundle);legacy.pop('example_number_next')
        for e in legacy['dictionary_examples']:e.pop('library_number')
        with server.connect() as db:
            db.execute("INSERT INTO languages VALUES('legacy','Legacy','{}',1)");languages.import_bundle(db,legacy,'legacy')
            self.assertEqual([r[0] for r in db.execute("SELECT number FROM example_numbers WHERE language_id='legacy' ORDER BY ordering")],[1,2])
        for value in [1,0,True]:
            bad=copy.deepcopy(bundle);bad['dictionary_examples'][1]['library_number']=value
            with self.assertRaises(ValueError):
                with server.connect() as db:
                    db.execute("INSERT INTO languages VALUES('invalid','Invalid','{}',1)");languages.import_bundle(db,bad,'invalid')
            with server.connect() as db:self.assertIsNone(db.execute("SELECT id FROM languages WHERE id='invalid'").fetchone())

    def test_json_and_sqlite_backup_restore_reserved_numbers_and_undo(self):
        row=self.example();self.example('delete');self.undo()
        json_path=Path(self.temp.name)/'numbered.json';json_path.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf8')
        with server.connect(audit=False) as db:prepared=project_backup.prepare(db,server.DB)
        package=language_exchange.staged(server.DB,prepared['token'],'project-backup')
        original=server.DB
        try:
            for source,name in [(json_path,'json'),(package,'sqlite')]:
                target=Path(self.temp.name)/(name+'.sqlite3');restore(source,target);server.DB=target;server.init()
                self.assertEqual(self.record(row['id'])['library_number'],1)
                self.undo(True)
                self.assertEqual(self.example()['library_number'],3)
                server.DB=original
        finally:Path(package).unlink(missing_ok=True)

    def test_reads_do_not_allocate_or_write_numbers(self):
        row=self.example()
        with server.connect(audit=False) as db:
            import example_groups
            example_groups.library(db,'ordos',{})
            server.annotations.get(db,'independent',row['id'])
            language_exchange.export_bundle(db,'ordos')
            self.assertEqual(db.total_changes,0)


if __name__=='__main__':unittest.main()
