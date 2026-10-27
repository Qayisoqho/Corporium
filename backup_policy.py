"""Bounded automatic snapshots; manual downloads are never retention candidates."""
import json
import logging
import re
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path

LIMITS=(5,10,20,30)
DEFAULT=20
LOCK=threading.RLock()
AUTOMATIC=re.compile(r'(?:\d{8}T\d{6}-[0-9a-f]{8}\.json|before-(?:languages|lexicon)-[0-9a-f]{8}\.sqlite3|before-desktop-\d{8}-\d{6}-\d{6}\.sqlite3)\Z')

def limit(folder):
    file=Path(folder).parent/'backup-policy.json'
    if not file.exists():return DEFAULT
    value=json.loads(file.read_text(encoding='utf8')).get('limit')
    if type(value)==int and value in (40,50,100):return 30  # Legacy choices use the new upper bound.
    if type(value)!=int or value not in LIMITS:raise ValueError('自动备份设置无效，请在全局设置中重新保存')
    return value

def candidates(folder):
    folder=Path(folder)
    if not folder.exists():return []
    if folder.is_symlink() or getattr(folder,'is_junction',lambda:False)():raise ValueError('自动备份目录不能是链接或目录联接')
    files=[]
    for p in folder.iterdir():
        if AUTOMATIC.fullmatch(p.name) and p.is_file() and not p.is_symlink() and p.resolve().parent==folder.resolve():
            try:files.append((p.stat().st_mtime_ns,p.name,p))
            except FileNotFoundError:continue  # Another local app may have pruned it.
    return [p for _,_,p in sorted(files,reverse=True)]

def status(folder):
    with LOCK:
        files=candidates(folder)
        sizes=[]
        for p in files:
            try:sizes.append(p.stat().st_size)
            except FileNotFoundError:continue
        return dict(limit=limit(folder),choices=LIMITS,count=len(sizes),bytes=sum(sizes))

def prune(folder,keep=None):
    with LOCK:
        maximum=limit(folder);files=candidates(folder)
        # Always keep the snapshot that has just completed, even if clock time moved back.
        if keep is not None:files.sort(key=lambda p:p.name==keep,reverse=True)
        for p in files[maximum:]:
            try:p.unlink()
            except OSError as error:logging.warning('Cannot remove automatic backup %s: %s',p,error)

def save_policy(folder,value):
    if type(value)!=int or value not in LIMITS:raise ValueError('请选择有效的自动备份保留份数')
    folder=Path(folder)
    with LOCK:
        folder.parent.mkdir(parents=True,exist_ok=True)
        file=folder.parent/'backup-policy.json';temp=file.with_name('.backup-policy-'+uuid.uuid4().hex+'.tmp')
        try:temp.write_text(json.dumps({'limit':value}),encoding='utf8');temp.replace(file)
        finally:temp.unlink(missing_ok=True)
        prune(folder)
        return status(folder)

def write_json(folder,data,*,stream=False,defer_prune=False):
    name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.json'
    def writer(path):
        if stream:
            import streaming_json,long_tasks
            with path.open('wb') as dest:streaming_json.write(data,dest,long_tasks.checkpoint)
        else:path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
    return write(folder,name,writer,defer_prune=defer_prune)

def sqlite_snapshot(folder,source,prefix):
    if prefix not in ('languages','lexicon','desktop'):raise ValueError('未知自动备份类型')
    suffix=datetime.now().strftime('%Y%m%d-%H%M%S-%f') if prefix=='desktop' else uuid.uuid4().hex[:8]
    def copy(path):
        with closing(sqlite3.connect(path)) as destination:source.backup(destination)
    return write(folder,'before-'+prefix+'-'+suffix+'.sqlite3',copy)

def write(folder,name,writer,*,defer_prune=False):
    folder=Path(folder)
    with LOCK:
        folder.mkdir(parents=True,exist_ok=True)
        candidates(folder);limit(folder)  # Validate before creating or pruning anything.
        target=folder/name;temp=folder/('.'+name+'.tmp')
        try:writer(temp);temp.replace(target)
        finally:temp.unlink(missing_ok=True)
        if not defer_prune:prune(folder,name)
        return name
