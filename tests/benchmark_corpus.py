"""Reproducible synthetic-only benchmarks. Never reads the production database."""

# Shared test baselines: restore only referenced retired inputs, as independent copies.
import pathlib as _fixture_pathlib, sys as _fixture_sys
_fixture_root=next(p for p in _fixture_pathlib.Path(__file__).resolve().parents if (p/'tools/test_materials.py').is_file())
_fixture_sys.path.insert(0,str(_fixture_root/'tools'))
from test_materials import enable_legacy as _enable_legacy_materials
_enable_legacy_materials(__file__)

import argparse,copy,cProfile,hashlib,io,json,platform,pstats,sqlite3,statistics,sys,time,uuid
from pathlib import Path
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server,corpus,lexicon,journal

def uid():return str(uuid.uuid4())
def encode(x):return json.dumps(x,ensure_ascii=False)
class Bench:
    def __init__(self,out):self.out=out;self.results=[]
    def call(self,path,body=None):
        h=object.__new__(server.Handler);h.path=path;payload=encode(body).encode();h.headers={'Content-Type':'application/json','Content-Length':str(len(payload)),'Host':'127.0.0.1:8765'};h.rfile=io.BytesIO(payload);result=[]
        def send(data,code=200,mime='application/json'):
            wire=encode(data).encode() if mime.startswith('application/json') else data
            result.append((code,data,len(wire)))
        h.send=send
        (h.do_GET if body is None else h.do_POST)()
        code,data,size=result[0]
        if code!=200:raise RuntimeError((path,code,data))
        return data,size
    def measure(self,n,name,path,body=None,repeats=1):
        durations=[];sizes=[];queries=[]
        original=server.sqlite3.connect
        class CountConnection(sqlite3.Connection):
            def execute(self,*args,**kw):
                count[0]+=1
                return super().execute(*args,**kw)
        def connect(*a,**kw):return original(*a,**{**kw,'factory':CountConnection})
        for _ in range(repeats):
            count=[0];server.sqlite3.connect=connect
            started=time.perf_counter()
            try:data,size=self.call(path,body)
            finally:server.sqlite3.connect=original
            durations.append(time.perf_counter()-started);sizes.append(size);queries.append(count[0])
        row=dict(sentences=n,operation=name,seconds=durations,median_s=statistics.median(durations),sql_execute_calls=queries,response_bytes=sizes)
        self.results.append(row);self.flush();print(encode(row),flush=True);return data
    def flush(self):
        (self.out/'results.json').write_text(encode(dict(python=sys.version,platform=platform.platform(),results=self.results)),encoding='utf-8')
    def undo(self,n,name):
        state=self.call('/api/undo-state?language=ordos')[0]
        return self.measure(n,name,'/api/undo',dict(generation=state['generation'],_language='ordos'))

