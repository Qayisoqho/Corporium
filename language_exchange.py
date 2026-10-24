import json
import io
import streaming_json
import languages
import lexicon
import timeline
import collaborators
import grammar_survey
import fieldwork_notes
import code_switching
import gloss_inheritance
import grammaticality


def export_bundle(db,lid,stream=False):
    language=grammaticality.export_language(languages.require(db,lid))
    text_rows=[dict(r) for r in db.execute('SELECT * FROM texts WHERE language_id=? ORDER BY rowid',(lid,))]
    for t in text_rows:
        t['info']=dict(db.execute('SELECT * FROM text_info WHERE text_id=?',(t['id'],)).fetchone() or {})
        t['entries']=streaming_json.Rows(db,'SELECT * FROM entries WHERE text_id=? ORDER BY position',(t['id'],),transform=lambda r:gloss_inheritance.export_body(db,'corpus',r)) if stream else [gloss_inheritance.export_body(db,'corpus',r) for r in gloss_inheritance.iter_rows(db,db.execute('SELECT * FROM entries WHERE text_id=? ORDER BY position',(t['id'],)),'corpus')]
    # Include referenced languages so mixed-language annotations remain interpretable.
    refs={json.loads(e['body']).get('language_id') for t in text_rows for e in t['entries']}-{None,'',lid}
    dictionary=lexicon.export_bundle(db,lid,stream=stream)
    refs|={x['language_id'] for x in dictionary['lexemes']+dictionary['annotation_layers']}-{lid}
    people_bundle=collaborators.export_bundle(db,lid)
    alignment=timeline.export_bundle(db,lid)
    code_ids={r['id'] for r in alignment['timeline_codes']}|{r[0] for r in db.execute('SELECT DISTINCT code_id FROM code_spans WHERE language_id=? AND code_id IS NOT NULL',(lid,))}
    alignment['timeline_codes']=[dict(r) for r in db.execute('SELECT * FROM timeline_codes ORDER BY name,id') if r['id'] in code_ids]
    refs.update(json.loads(c['metadata'])['workspace_language_id'] for c in alignment['timeline_codes'] if json.loads(c['metadata']).get('workspace_language_id') not in (None,'',lid))
    refs.update(x for p in people_bundle['timeline_speakers'] for x in json.loads(p['metadata']).get('language_ids',[]) if x!=lid and db.execute('SELECT 1 FROM languages WHERE id=?',(x,)).fetchone())
    return ({'format':'corpus-language-v1','language':language,'referenced_languages':[grammaticality.export_language(languages.require(db,x)) for x in refs], 'folders':[dict(r) for r in db.execute('SELECT * FROM folders WHERE language_id=? ORDER BY position',(lid,))],'texts':text_rows,**dictionary,**alignment,**people_bundle,**grammar_survey.export_bundle(db,lid),**fieldwork_notes.export_bundle(db,lid,stream=stream),**code_switching.export_bundle(db,lid,stream=stream)})

# Exchange files are staged outside project data and expire after an hour.
import tempfile
import secrets
import time
import zipfile
import shutil
import threading
from pathlib import Path
import media_engine
STAGING=tempfile.TemporaryDirectory(prefix="corporium-exchange-")
STAGED={}
LOCK=threading.RLock()
MAX_PACKAGE=20*1024**3
MAX_JSON=MAX_PACKAGE
EXPORT_KINDS={'project-backup','language-json','analysis-json','export'}

def discard(token):
    item=STAGED.pop(token,None)
    if item and item['path'].resolve().is_relative_to(Path(STAGING.name).resolve()) and not any(x['path']==item['path'] for x in STAGED.values()):
        try:item['path'].unlink(missing_ok=True)
        except PermissionError:
            # A save/download may already have this file open on Windows.
            STAGED[token]=item

def prune():
    with LOCK:
        for key,item in list(STAGED.items()):
            if time.time()-item['time']>3600:discard(key)

def cleanup_loop():
    while True:
        time.sleep(60)
        prune()

threading.Thread(target=cleanup_loop,daemon=True,name='corporium-staged-cleanup').start()


def stage(dbpath,path,kind):
    with LOCK:
        prune()
        project=str(Path(dbpath).resolve())
        if kind in EXPORT_KINDS:
            older=[key for key,item in STAGED.items() if item['db']==project and item['kind'] in EXPORT_KINDS]
            for key in older[:-2]:discard(key)
        token=secrets.token_urlsafe(32)
        STAGED[token]=dict(path=Path(path),db=project,kind=kind,time=time.time())
        import long_tasks
        job=long_tasks.CURRENT.get()
        if job and job['kind']=='operation':job.setdefault('staged',[]).append(token)
    return token


def staged(dbpath,token,kind):
    with LOCK:
        item=STAGED.get(token)
        if not item or item['db']!=str(Path(dbpath).resolve()) or item['kind']!=kind or time.time()-item['time']>3600:raise ValueError('数据包预览已过期，请重新选择文件')
        return item['path']


def info(bundle):
    if not isinstance(bundle,dict) or bundle.get('format')!='corpus-language-v1' or not isinstance(bundle.get('language'),dict):raise ValueError('请选择 Corporium 单语言数据包或旧版单语言 JSON')
    return dict(name=bundle['language']['name'],texts=len(bundle.get('texts',[])),sentences=sum(len(t.get('entries',[])) for t in bundle.get('texts',[])),examples=len(bundle.get('dictionary_examples',[])),lexemes=len(bundle.get('lexemes',[])),timelines=len(bundle.get('timeline_sessions',[])),media=len(bundle.get('timeline_media',[])),included_media=len(bundle.get('media_files',{})))


