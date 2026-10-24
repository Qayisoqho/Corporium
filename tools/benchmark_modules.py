"""Cross-module synthetic performance lab. Output confined to build/; generated media only."""
import sys,os,json,time,sqlite3,statistics,subprocess,ctypes,threading,platform,traceback,argparse,copy
from pathlib import Path
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]
temp=ROOT/'build/test-materials-runs/tmp';temp.mkdir(parents=True,exist_ok=True)
os.environ['TEMP']=os.environ['TMP']=str(temp)
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from benchmark_corpus import Bench,create,uid,encode
import server,lexicon,corpus,grammar,grammar_survey,morpheme_registry,component_links,timeline,media_engine,synonyms

def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
def memory():
 class Counters(ctypes.Structure):
  _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(n,ctypes.c_size_t) for n in ('peak','rss','pp','p','np','n','page','peakpage')]
 c=Counters();c.cb=ctypes.sizeof(c)
 ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
 ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
 ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(c),c.cb)
 return dict(rss_mib=c.rss/1048576,peak_mib=c.peak/1048576)
def size(p):return sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
def fixture(out,n):
 path=out/f'synthetic-{n}.sqlite3';eid,texts,counts=create(path,n)
 with server.connect(audit=False) as db:
  lex=list(db.execute('SELECT * FROM lexemes'));entries=list(db.execute('SELECT id,body FROM entries'));mids=[]
  for i,r in enumerate(lex):
   body=json.loads(r['body']);form='m'+str(i);reading=('m','p','t','k')[i%4]+('a','i','u','ai')[i//4%4]+('55','21','35','51')[i//16%4]
   body['word_structure']={'analyses':[{'id':'a','title':'合成共时分析','components':[{'id':'c','form':form,'gloss':'合成义'+str(i%30),'readings':[reading]}]}]}
   body=lexicon.normalize(body);db.execute('UPDATE lexemes SET body=? WHERE id=?',(encode(body),r['id']))
   mid=uid();mids.append(mid);mb=dict(gloss='合成义'+str(i%30),readings=[reading],writings=[],features=[],senses=[],notes='性能测试语素')
   db.execute('INSERT INTO morphemes VALUES(?,?,?,?,?,1)',(mid,'ordos',form,1,encode(mb)))
   ref=component_links.choose(body,dict(analysis_id='a',component_id='c'))
   db.execute('INSERT INTO morpheme_components VALUES(?,?,?,?,?,?,1)',(uid(),r['id'],'a','c',mid,encode(ref)))
   if i and i%2:
    synonyms.mutate(db,'ordos',dict(source=dict(kind='morpheme',id=mids[-2],sense='@main'),target=dict(kind='morpheme',id=mid,sense='@main')))
  for i in range(max(100,n//10)):
   body=json.loads(entries[i%len(entries)]['body']);body.update(language_id='ordos',targets=[],source='合成独立例句')
   db.execute('INSERT INTO dictionary_examples(id,language_id,body,revision) VALUES(?,?,?,1)',(uid(),'ordos',encode(body)))
  survey=[]
  for i in range(max(100,n//25)):
   parent=None if i%20==0 else survey[i-i%20];kind='section' if i%20==0 else 'question'
   node=grammar_survey.insert_node(db,'ordos',parent,kind,'合成调查 '+str(i),grammar_survey.clean_body(db,{},'ordos'));survey.append(node)
   if kind=='question':
    db.execute('INSERT INTO survey_evidence VALUES(?,?,?,?,?,?,?,1)',(uid(),'ordos',node,'corpus',entries[i%len(entries)]['id'],0,encode(grammar_survey.clean_body(db,{},'ordos',True))))
  # A deterministic generated waveform replaces all private recordings.
  import wave,struct,math
  media=ROOT/'build/test-materials-runs/media';media.mkdir(parents=True,exist_ok=True)
  file=media/'synthetic-tone.wav'
  if not file.exists():
   with wave.open(str(file),'wb') as wav:
    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000)
    wav.writeframes(b''.join(struct.pack('<h',int(1000*math.sin(2*math.pi*220*i/8000))) for i in range(32000)))
  meta=media_engine.probe(file)
  asset=dict(name=file.name,path=str(file.resolve()),storage='link',metadata=meta)
  sid=timeline.mutate(db,'ordos','create',{'name':'合成音频会话'},asset)['id']
  assets=[dict(session=sid,**asset)]
  sid=assets[0]['session'];tracks=[db.execute('SELECT id FROM timeline_tracks WHERE session_id=?',(sid,)).fetchone()[0]]
  for i in range(1,8):
   tid=uid();tracks.append(tid);db.execute('INSERT INTO timeline_tracks(id,session_id,name,kind,position) VALUES(?,?,?,?,?)',(tid,sid,'合成轨道'+str(i),'sentence',i))
  intervals=[]
  for i,e in enumerate(entries):
   iid=uid();intervals.append(iid);start=(i//8)*4000
   db.execute('INSERT INTO timeline_intervals(id,session_id,track_id,entry_id,start_ms,end_ms) VALUES(?,?,?,?,?,?)',(iid,sid,tracks[i%8],e['id'],start,start+3500))
  for tag in ('GEN','PRS','PST','PL','IMP') :grammar.mutate(db,'grammar-save',dict(symbol=tag,description='合成标签'),'ordos')
  lexicon.validate_links(db);grammar_survey.validate(db)
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['texts','entries','corpus_units','lexemes','lexical_links','dictionary_examples','morphemes','morpheme_components','synonym_links','survey_nodes','survey_evidence','timeline_intervals','timeline_media','annotation_cells']}
 f=dict(n=n,eid=eid,texts=texts,lexeme=lex[0]['id'],morpheme=mids[0],survey=survey[1],session=sid,interval=intervals[0],assets=assets,counts=counts)
 dump(out/f'fixture-{n}.json',f);print('FIXTURE '+encode(counts),flush=True)

def operation(out,n,name):
 def resource_guard():
  while True:
   info=memory()
   if info['rss_mib']>1536:
    row=dict(n=n,operation=name,status='resource_limit',limit_mib=1536,**info)
    dump(out/f'{n}-{name}.json',row);print(encode(row),flush=True);os._exit(75)
   time.sleep(.25)
 threading.Thread(target=resource_guard,daemon=True).start()
 server.DB=out/f'synthetic-{n}.sqlite3';f=json.loads((out/f'fixture-{n}.json').read_text(encoding='utf8'));b=Bench(out)
 def api(path,body=None):return b.call(path,body)[0]
 def url(path,**q):return path+'?'+urlencode(dict(language='ordos',**q))
 routes={'full_backup':'/api/backup','home':'/api/home','texts':url('/api/texts'),'entries':url('/api/entries',page_size=20),'deep_page':url('/api/entries',page=n//20,page_size=20),'search':url('/api/entries',q='GEN',field='gloss'),'dictionary':url('/api/lexemes',q='lemma42'),'dictionary_detail':url('/api/lexeme',id=f['lexeme']),'dictionary_evidence':url('/api/lexeme-examples',id=f['lexeme']),'morphemes':url('/api/morphemes',q='合成义'),'morpheme_detail':url('/api/morpheme',id=f['morpheme']),'homophones':url('/api/homophones'),'phonology':url('/api/homophone-phonology'),'synonyms':url('/api/synonyms',kind='morpheme',id=f['morpheme']),'survey':url('/api/survey'),'survey_detail':url('/api/survey-detail',id=f['survey']),'library':url('/api/example-library'),'grammar_audit':url('/api/grammar-audit',lower='true'),'classes':url('/api/classes'),'collaborators':url('/api/collaborators'),'timeline':url('/api/timeline-detail',id=f['session'],start=0,end=60000),'timeline_seek':url('/api/timeline-detail',id=f['session'],start=n//16*4000,end=n//16*4000+60000),'timeline_complete':url('/api/timeline-detail',id=f['session'],complete=1),'segmentation':url('/api/segmentation',kind='corpus',id=f['eid']),'typst_export':url('/api/export',id=f['texts'][0]),'language_export':url('/api/export-language'),'auto_match':url('/api/lexeme-auto-preview')}
 def work():
  if name in routes:return api(routes[name])
  if name in ('analysis','counts'):
   q={'kind':'counts'} if name=='counts' else {'conditions':[{'field':'morpheme','value':'n','mode':'exact'},{'field':'tag','value':'GEN','relation':'same_word'}]}
   r=api('/api/analysis-run',{'query':q,'_language':'ordos'});api(url('/api/analysis-result',id=r['id']));return r
  if name=='edit_check_undo':
   e=api(url('/api/entries',text=f['texts'][0]))['items'][0];original=e['notes']
   api('/api/save',{**e,'notes':original+' 性能协作编辑','_language':'ordos'})
   api(url('/api/segmentation',kind='corpus',id=e['id']));api(url('/api/lexeme-examples',id=f['lexeme']));api(url('/api/survey-detail',id=f['survey']));api(routes['timeline'])
   st=api(url('/api/undo-state'));api('/api/undo',{'generation':st['generation'],'_language':'ordos'})
   with server.connect(audit=False) as db:assert json.loads(db.execute('SELECT body FROM entries WHERE id=?',(e['id'],)).fetchone()[0])['notes']==original
   return {'verified':'edit, segmentation, dictionary, survey, timeline, undo'}
  if name=='replace_undo':
   req=dict(field='translation',find='旧术语',replacement='新术语',text_id=f['texts'][0],_language='ordos');p=api('/api/text-replace-preview',req)
   r=api('/api/text-replace-apply',{**req,'token':p['token'],'keys':[c['key'] for c in p['changes']]});st=api(url('/api/undo-state'));api('/api/undo',{'generation':st['generation'],'_language':'ordos'});assert r['replacements']==120;return r
  if name=='backup':
   with server.connect(audit=False) as db:
    dest=sqlite3.connect(out/f'backup-{n}.sqlite3');db.backup(dest);ok=dest.execute('PRAGMA integrity_check').fetchone()[0];dest.close();assert ok=='ok'
   return {'verified':'SQLite backup + integrity_check'}
  raise ValueError(name)
 samples=[];result=None
 for i in range(3 if name not in ('edit_check_undo','replace_undo','backup','full_backup','language_export','timeline_complete') else 1):
  start=time.perf_counter();result=work();elapsed=time.perf_counter()-start;samples.append(elapsed)
  print(encode(dict(operation=name,repeat=i,seconds=elapsed,**memory())),flush=True)
  if elapsed>30:break  # Keep slow-operation diagnosis bounded; report the available single sample honestly.
 row=dict(n=n,operation=name,seconds=samples,first_s=samples[0],warm_median_s=statistics.median(samples[1:]) if len(samples)>1 else None,max_s=max(samples),**memory())
 if isinstance(result,dict):row['response_summary']={k:result[k] for k in ('total','count','cached','summary','verified') if k in result};row['response_bytes']=len(encode(result).encode())
 dump(out/f'{n}-{name}.json',row)

def run(out,sizes):
 out.mkdir(parents=True,exist_ok=True);dump(out/'environment.json',dict(platform=platform.platform(),python=sys.version,cpu_count=os.cpu_count(),sizes=sizes,method='Fresh process per operation, first application-cold (OS file cache NOT flushed), then 2 warm repetitions. In-process real HTTP handler, includes JSON serialization but excludes socket/render latency.',media_policy='generated synthetic waveform only; no private recordings'))
 results=[]
 def child(n,op,timeout):
  log=out/f'{n}-{op}.log';start=time.perf_counter()
  with log.open('w',encoding='utf8') as stream:
   p=subprocess.Popen([sys.executable,__file__,'--output',str(out),'--size',str(n),'--worker',op],stdout=stream,stderr=subprocess.STDOUT)
   try:rc=p.wait(timeout=timeout);status='ok' if rc==0 else 'error'
   except subprocess.TimeoutExpired:p.kill();p.wait();status='timeout'
  result=dict(n=n,operation=op,status=status,wall_s=time.perf_counter()-start)
  if (out/f'{n}-{op}.json').exists():result.update(json.loads((out/f'{n}-{op}.json').read_text(encoding='utf8')))
  if status!='ok':result['log_tail']=log.read_text(encoding='utf8')[-1800:]
  results.append(result);dump(out/'results.json',results);print(encode(result),flush=True);return status
 operations=['home','texts','entries','deep_page','search','dictionary','dictionary_detail','dictionary_evidence','morphemes','morpheme_detail','homophones','phonology','synonyms','survey','survey_detail','library','grammar_audit','classes','collaborators','timeline','timeline_seek','timeline_complete','segmentation','analysis','counts','auto_match','edit_check_undo','replace_undo','typst_export','language_export','backup']
 for n in sizes:
  if not (out/f'fixture-{n}.json').exists() and child(n,'seed',900)!='ok':continue
  for op in operations:child(n,op,120)
  dump(out/f'disk-{n}.json',dict(total_bytes=size(out),database_bytes=(out/f'synthetic-{n}.sqlite3').stat().st_size))
 print('ALL DONE',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--sizes',nargs='+',type=int,default=[1000,10000,50000]);p.add_argument('--size',type=int);p.add_argument('--worker');a=p.parse_args();out=Path(a.output).resolve()
 if not out.is_relative_to(ROOT/'build'):raise SystemExit('Output must be under build/')
 if a.worker=='seed':fixture(out,a.size)
 elif a.worker:operation(out,a.size,a.worker)
 else:run(out,a.sizes)