def create(path,n):
    if path.exists():raise RuntimeError('Refusing to overwrite '+str(path))
    server.DB=path;server.init()
    # All content is generated here; initialize schema, then bulk-load valid fixtures.
    with server.connect() as db:
        lexemes=[]
        for i in range(max(100,n//10)):
            xid=uid();b=lexicon.normalize(dict(notes=f'合成词条备注 {i}',usages=[dict(pos='N',senses=[dict(short_gloss='家',definition='合成解释')])],variants=[dict(form=f'lemma{i}-n')]))
            lexemes.append((xid,b));db.execute('INSERT INTO lexemes VALUES(?,?,?,?,1)',(xid,'ordos',f'lemma{i}',encode(b)))
        layer=uid();sentence_layer=uid()
        db.execute("INSERT INTO annotation_layers(id,language_id,name,font,style,position,visible,searchable,revision,size,anchor) VALUES(?,'ordos','词类','Junicode','normal',0,1,1,1,100,'word')",(layer,))
        db.execute("INSERT INTO annotation_layers(id,language_id,name,font,style,position,visible,searchable,revision,size,anchor) VALUES(?,'ordos','译注','Junicode','normal',1,1,1,1,100,'translation')",(sentence_layer,))
        texts=[];first=None
        for i in range(n):
            if i%500==0:
                tid=uid();texts.append(tid);db.execute('INSERT INTO texts VALUES(?,?,?,?,?,?,?)',(tid,f'合成文本 {i//500+1}','完全合成，仅作性能测试','','bench-'+str(i),'[]','ordos'))
            marker=i%100<24
            pairs=[('benchold' if marker else 'ger','家'),('bi','我'),('ger-n','家-GEN'),('sain','好'),('morin','马'),('yabu-na','走-PRS'),('tere','那'),('udur','日'),('nigen','一'),('soma','房屋'),('ir-e','来-IMP'),('。','')]
            words=[dict(form=f,gloss=g,form_kind='content',gloss_kind='content') for f,g in pairs]
            if i%10==0:
                words[4]=dict(form='we-amos-la',gloss='pst-go-pst',form_kind='content',gloss_kind='content',morph_groups=[dict(id=uid(),type='circumfix',members=['0:host','2:host'],gloss='PST',status='confirmed',notes='合成环缀',snapshot=dict(form='we-amos-la',gloss='pst-go-pst'))])
            elif i%10==1:words[4].update(form='so<l>ma',gloss='home<PL>')
            words[-1].update(punctuation=True,punctuation_form='。')
            body=dict(function='pass',ipa=f'bi ger sain morin yabu-na {i}',translation=f'这是第 {i+1} 条合成语料。'+('旧术语' if marker else '普通句子'),notes=f'合成调查笔记 编号{i:05d}',words=words,edited=True)
            eid=uid();first=first or eid;db.execute('INSERT INTO entries VALUES(?,?,?,?,1)',(eid,tid,i%500+1,encode(body)))
            analyzed=corpus.analyze(copy.deepcopy(body));unit_rows=[];segments=[];links=[];analyses=[];cells=[]
            for j,w in enumerate(analyzed['words']):
                wid=uid();unit_rows.append((wid,eid,'word',None,j,w['form'],w['gloss'],1,1))
                mids=[]
                for k,m in enumerate(w['morphemes']):
                    mid=uid();mids.append(mid);unit_rows.append((mid,eid,'morpheme',wid,k,m['form'],m['gloss'],1,1));segments.append((mid,encode({**m,'snapshot':{k:w[k] for k in ('form','gloss')}})))
                if j in (0,4,7):
                    xid,b=lexemes[(i+j)%len(lexemes)];lid=uid();links.append((lid,(mids[0] if j==4 and mids else wid),xid,b['usages'][0]['id'],b['usages'][0]['senses'][0]['id'],'合成关联','ordos',1));analyses.append((lid,None,'[]'))
                if j in (0,4):cells.append((uid(),'corpus',eid,wid,layer,'NOUN',1))
            cells.append((uid(),'corpus',eid,'@sentence',sentence_layer,'合成附加翻译',1))
            db.executemany('INSERT INTO corpus_units VALUES(?,?,?,?,?,?,?,?,?)',unit_rows);db.executemany('INSERT INTO unit_segments VALUES(?,?)',segments);db.executemany('INSERT INTO lexical_links VALUES(?,?,?,?,?,?,?,?)',links);db.executemany('INSERT INTO morphology_analyses VALUES(?,?,?)',analyses);db.executemany('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,?)',cells)
        lexicon.validate_links(db)
        counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('entries','corpus_units','lexemes','lexical_links','annotation_cells')}
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    print(encode(dict(seed=n,counts=counts,db_mib=path.stat().st_size/1048576)),flush=True)
    return first,texts,counts

def run(out,sizes,source=None):
    b=Bench(out)
    for n in sizes:
        path=out/f'synthetic-{n}.sqlite3'
        if source:
            print('COPY '+str(n),flush=True)
            fixture=json.loads((source/f'fixture-{n}.json').read_text(encoding='utf-8'))
            with sqlite3.connect((source/path.name).as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(path) as dst:src.backup(dst)
            server.DB=path;server.init()
            eid,texts,counts=fixture['eid'],fixture['texts'],fixture['counts']
        else:
            print('GENERATE '+str(n),flush=True);eid,texts,counts=create(path,n)
        (out/f'fixture-{n}.json').write_text(encode(dict(eid=eid,texts=texts,counts=counts,db_mib=path.stat().st_size/1048576)),encoding='utf-8')
        b.measure(n,'首页汇总','/api/home',repeats=3)
        b.measure(n,'文本列表','/api/texts?language=ordos',repeats=3)
        b.measure(n,'当前文本第一页','/api/entries?'+urlencode(dict(text=texts[0],language='ordos',page=1,page_size=20)),repeats=3)
        b.measure(n,'全部语料第一页','/api/entries?language=ordos&page=1&page_size=20',repeats=3)
        b.measure(n,'全部语料末页','/api/entries?'+urlencode(dict(language='ordos',page=n//20,page_size=20)),repeats=3)
        for field,q in [('all','benchold'),('notes','编号00042'),('gloss','GEN')]:
            r=b.measure(n,'搜索-'+field,'/api/entries?'+urlencode(dict(language='ordos',field=field,q=q,page_size=20)),repeats=3);assert r['total']==(int(n*.24) if field=='all' else 1 if field=='notes' else n)
        b.measure(n,'词典搜索','/api/lexemes?language=ordos&q=lemma42',repeats=3)
        d=b.measure(n,'打开单句编辑','/api/annotations?kind=corpus&id='+eid,repeats=3)
        payload=dict(kind='corpus',id=eid,revision=d['revision'],before=d['cells'],layers=d['layers'],cells=d['cells'],body=copy.deepcopy(d['body']),slot_ids=[w['id'] for w in d['words']])
        payload['body']['notes']+=' 修改'
        b.measure(n,'保存单句备注','/api/inline-save',payload);b.undo(n,'撤销单句保存')
        for field,find,replacement in [('translation','旧术语','新术语'),('form','benchold','benchnew')]:
            request=dict(field=field,find=find,replacement=replacement,text_id='',_language='ordos')
            p=b.measure(n,field+'替换预览','/api/text-replace-preview',request)
            assert len(p['changes'])==int(n*.24) and not p['conflicts'] and not p['blocked']
            r=b.measure(n,field+'替换应用','/api/text-replace-apply',{**request,'token':p['token'],'keys':[c['key'] for c in p['changes']]});assert r['replacements']==int(n*.24)
            b.measure(n,field+'替换后刷新','/api/entries?language=ordos&page_size=20')
            b.measure(n,field+'替换后重新预览','/api/text-replace-preview',request)
            b.undo(n,field+'撤销批量替换')
        with server.connect() as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            for table,count in counts.items():assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==count
            assert 'benchold' in json.loads(db.execute('SELECT body FROM entries WHERE id=?',(eid,)).fetchone()[0])['words'][0]['form']
        if n==1000:
            request=dict(field='form',find='benchold',replacement='benchnew',text_id='',_language='ordos');p=b.call('/api/text-replace-preview',request)[0]
            profile=cProfile.Profile();profile.enable();b.call('/api/text-replace-apply',{**request,'token':p['token'],'keys':[c['key'] for c in p['changes']]});profile.disable();profile.dump_stats(str(out/'replace-1000.prof'))
            with (out/'replace-1000-profile.txt').open('w',encoding='utf-8') as f:pstats.Stats(profile,stream=f).strip_dirs().sort_stats('cumulative').print_stats(40)
            b.undo(n,'分析运行后撤销')
        print('DONE '+str(n),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--sizes',nargs='+',type=int,default=[1000,5000,10000]);parser.add_argument('--source',help='Existing synthetic benchmark directory under build (copied read-only)');a=parser.parse_args()
    out=Path(a.output).resolve();allowed=(ROOT/'build').resolve()
    if allowed not in out.parents:raise SystemExit('Output must be under project build/')
    source=Path(a.source).resolve() if a.source else None
    if source and allowed not in source.parents:raise SystemExit('Source must be a synthetic benchmark directory under project build/')
    out.mkdir(parents=True,exist_ok=False);run(out,a.sizes,source)
