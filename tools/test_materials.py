"""Shared, hash-checked test baselines. Checkouts are independent writable copies.

The catalog is local build evidence, not research data or a shipped sample.
Legacy scripts can recreate retired input paths without keeping every copy.
"""
import argparse
import atexit
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
STORE=ROOT/'build/test-materials'
CATALOG=STORE/'catalog.json'
_verified={}
_restored={}


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def build_path(path):
    """Never resolve a working destination into real data or a directory link."""
    path=Path(path)
    if not path.is_absolute():path=ROOT/path
    absolute=Path(os.path.abspath(path))
    if not absolute.is_relative_to(ROOT/'build'):raise ValueError('Test output must stay under build/')
    if any(absolute.is_relative_to(ROOT/p) for p in ('build/media-venv','build/Corporium-dev')):raise ValueError('Do not write into development environments')
    for part in [absolute,*absolute.parents]:
        if part==ROOT:break
        if part.is_symlink() or part.is_junction():raise ValueError('Test output cannot use a directory link')
    resolved=absolute.resolve()
    if resolved==STORE or resolved.is_relative_to(STORE):raise ValueError('Working copies cannot overwrite the baseline store')
    return resolved


def catalog():
    if not CATALOG.exists():return dict(version=1,objects={},aliases={},profiles={})
    value=json.loads(CATALOG.read_text(encoding='utf-8'))
    if value.get('version')!=1:raise ValueError('Unsupported test material catalog')
    return value


def source(key,data=None):
    data=data or catalog()
    sha=data['profiles'].get(key,{}).get('sha256')
    if sha is None:
        p=Path(key)
        if p.is_absolute():
            try:key=p.resolve().relative_to(ROOT).as_posix()
            except ValueError:raise ValueError('Unknown test material')
        else:key=p.as_posix()
        sha=data['aliases'].get(key)
    if sha not in data['objects']:raise ValueError('Unknown test material: '+str(key))
    item=data['objects'][sha];path=ROOT/item['path']
    # Historical formal copies also live in the store: normal application backup
    # retention must never remove an input required by a future regression run.
    resolved=path.resolve()
    if not resolved.is_relative_to(STORE):raise ValueError('Baseline source outside the test material store')
    for part in [path,*path.parents]:
        if part==ROOT:break
        if part.is_symlink() or part.is_junction():raise ValueError('Baseline source cannot be a link')
    st=path.stat();stamp=(str(path),st.st_mtime_ns,st.st_size)
    if _verified.get(sha)!=stamp:
        if st.st_size!=item['bytes'] or digest(path)!=sha:raise ValueError('Test baseline checksum mismatch: '+str(key))
        _verified[sha]=stamp
    return path,sha


def checkout(key,destination,*,metadata=True):
    data=catalog();original,sha=source(key,data);dest=build_path(destination)
    if dest.exists():raise ValueError('Refusing to overwrite '+str(dest))
    profile=data['profiles'].get(key,{})
    meta=dest.with_suffix('.fixture.json')
    if metadata and profile.get('fixture') and meta.exists():raise ValueError('Refusing to overwrite fixture metadata')
    dest.parent.mkdir(parents=True,exist_ok=True)
    temporary=dest.with_name('.'+dest.name+'.'+uuid.uuid4().hex+'.tmp')
    created=False
    try:
        shutil.copyfile(original,temporary)
        if digest(temporary)!=sha:raise ValueError('Test material copy failed verification')
        # Exclusive destination creation also protects simultaneous checkouts.
        with dest.open('xb') as out:
            created=True
            with temporary.open('rb') as inp:shutil.copyfileobj(inp,out,1024*1024)
    except BaseException:
        if created:dest.unlink(missing_ok=True)
        raise
    finally:temporary.unlink(missing_ok=True)
    if metadata and profile.get('fixture'):
        with meta.open('x',encoding='utf-8') as stream:json.dump(profile['fixture'],stream,ensure_ascii=False,indent=2)
    return dest


def _cleanup_restored():
    for path,sha in list(_restored.items()):
        try:
            build_path(path)
            # Changed working results and unfinished transactions remain evidence.
            if any(Path(str(path)+s).exists() for s in ('-wal','-shm','-journal')):continue
            if path.exists() and digest(path)==sha:path.unlink()
        except (OSError,ValueError):pass


def referenced_aliases(script,data=None):
    script=Path(script).resolve();data=data or catalog()
    text=script.read_text(encoding='utf-8')
    try:constants=[n.value for n in ast.walk(ast.parse(text)) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
    except SyntaxError:return []
    found=[]
    for name in data['aliases']:
        path=ROOT/name;parts=Path(name).parts;directory='/'.join(parts[:-1]);local=path.parent==script.parent
        arguments=[Path(v) if Path(v).is_absolute() else ROOT/v for v in sys.argv[1:] if '/' in str(v) or '\\' in str(v)]
        explicit=name in text or directory in text or (len(parts)>2 and parts[1] in constants) or any(path.parent==a.resolve() for a in arguments)
        filename=path.name in constants or any(c and path.name.startswith(c.replace('\\','/').rsplit('/',1)[-1]) and ('sqlite3' in text) for c in constants if c.endswith('-'))
        if any(c in ('*.sqlite3','**/*.sqlite3') for c in constants) and path.is_relative_to(script.parent):filename=True
        if name in text or (filename and (local or explicit)):found.append(name)
    return found


def enable_legacy(script):
    """Restore only missing cataloged inputs referenced by this legacy entrypoint.

    An unchanged temporary input is removed at normal exit. Changed results stay
    in their original location. Captured before-source implementations are never
    rewritten and the baseline store is never exposed as a writable database.
    """
    data=catalog()
    if not data['aliases']:return []
    restored=[]
    for name in referenced_aliases(script,data):
        sha=data['aliases'][name]
        path=ROOT/name
        if path.exists():continue
        checkout(name,path,metadata=False);_restored[path]=sha;restored.append(path)
    return restored


atexit.register(_cleanup_restored)


def main():
    p=argparse.ArgumentParser(description='共用测试材料：独立取用、按配置生成、旧路径兼容')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('list')
    c=sub.add_parser('checkout');c.add_argument('profile');c.add_argument('destination')
    g=sub.add_parser('generate');g.add_argument('--profile',choices=['smoke','ordinary','dense','research','reduplication'],default='smoke');g.add_argument('--sentences',type=int,default=100);g.add_argument('--output',required=True);g.add_argument('--seed',type=int,default=20261024)
    r=sub.add_parser('run');r.add_argument('script');r.add_argument('args',nargs=argparse.REMAINDER)
    a=p.parse_args()
    if a.command=='list':print(json.dumps(catalog()['profiles'],ensure_ascii=False,indent=2))
    elif a.command=='checkout':print(checkout(a.profile,a.destination))
    elif a.command=='generate':
        from test_materials_generator import generate
        result=generate(a.profile,a.sentences,a.output,a.seed)
        print(json.dumps({k:result[k] for k in ('profile','requested_sentences','seed','database','sha256','validation')}|dict(counts=result['fixture']['counts']),ensure_ascii=False))
    else:
        script=Path(a.script).resolve();enable_legacy(script)
        raise SystemExit(subprocess.call([sys.executable,'-B',str(script),*a.args],env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}))


if __name__=='__main__':main()
