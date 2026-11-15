"""Validate the bundled fictional example without reading any local project."""
from pathlib import Path
import json
import re
import sqlite3
import sys
import tempfile
import zipfile
from contextlib import closing

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import project_backup,record_sources,source_schema

def validate():
    source = Path(__file__).resolve().parent/'examples/Telira.corporium'
    with zipfile.ZipFile(source) as archive:
        if archive.namelist() != ['language.json']:
            raise ValueError('The built-in example must contain only language.json')
        bundle = json.loads(archive.read('language.json'))
    if bundle.get('media_files'):
        raise ValueError('The built-in example must not contain media')
    if not bundle.get('languages') and not bundle.get('language'):
        raise ValueError('Missing example language metadata')
    if any(re.match(r'^[A-Za-z]:[\\/]|^/', text.get('source', '')) for text in bundle.get('texts', [])):
        raise ValueError('The built-in example must not expose absolute local source paths')
    snapshot=source.with_suffix('.corporium-backup')
    with zipfile.ZipFile(snapshot) as z:
        assert set(z.namelist())=={'project.sqlite3','manifest.json'}
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['format']==project_backup.FORMAT and not manifest['media'] and not manifest['external_links']
    (ROOT/'build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'build',prefix='telira-public-') as temp:
        restored=Path(temp)/'corpus.sqlite3'
        project_backup.restore(snapshot,restored)
        with closing(sqlite3.connect(restored.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            assert record_sources.native(db)
            source_schema.validate_relations(db)
            assert [r[0] for r in db.execute('SELECT name FROM languages')]==['Tëlira']
            for table,n in [('texts',2),('entries',168),('lexemes',573),('grammar_tags',71),('gloss_bindings',1221),('undo_steps',0),('timeline_media',0)]:
                assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]==n,table
    print(json.dumps({'exchange':source.name,'starter':snapshot.name,'status':'validated'},ensure_ascii=False))

if __name__ == '__main__':
    validate()
