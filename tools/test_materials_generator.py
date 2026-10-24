"""One configurable entrypoint over the existing validated synthetic builders."""
import contextlib
import copy
import io
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
import uuid

from test_materials import ROOT,build_path,digest


def dense(db,fixture):
    import corpus,lexicon,segmentation
    targets={}
    for form,gloss in db.execute("SELECT DISTINCT form,gloss FROM corpus_units WHERE kind='word' AND active=1 AND form<>'。'"):
        xid=str(uuid.uuid4());body=lexicon.normalize(dict(usages=[dict(pos='N',senses=[dict(short_gloss=gloss or '测试')])]))
        db.execute('INSERT INTO lexemes VALUES(?,?,?,?,1)',(xid,'ordos',form,json.dumps(body,ensure_ascii=False)))
        targets[form]=dict(id=xid,usage_id=body['usages'][0]['id'],sense_id=body['usages'][0]['senses'][0]['id'])
    for row in db.execute("SELECT u.*,l.id link_id FROM corpus_units u LEFT JOIN lexical_links l ON l.unit_id=u.id WHERE u.kind='word' AND u.active=1 AND u.form<>'。'").fetchall():
        x=targets[row['form']];key=row['link_id'] or str(uuid.uuid4())
        if row['link_id']:
            db.execute('UPDATE lexical_links SET lexeme_id=?,usage_id=?,sense_id=? WHERE id=?',(x['id'],x['usage_id'],x['sense_id'],key))
            db.execute("UPDATE morphology_analyses SET form_id=NULL,features='[]' WHERE id=?",(key,));db.execute('DELETE FROM component_links WHERE id=?',(key,))
        else:
            db.execute('INSERT INTO lexical_links VALUES(?,?,?,?,?,?,?,?)',(key,row['id'],x['id'],x['usage_id'],x['sense_id'],'共用密集关联材料','ordos',1))
            db.execute('INSERT INTO morphology_analyses VALUES(?,?,?)',(key,None,'[]'))
    for row in db.execute('SELECT * FROM dictionary_examples').fetchall():
        body=json.loads(row['body']);corpus.analyze(body);body['targets']=[]
        for i,w in enumerate(body['words']):
            if w.get('punctuation') or not w['form'].strip():continue
            x=targets[corpus.clean(w['form'])]
            body['targets'].append(dict(lexeme_id=x['id'],usage_id=x['usage_id'],sense_id=x['sense_id'],features=[],notes='共用密集关联材料',segmentation_ref=segmentation.reference(w,i,dict(key='@word',form=w['form'],gloss=w['gloss'],fragments=[]))))
        db.execute('UPDATE dictionary_examples SET body=? WHERE id=?',(json.dumps(body,ensure_ascii=False),row['id']))
    fixture.update(targets=targets,common=targets['bi']['id'])


def research(db,fixture):
    import grammar
    sid=fixture['session'];tracks=list(db.execute('SELECT * FROM timeline_tracks WHERE session_id=?',(sid,)))
    for t in tracks:
        for prefix,kind in [('event','event'),('code','language')]:
            db.execute('INSERT INTO timeline_tracks(id,session_id,name,kind,position,parent_id) VALUES(?,?,?,?,?,?)',(prefix+'-'+t['id'],sid,'共用合成'+kind,kind,20+t['position']*2+(kind=='language'),t['id']))
    db.execute("INSERT INTO timeline_codes VALUES('shared-code','共用合成语言标记','{}',1)")
    for row in db.execute('SELECT * FROM timeline_intervals WHERE session_id=?',(sid,)).fetchall():
        for prefix,label,a,z in [('event','合成事件',100,600),('code','合成语码',1000,1600)]:
            db.execute('INSERT INTO timeline_intervals(id,session_id,track_id,label,start_ms,end_ms,parent_id,code_id) VALUES(?,?,?,?,?,?,?,?)',(prefix+'-'+row['id'],sid,prefix+'-'+row['track_id'],label,row['start_ms']+a,row['start_ms']+z,row['id'],'shared-code' if prefix=='code' else None))
    db.executemany('INSERT INTO grammar_tags VALUES(?,?,?,?,?,?,?,1)',[(f'shared-tag-{i}','ordos',f'T{i:04}',f'合成标签 {i}','共用合成类',json.dumps([f'TAG{i:04}']),'共用压力材料') for i in range(1000)])
    grammar.publish(db,'ordos')


