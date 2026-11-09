"""New-language imports preserve supplied classification catalogues verbatim."""
import json
from pathlib import Path
import tempfile
import unittest
import categories
import language_exchange
import languages
import server

class ExchangeCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=server.ROOT/'build',prefix='catalogue-test-')
        self.previous=server.DB;server.DB=Path(self.temp.name)/'corpus.sqlite3';server.init()

    def tearDown(self):
        server.DB=self.previous;self.temp.cleanup()

    def bundle(self):
        with server.connect(audit=False) as db:
            result=language_exchange.export_bundle(db,'ordos')
        for i,c in enumerate(result['category_classes']):
            if c['kind'] in ('form','usage_tag'):c['name']=f'English {c["kind"]} {i}'
        return result

    def load(self,bundle):
        path=Path(self.temp.name)/'language.json';path.write_text(json.dumps(bundle),encoding='utf-8')
        with server.connect(audit=False) as db:
            lid=language_exchange.import_new(db,server.DB,path,'Imported',[])['language_id']
        return lid

    def test_new_package_keeps_translated_catalogues_without_factory_duplicates(self):
        bundle=self.bundle();expected={(r['kind'],r['name']) for r in bundle['category_classes']}
        lid=self.load(bundle)
        with server.connect(audit=False) as db:
            actual={(r['kind'],r['name']) for r in categories.listing(db,lid)}
            self.assertEqual(actual,expected)
        # Reopening the project must not add the factory language names back.
        server.init()
        with server.connect(audit=False) as db:self.assertEqual({(r['kind'],r['name']) for r in categories.listing(db,lid)},expected)

    def test_legacy_package_without_catalogues_retains_default_seeding(self):
        bundle=self.bundle();bundle.pop('category_classes')
        lid=self.load(bundle)
        with server.connect(audit=False) as db:
            rows=categories.listing(db,lid)
            self.assertEqual({r['name'] for r in rows if r['kind']=='form'},set(categories.FORM_NAMES.values()))
            self.assertEqual({r['name'] for r in rows if r['kind']=='usage_tag'},set(categories.TAG_NAMES.values()))

    def test_supplied_form_catalogue_does_not_suppress_unsupplied_usage_catalogue(self):
        bundle=self.bundle();bundle['category_classes']=[r for r in bundle['category_classes'] if r['kind']=='form']
        lid=self.load(bundle)
        with server.connect(audit=False) as db:
            rows=categories.listing(db,lid)
            self.assertEqual({r['name'] for r in rows if r['kind']=='form'},{r['name'] for r in bundle['category_classes']})
            self.assertEqual({r['name'] for r in rows if r['kind']=='usage_tag'},set(categories.TAG_NAMES.values()))

if __name__=='__main__':unittest.main()