def read(path,update=lambda *a:None):
    bundle=None
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                names=set(z.namelist())
                if len(names)!=len(z.infolist()):raise ValueError('数据包中有重复文件')
                if len(z.infolist())>100000 or sum(i.file_size for i in z.infolist())>MAX_PACKAGE:raise ValueError('数据包内容过大')
                if z.getinfo('language.json').file_size>MAX_JSON:raise ValueError('语言 JSON 超过 20 GB')
                with z.open('language.json') as source:bundle=streaming_json.read(io.TextIOWrapper(source,encoding='utf-8-sig'),update)
                if set(bundle.get('media_files',{}))-{r['id'] for r in bundle.get('timeline_media',[])}:raise ValueError('数据包包含未声明的媒体')
                for mid,name in bundle.get('media_files',{}).items():
                    if not isinstance(name,str) or name not in names or not name.startswith('media/') or '..' in Path(name).parts:raise ValueError('媒体数据包路径无效')
        else:
            if Path(path).stat().st_size>MAX_JSON:raise ValueError('语言 JSON 超过 20 GB')
            with Path(path).open(encoding='utf-8-sig') as source:bundle=streaming_json.read(source,update)
            if bundle.get('media_files'):raise ValueError('含媒体的交换包须为 .corporium 文件')
        info(bundle);return bundle
    except BaseException:
        if bundle is not None:bundle.close()
        raise


def prepare(db,dbpath,lid,include_media=False,update=lambda *a:None,json_only=False):
    update(None,'正在整理语言及关联数据')
    bundle=export_bundle(db,lid,stream=True);files={}
    if json_only:
        with tempfile.NamedTemporaryFile(suffix='.json',dir=STAGING.name,delete=False) as f:path=Path(f.name)
        try:
            with path.open('wb') as dest:streaming_json.write(bundle,dest,update)
            return dict(token=stage(dbpath,path,'language-json'),size=path.stat().st_size,**info(bundle))
        except BaseException:path.unlink(missing_ok=True);raise
    attached={r['asset_id'] for r in bundle.get('object_media',[])}
    for asset in bundle.get('timeline_media',[]):
        if include_media or asset['id'] in attached or json.loads(asset['metadata']).get('object_media'):
            if asset['storage']!='missing':files[asset['id']]=media_engine.resolve(dbpath,asset)
    bundle['media_files']={mid:'media/'+str(n)+p.suffix for n,(mid,p) in enumerate(files.items())}
    # Exported links must never resolve another user's absolute paths automatically.
    for asset in bundle.get('timeline_media',[]):asset['path']='';asset['storage']='missing'
    f=tempfile.NamedTemporaryFile(suffix='.corporium',dir=STAGING.name,delete=False);path=Path(f.name);f.close()
    try:
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
            record=zipfile.ZipInfo('language.json');record.compress_type=zipfile.ZIP_DEFLATED
            with z.open(record,'w',force_zip64=True) as dest:streaming_json.write(bundle,dest,update)
            for mid,p in files.items():
                update(None,'正在写入媒体：'+p.name)
                with p.open('rb') as src,z.open(bundle['media_files'][mid],'w',force_zip64=True) as dest:
                    while chunk:=src.read(1024*1024):dest.write(chunk);update(None,'正在写入媒体：'+p.name)
        return dict(token=stage(dbpath,path,'export'),size=path.stat().st_size,**info(bundle))
    except BaseException:path.unlink(missing_ok=True);raise


def import_new(db,dbpath,path,name,created):
    from long_tasks import checkpoint
    bundle=read(path,checkpoint)
    try:return _import_new(db,dbpath,path,name,created,bundle)
    finally:bundle.close()

def _import_new(db,dbpath,path,name,created,bundle):
    name=name.strip()
    if not name:raise ValueError('请填写导入后的语言名称')
    if any(r[0].strip().casefold()==name.casefold() for r in db.execute('SELECT name FROM languages')):raise ValueError('已有同名语言，请为导入语言改名')
    meta=bundle['language'].get('metadata','{}');meta=json.loads(meta) if isinstance(meta,str) else meta
    if 'grammar_tags' in bundle:meta={**meta,'glossary':{}}
    lid=languages.save(db,dict(name=name,metadata=meta))['id']
    import journal
    journal.scope.set(lid)
    media={}
    if bundle.get('media_files'):
        root=Path(dbpath).parent/'media';root.mkdir(exist_ok=True)
        with zipfile.ZipFile(path) as z:
            for old,entry in bundle['media_files'].items():
                p=root/(secrets.token_hex(16)+Path(entry).suffix);created.append(p)
                from long_tasks import checkpoint
                with z.open(entry) as src,p.open('xb') as dest:
                    while True:
                        checkpoint(None,'正在准备导入媒体…')
                        chunk=src.read(1024*1024)
                        if not chunk:break
                        dest.write(chunk)
                media[old]=dict(path=str(p.relative_to(Path(dbpath).parent)),fingerprint=media_engine.fingerprint(p))
    result=languages.import_bundle(db,bundle,lid,media_files=media,fresh_references=True)
    return {**result,'language_id':lid}