def smoke(fixture):
    """Use the same feature blueprints that the individual regression tests use."""
    import test_paradigm_inheritance,test_reduplication,test_multipart_forms,test_gloss_inheritance
    p=test_paradigm_inheritance.ParadigmInheritanceTests();x=p.entry()
    row=p.source('independent',[('went','')]);p.complete(row)
    red=test_reduplication.ReduplicationTests();r=red.example('independent');red.save(r,'independent',type='modified')
    multi=test_multipart_forms.MultipartFormsTests();m=multi.target()
    gi=test_gloss_inheritance.GlossInheritanceTests();target=gi.word('shared-home',['家']);ind=gi.example([('shared-home','家.SG'),('free','')]);gi.link(ind,target,'@word',kind='independent');gi.mode('independent',ind,'override','本句覆盖')
    status,result=p.call('/api/grammaticality-save',dict(kind='independent',id=r['id'],revision=red.get(r,'independent')['revision'],grammaticality='questionable',_language='ordos'));p.assertEqual(status,200,result)
    other=p.api('save-language',dict(name='共用测试语言二',metadata={}))['id']
    fixture['features']=dict(paradigm=x['id'],paradigm_example=row['id'],reduplication=r['id'],circumfix=m['id'],inheritance_example=ind['id'],other_language=other)


def reduplicated(path,n):
    import server,corpus,lexicon,reduplication
    server.DB=path;server.init()
    with server.connect(audit=False) as db:
        db.execute("INSERT INTO texts(id,title,source,original,errors,language_id) VALUES('shared-redup','共用重叠压力材料','','','[]','ordos')")
        for i in range(n):
            body=corpus.analyze(dict(function='pass',ipa='je jepasu na',translation='合成重叠材料',notes='',raw='',edited=True,words=[dict(form='je~jepasu',gloss='RED~go'),dict(form='na',gloss='1SG'),dict(form='x',gloss='word')]))
            reduplication.apply(body,dict(source=dict(word=0,key='r:0:host'),base=dict(word=0,key='r:1:host'),type='partial'))
            db.execute('INSERT INTO entries(id,text_id,position,body) VALUES(?,?,?,?)',(str(i),'shared-redup',i+1,json.dumps(body,ensure_ascii=False)));lexicon.sync_entry(db,str(i))
    return dict(n=n,eid='0',texts=['shared-redup'])


def generate(profile,n,output,seed=20261024):
    if profile not in ('smoke','ordinary','dense','research','reduplication') or type(n) is not int or not 1<=n<=50000:raise ValueError('Invalid profile or sentence count (1–50000)')
    dest=build_path(output)
    if dest.exists():raise ValueError('Refusing to overwrite '+str(dest))
    temp=ROOT/'build/test-materials-runs/tmp';temp.mkdir(parents=True,exist_ok=True);tempfile.tempdir=str(temp)
    sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
    import server
    previous=server.DB;original_uuid=uuid.uuid4;randomizer=random.Random(seed)
    uuid.uuid4=lambda:uuid.UUID(int=randomizer.getrandbits(128),version=4)
    try:
        with tempfile.TemporaryDirectory(dir=temp) as directory:
            stage=Path(directory);path=stage/f'synthetic-{n}.sqlite3'
            if profile=='reduplication':fixture=reduplicated(path,n)
            else:
                from benchmark_modules import fixture as ordinary
                with contextlib.redirect_stdout(io.StringIO()):ordinary(stage,n)
                fixture=json.loads((stage/f'fixture-{n}.json').read_text(encoding='utf-8'))
                if profile in ('dense','research'):
                    with server.connect(audit=False) as db:dense(db,fixture)
                if profile=='research':
                    with server.connect(audit=False) as db:research(db,fixture)
                # Bulk seeding bypasses handler write hooks. Explicitly establish
                # the current meaning/binding model in this synthetic staging DB.
                server.init()
                import gloss_inheritance
                with server.connect(audit=False) as db:
                    gloss_inheritance.sync_meanings(db)
                    owners=[('corpus',r[0]) for r in db.execute('SELECT DISTINCT u.entry_id FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE u.active=1 AND l.sense_id IS NOT NULL')]
                    owners += [('independent',r[0]) for r in db.execute("SELECT id FROM dictionary_examples WHERE json_array_length(json_extract(body,'$.targets'))>0")]
                    for kind,rid in owners:gloss_inheritance.reconcile_owner(db,kind,rid)
                if profile=='smoke':smoke(fixture)
            import test_relation_sequences
            test_relation_sequences.RelationSequenceTests().health()
            with server.connect(audit=False) as db:
                names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                fixture['counts']={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('texts','entries','dictionary_examples','lexemes','lexical_links','gloss_bindings','morphemes','annotation_cells','timeline_intervals','grammar_tags','survey_nodes') if t in names}
            dest.parent.mkdir(parents=True,exist_ok=True)
            with dest.open('xb') as out,path.open('rb') as inp:shutil.copyfileobj(inp,out,1024*1024)
            result=dict(generator_version=2,profile=profile,requested_sentences=n,seed=seed,sha256=digest(dest),database=str(dest.relative_to(ROOT)),fixture=fixture,validation='integrity, foreign keys, 17 relation validators')
            dest.with_suffix('.fixture.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            return result
    finally:
        uuid.uuid4=original_uuid;server.DB=previous
