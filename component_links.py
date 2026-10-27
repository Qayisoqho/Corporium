"""Stable references to a component in a particular dictionary analysis.

The saved snapshot is evidence, not an identity. Changed/missing targets remain
readable and require explicit reselection; matching spellings never rebind them.
"""
import copy
import json

TABLES=('component_links',)

def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS component_links(id TEXT PRIMARY KEY,body TEXT NOT NULL)')

def snapshot(body,aid,cid):
    a=next((a for a in body.get('word_structure',{}).get('analyses',[]) if a['id']==aid),None)
    c=next((c for c in (a or {}).get('components',[]) if c['id']==cid),None)
    if not c:raise ValueError('所选形态分析或组分已不存在，请重新选择')
    return {'analysis':{k:copy.deepcopy(v) for k,v in a.items() if k!='components'},'component':copy.deepcopy(c)}

def choose(body,value):
    if not value:return None
    if not isinstance(value,dict) or not all(isinstance(value.get(k),str) and value[k] for k in ('analysis_id','component_id')):
        raise ValueError('请选择形态分析和具体组分')
    return {'analysis_id':value['analysis_id'],'component_id':value['component_id'],'snapshot':snapshot(body,value['analysis_id'],value['component_id'])}

def review(body,ref):
    if not ref:return False
    try:
        # Compare canonical fields, not absent defaults or presentation numbering.
        def canonical(s):
            import word_structure
            a={**s['analysis'],'components':[s['component']]}
            # A parent's other components are intentionally not in the snapshot.
            parent=a['components'][0].get('parent_id','');a['components'][0]={**a['components'][0],'parent_id':''}
            value=word_structure.normalize({'analyses':[a]})['analyses'][0]
            value['components'][0]['parent_id']=parent
            from manual_status import comparable
            return comparable(value)
        return canonical(snapshot(body,ref['analysis_id'],ref['component_id']))!=canonical(ref.get('snapshot'))
    except (ValueError,KeyError,TypeError):return True

def read(db,linkid):
    r=db.execute('SELECT body FROM component_links WHERE id=?',(linkid,)).fetchone()
    return json.loads(r[0]) if r else None

def validate(ref):
    if ref is None:return None
    if not isinstance(ref,dict) or not all(isinstance(ref.get(k),str) and ref[k] for k in ('analysis_id','component_id')):
        raise ValueError('组分关联记录格式不正确')
    evidence=ref.get('snapshot')
    if not isinstance(evidence,dict) or not all(isinstance(evidence.get(k),dict) for k in ('analysis','component')):
        raise ValueError('组分关联缺少原始分析记录')
    if evidence['analysis'].get('id')!=ref['analysis_id'] or evidence['component'].get('id')!=ref['component_id']:
        raise ValueError('组分关联身份与原始记录不一致')
    return copy.deepcopy(ref)

def write(db,linkid,ref):
    ref=validate(ref)
    if ref:db.execute('INSERT INTO component_links VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(linkid,json.dumps(ref,ensure_ascii=False)))
    else:db.execute('DELETE FROM component_links WHERE id=?',(linkid,))

def remap(ref,owner,xmap,submap,classmap,typemap,tagmap):
    if not ref:return None
    ref=validate(ref)
    c=ref['snapshot']['component'];target=c.get('lexeme_id')
    # Old evidence can mention already removed definitions. Preserve these IDs
    # rather than making an otherwise valid language backup impossible to import.
    if target:
        for key in ('usage_id','sense_id','form_id'):
            if c.get(key):c[key]=submap.get((target,c[key]),c[key])
        c['lexeme_id']=xmap.get(target,target)
    c['features']=[tagmap.get(f,f) for f in c.get('features',[])]
    for w in c.get('writings',[]):w['type_id']=typemap.get(w['type_id'],w['type_id'])
    return ref
