"""Project-scoped, bounded work queue with atomic cancellable writes."""
import contextvars
import json
import secrets
import sqlite3
import threading
import time
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CURRENT=contextvars.ContextVar('corporium_long_task',default=None)
LOCK=threading.RLock()
POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='corporium-long-task')
JOBS={}
KINDS={'dictionary','auto-match','timeline','language-package','language-json','language-preview','backup'}
KINDS.update({'operation','grammar-audit','statistics','analysis-result','analysis-export','homophones'})
ACTIVE=('queued','running','committing')
MEMORY_LIMIT=1536*1024**2

def working_set():
    if os.name!='nt':return None
    import ctypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(n,ctypes.c_size_t) for n in ('peak','rss','pp','p','np','n','page','peakpage')]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    kernel=ctypes.windll.kernel32;psapi=ctypes.windll.psapi
    kernel.GetCurrentProcess.restype=ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
    if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):return counters.rss

class Cancelled(Exception):pass

def checkpoint(progress=None,message=None):
    job=CURRENT.get()
    if job is None:return
    if job['cancel'].is_set():raise Cancelled('任务已取消，未修改原数据')
    with LOCK:
        if message is not None:job['message']=message
        job['progress']=progress

def steps(iterable):
    """Bound cancellation latency in Python loops without checking every element."""
    if CURRENT.get() is None:
        yield from iterable
        return
    for index,item in enumerate(iterable):
        if index%64==0:checkpoint()
        yield item
    checkpoint()

def committing(db):
    """Linearize cancel vs commit. No cancellation is accepted after this gate."""
    job=CURRENT.get()
    if job is None:return
    with LOCK:
        checkpoint(None,'正在提交最终结果…')
        job['state']='committing'
        db.set_progress_handler(None,0)

def active(project):
    project=str(Path(project).resolve())
    with LOCK:return any(j['project']==project and j['state'] in ACTIVE for j in JOBS.values())

def cancel_all():
    """Release pending work when the desktop process closes."""
    with LOCK:
        for job in list(JOBS.values()):
            if job['state'] in ('queued','running'):cancel(job['project'],job['id'])

def view(project,jid):
    with LOCK:
        j=JOBS.get(jid)
        if not j or j['project']!=str(Path(project).resolve()):raise ValueError('任务已过期或不属于当前项目')
        return {k:v for k,v in j.items() if k not in ('project','cancel','request','future','resource_error','staged','created','backup_folders')}

def cancel(project,jid):
    view(project,jid)
    with LOCK:
        j=JOBS[jid]
        if j['state'] in ('queued','running'):
            j['cancel'].set();j['message']='正在取消并清理临时文件…'
            if j['state']=='queued' and j['future'].cancel():
                j.update(state='cancelled',finished=time.time(),message='任务已取消，未修改原数据')
    return view(project,jid)

def submit(project,kind,request):
    project=str(Path(project).resolve())
    if kind not in KINDS:raise ValueError('不支持的后台任务')
    with LOCK:
        now=time.time()
        for key,j in list(JOBS.items()):
            if j['state'] not in ACTIVE and now-j['finished']>60:del JOBS[key]
        if sum(j['state'] in ACTIVE for j in JOBS.values())>=4:raise ValueError('已有多个任务等待处理，请等待或取消任务')
        jid=secrets.token_urlsafe(24)
        job=dict(id=jid,project=project,kind=kind,request=request,state='queued',message='等待前一个任务完成',progress=None,cancel=threading.Event(),finished=0)
        JOBS[jid]=job
        job['future']=POOL.submit(run,job)
    return jid

