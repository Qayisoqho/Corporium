"""Local media preparation. Workers capture project paths; they never touch a corpus DB."""
import hashlib
import heapq
import json
import mimetypes
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='corporium-media')
JOBS={};GUARD=threading.Lock()
EXTENSIONS={'.wav','.mp3','.flac','.m4a','.mp4','.mov','.mkv','.avi','.ogg','.opus','.webm','.aac','.wma','.wmv','.aif','.aiff','.m4v','.3gp'}

def dependencies():
    try:import av;import numpy as np
    except ImportError:raise ValueError('媒体组件未安装，请安装开发依赖 av 和 numpy 后重启 Corporium')
    return av,np

def fingerprint(path):
    stat=path.stat()
    return {'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}

def probe(path):
    av,_=dependencies()
    with av.open(str(path)) as c:
        streams=[s for s in c.streams if s.type in ('audio','video') and not s.disposition & av.stream.Disposition.attached_pic]
        if not streams:raise ValueError('文件没有可用音视频流')
        duration=round((c.duration or 0)/av.time_base*1000)
        if duration<=0:raise ValueError('无法确定媒体时长，请使用具有完整时间索引的文件')
        return dict(duration_ms=duration,start_us=c.start_time or 0,fingerprint=fingerprint(path),streams=[dict(type=s.type,codec=s.codec_context.name,index=s.index,channels=getattr(s.codec_context,'channels',None),width=getattr(s.codec_context,'width',None),height=getattr(s.codec_context,'height',None)) for s in streams])

def cache_root(dbpath):
    root=Path(dbpath).parent/'media-cache';root.mkdir(parents=True,exist_ok=True);return root

def resolve(dbpath,asset):
    if asset['storage']=='missing' or not asset['path']:raise ValueError('媒体尚未定位，请使用换源选择媒体文件')
    path=Path(asset['path'])
    if asset['storage']=='copy':
        root=(Path(dbpath).parent/'media').resolve();path=(Path(dbpath).parent/path).resolve()
        if not path.is_relative_to(root):raise ValueError('项目媒体路径无效')
    if not path.is_file():raise ValueError('媒体文件已移动或不存在，请使用换源重新定位')
    meta=asset['metadata'] if isinstance(asset['metadata'],dict) else json.loads(asset['metadata'])
    if fingerprint(path)!=meta['fingerprint']:raise ValueError('媒体文件已被外部修改，请使用换源重新确认对齐')
    return path

def cache_key(asset):
    return hashlib.sha256(json.dumps([asset['path'],asset['metadata']],sort_keys=True).encode()).hexdigest()

def job_view(dbpath,jid):
    with GUARD:
        j=JOBS.get(jid)
        if not j or j['project']!=str(Path(dbpath).resolve()):raise ValueError('媒体任务已失效，请重新操作')
        return {k:v for k,v in j.items() if k not in ('project','cancel','key')}

def submit(dbpath,key,work):
    project=str(Path(dbpath).resolve())
    with GUARD:
        for j in JOBS.values():
            if j['project']==project and j['key']==key and j['state'] in ('queued','running','done'):return j['id']
        # Cache tasks are cheap to reconstruct; do not retain unbounded task history.
        completed=[k for k,v in JOBS.items() if v['state'] not in ('queued','running')]
        for k in completed[:-60]:JOBS.pop(k,None)
        jid=str(uuid.uuid4());j=dict(id=jid,project=project,key=key,state='queued',progress=0,message='等待处理',cancel=False);JOBS[jid]=j
    def update(progress,message):
        if j['cancel']:raise ValueError('任务已取消')
        j.update(progress=max(0,min(100,progress)),message=message)
    def run():
        j['state']='running'
        try:j.update(result=work(update),state='done',progress=100,message='已完成')
        except Exception as e:j.update(state='error',message=str(e))
    POOL.submit(run);return jid

def cancel(dbpath,jid):
    job_view(dbpath,jid)
    with GUARD:JOBS[jid]['cancel']=True
    return {'ok':True}

def imported(dbpath,jid):
    j=job_view(dbpath,jid)
    if j['state']!='done' or not isinstance(j.get('result'),dict) or 'storage' not in j['result']:raise ValueError('请等待媒体导入完成')
    resolve(dbpath,j['result']);return j['result']

def import_media(dbpath,b):
    path=Path(str(b.get('path','')).strip().strip('"')).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in EXTENSIONS:raise ValueError('请选择可用的本地音视频文件')
    storage=b.get('storage','link')
    if storage not in ('link','copy'):raise ValueError('请选择复制进项目或链接原位置')
    before=fingerprint(path)
    def work(update):
        update(1,'检查媒体编码');meta=probe(path);target=path
        if storage=='copy':
            root=Path(dbpath).parent/'media';root.mkdir(parents=True,exist_ok=True)
            target=root/(str(uuid.uuid4())+path.suffix.lower());partial=target.with_suffix(target.suffix+'.partial')
            try:
                with path.open('rb') as source,partial.open('xb') as dest:
                    done=0
                    while chunk:=source.read(4*1024*1024):
                        dest.write(chunk);done+=len(chunk);update(done/max(1,before['size'])*95,'复制媒体进项目')
                if fingerprint(path)!=before:raise ValueError('复制时源文件已改变，请重试')
                partial.replace(target)
            finally:
                if partial.exists():partial.unlink()
            meta['fingerprint']=fingerprint(target)
        elif fingerprint(path)!=before:raise ValueError('检查时源文件已改变，请重试')
        return dict(name=path.name,path=str(target.relative_to(Path(dbpath).parent)) if storage=='copy' else str(target),storage=storage,metadata=meta)
    return {'job':submit(dbpath,'import:'+str(uuid.uuid4()),work)}

def prepare(dbpath,asset,kind):
    if kind not in ('wave','proxy'):raise ValueError('无效媒体任务')
    path=resolve(dbpath,asset);key=cache_key(asset);root=cache_root(dbpath)
    if kind=='wave':
        import waveform_cache
        target=waveform_cache.overview_path(dbpath,key)/'manifest.json'
    else:target=root/(key+'.mp4')
    if not target.exists():
        with GUARD:
            for jid,j in list(JOBS.items()):
                if j['project']==str(Path(dbpath).resolve()) and j['key']==kind+':'+key and j['state']=='done':JOBS.pop(jid)
    def work(update):
        if target.exists():return {'ready':True}
        if kind=='wave':
            waveform_cache.build(dbpath,key,path,asset['metadata'],update)
            resolve(dbpath,asset)
            waveform_cache.retire_legacy(dbpath,key)
            return {'ready':True}
        temp=target.with_suffix(target.suffix+'.partial')
        try:
            proxy(path,temp,asset['metadata'],update)
            resolve(dbpath,asset);temp.replace(target)
        finally:
            if temp.exists():temp.unlink()
        return {'ready':True}
    return {'job':submit(dbpath,kind+':'+key,work),'ready':target.exists()}

def wave_data(dbpath,asset,start,end,pixels=1200,compact=False):
    import waveform_cache
    source=resolve(dbpath,asset)
    result=waveform_cache.data(dbpath,cache_key(asset),source,asset['metadata'],start,end,pixels,compact)
    resolve(dbpath,asset)
    return result


def proxy(path,target,meta,update):
    av,_=dependencies()
    with av.open(str(path)) as source,av.open(str(target),'w',format='mp4',options={'movflags':'+faststart'}) as dest:
        vin=next((s for s in source.streams if s.type=='video' and not s.disposition & av.stream.Disposition.attached_pic),None)
        ain=next((s for s in source.streams if s.type=='audio'),None)
        if vin:
            video=dest.add_stream('libx264',rate=vin.average_rate or 25)
            scale=min(1,1280/max(vin.width,vin.height));video.width=max(2,round(vin.width*scale/2)*2);video.height=max(2,round(vin.height*scale/2)*2)
            video.pix_fmt='yuv420p';video.options={'preset':'veryfast','crf':'23'};video.codec_context.time_base=Fraction(1,90000)
        if ain:
            audio=dest.add_stream('aac',rate=48000);audio.layout='stereo';resampler=av.AudioResampler(format='fltp',layout='stereo',rate=48000)
        pending=[];serial=0;last=-1;origin=meta['start_us']/av.time_base
        def emit_video():
            nonlocal last
            _,_,frame=heapq.heappop(pending)
            if frame.pts<=last:return
            last=frame.pts
            for p in video.encode(frame):dest.mux(p)
        for packet in source.demux(*[s for s in (vin,ain) if s]):
            for frame in packet.decode():
                if frame.time is None:continue
                seconds=frame.time-origin;update(seconds*100000/max(1,meta['duration_ms']),'生成兼容播放副本')
                if packet.stream.type=='video':
                    frame=frame.reformat(width=video.width,height=video.height,format='yuv420p');frame.pts=round(seconds*90000);frame.time_base=Fraction(1,90000)
                    serial+=1;heapq.heappush(pending,(frame.pts,serial,frame))
                    if len(pending)>32:emit_video()
                else:
                    for converted in resampler.resample(frame):
                        converted.pts-=round(origin/converted.time_base)
                        for p in audio.encode(converted):dest.mux(p)
        if vin:
            while pending:emit_video()
            for p in video.encode(None):dest.mux(p)
        if ain:
            for converted in resampler.resample(None):
                converted.pts-=round(origin/converted.time_base)
                for p in audio.encode(converted):dest.mux(p)
            for p in audio.encode(None):dest.mux(p)

def playable(dbpath,asset,use_proxy=False):
    if asset['metadata'].get('kind')=='audio' and asset['metadata'].get('object_media'):
        import object_media
        return object_media.audio_playable(dbpath,asset)
    path=resolve(dbpath,asset)
    if use_proxy:
        path=cache_root(dbpath)/(cache_key(asset)+'.mp4')
        if not path.is_file():raise ValueError('兼容副本尚未生成')
    return path

def stream_file(handler,path):
    import re
    size=path.stat().st_size;start=0;end=size-1;requested=handler.headers.get('Range')
    if requested:
        m=re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
        if not m or not any(m.groups()):handler.send_error(416);return
        if m[1]:start=int(m[1]);end=min(end,int(m[2])) if m[2] else end
        else:start=max(0,size-int(m[2]))
        if start>end or start>=size:
            handler.send_response(416);handler.send_header('Content-Range',f'bytes */{size}');handler.end_headers();return
    handler.send_response(206 if requested else 200);handler.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream');handler.send_header('Content-Length',str(end-start+1));handler.send_header('Accept-Ranges','bytes');handler.send_header('Cache-Control','private, no-store')
    if requested:handler.send_header('Content-Range',f'bytes {start}-{end}/{size}')
    handler.end_headers()
    try:
        with path.open('rb') as f:
            f.seek(start);remaining=end-start+1
            while remaining:
                chunk=f.read(min(262144,remaining))
                if not chunk:break
                handler.wfile.write(chunk);remaining-=len(chunk)
    except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
