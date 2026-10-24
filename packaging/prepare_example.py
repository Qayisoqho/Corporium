"""Validate the bundled fictional example without reading any local project."""
from pathlib import Path
import json
import re
import zipfile

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
    print(json.dumps({'example': source.name, 'bytes': source.stat().st_size,
                      'media_files': 0, 'status': 'validated'}, ensure_ascii=False))

if __name__ == '__main__':
    validate()