def run(job):
    token=CURRENT.set(job);db=None;stopped=threading.Event();audit_observer=None;audit_token=None
    def monitor():
        while not stopped.wait(.25):
            try:memory=working_set()
            except (OSError,AttributeError):memory=None
            if memory and memory>MEMORY_LIMIT:
                with LOCK:
                    if job['state']=='committing':return
                    job['resource_error']='内存使用达到保护上限，任务已停止且未修改原数据。请缩小处理范围或分批导入；整库备份请使用 SQLite 备份包。'
                    job['cancel'].set()
                return
    watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
    try:
        checkpoint(None,'正在准备任务…')
        with LOCK:job['state']='running'
        if job['kind']=='operation':
            import task_operations
            result=task_operations.run(job)
            with LOCK:job.update(state='done',progress=100,message='已完成',result=result)
            return
        db=sqlite3.connect(Path(job['project']).as_uri()+'?mode=ro',uri=True)
        db.row_factory=sqlite3.Row
        if job['kind']=='grammar-audit':
            import grammar_audit_cache
            audit_observer=grammar_audit_cache.Snapshot(db)
            audit_token=grammar_audit_cache.CURRENT.set(audit_observer)
        db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-8192')
        db.set_progress_handler(lambda:int(job['cancel'].is_set()),5000)
        db.execute('BEGIN')
        r=job['request'];lid=r.get('language','ordos');kind=job['kind']
        import languages,lexicon,timeline,language_exchange,project_backup
        if lid!='all':languages.require(db,lid)
        if kind=='dictionary':
            checkpoint(None,'正在检索词条和关联例证…')
            result=lexicon.list_lexemes(db,r.get('lexical_language',lid),r.get('q',''),r.get('page',1),r.get('page_size',30),category=r.get('semantic_class',''),order=r.get('sort_order',''),search=r.get('search'),summary=r.get('summary')=='1',targets=r.get('targets')=='all',counts=r.get('counts')!='0')
        elif kind=='auto-match':
            checkpoint(None,'正在逐句匹配词典…')
            result=lexicon.auto_link_plan(db,lid,r.get('text_id',''),r.get('ignore_symbols','-=.'),r.get('ignore_position','edges'))
        elif kind=='timeline':
            checkpoint(None,'正在读取时间轴区间…');result=timeline.detail(db,lid,r)
        elif kind=='grammar-audit':
            import grammar
            checkpoint(None,'正在检查句子、语素与词典关联…');result=grammar.audit(db,r)
        elif kind=='statistics':
            import corpus_statistics
            checkpoint(None,'正在统计词数与句数…');result=corpus_statistics.calculate(db,lid,corpus_statistics.normalize(r.get('scope',{})))
        elif kind=='analysis-result':
            import analysis_workspace
            checkpoint(None,'正在整理分析结果…');result=analysis_workspace.result_page(db,lid,r)
        elif kind=='analysis-export':
            import analysis_workspace
            checkpoint(None,'正在导出完整分析…');result=analysis_workspace.export_file(db,job['project'],lid,r)
        elif kind=='homophones':
            import homophones
            checkpoint(None,'正在整理同音语素表…');result=homophones.table(db,lid,r)
        elif kind=='backup':result=project_backup.prepare(db,job['project'],r.get('include_media') is True,checkpoint)
        elif kind=='language-preview':
            path=language_exchange.staged(job['project'],r.get('token'),'import')
            bundle=language_exchange.read(path,checkpoint)
            try:result=dict(language_exchange.info(bundle),token=r['token'])
            finally:bundle.close()
        else:result=language_exchange.prepare(db,Path(job['project']),lid,r.get('include_media') is True,checkpoint,json_only=kind=='language-json')
        # Keep a completed staged file usable; read results still respect cancellation.
        if kind not in ('backup','language-package','language-json','analysis-export'):checkpoint()
        with LOCK:job.update(state='done',progress=100,message='已完成',result=result)
    except Exception as error:
        with LOCK:
            resource_error=job.get('resource_error')
            cancelled=not resource_error and (isinstance(error,Cancelled) or job['cancel'].is_set())
            job.update(state='cancelled' if cancelled else 'error',message=resource_error or ('任务已取消，未修改原数据' if cancelled else str(error)))
    finally:
        stopped.set();watcher.join()
        if audit_token is not None:
            grammar_audit_cache.CURRENT.reset(audit_token)
            audit_observer.close()
        if db is not None:db.close()
        with LOCK:job['finished']=time.time()
        def expire():
            with LOCK:JOBS.pop(job['id'],None)
        timer=threading.Timer(60,expire);timer.daemon=True;timer.start()
        CURRENT.reset(token)
