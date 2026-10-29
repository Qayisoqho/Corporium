"""Explicit morphological hypotheses; never infer segmentation from gloss dots."""
import json
import grammar
import categories
import word_structure
import component_links

TABLES=('morphology_analyses','unit_segments')+word_structure.TABLES+component_links.TABLES
ENTRY_TYPES=('unspecified','lexeme','morpheme','root','affix','clitic','infix','circumfix','connector','multipart','stem','expression')
FORM_TYPES=('allomorph','base','inflected','stem','spelling','pronunciation','other')
VARIATIONS=('unknown','free','conditioned','na')
CONDITIONS=('phonological','morphological','syntactic','lexical')
STATES=('hypothesis','confirmed','disputed')
RELATIONS=('stem','inflection','derivation','allomorph')

def initialize(db):
    word_structure.initialize(db)
    component_links.initialize(db)
    db.execute("CREATE TABLE IF NOT EXISTS morphology_analyses(id TEXT PRIMARY KEY,form_id TEXT,features TEXT NOT NULL DEFAULT '[]')")
    db.execute("CREATE TABLE IF NOT EXISTS unit_segments(id TEXT PRIMARY KEY,body TEXT NOT NULL)")

def choice(value,allowed,label):
    if not isinstance(value,str) or value not in allowed:raise ValueError(label+'无效')
    return value

def text(value):
    if not isinstance(value,str):raise ValueError('形态说明必须是文本')
    return value

def ids(value):
    if not isinstance(value,list) or any(not isinstance(x,str) or not x for x in value):raise ValueError('语法特征须引用已登记的标签')
    return list(dict.fromkeys(value))

def normalize(body,result):
    from manual_status import clean
    body=clean(body)
    result['word_structure']=word_structure.normalize(body.get('word_structure',{}))
    result['entry_type']=choice(body.get('entry_type','unspecified'),ENTRY_TYPES,'条目类型')
    result['features']=ids(body.get('features',[]))
    relation=body.get('relation')
    if relation:
        if not isinstance(relation,dict):raise ValueError('所属基本条目格式错误')
        result['relation']={'base_id':text(relation.get('base_id','')),'type':choice(relation.get('type'),RELATIONS,'条目关系')}
        if not result['relation']['base_id']:raise ValueError('请选择所属基本条目')
    else:result['relation']=None
    for source,target in zip(body.get('variants',[]),result['variants']):
        kind=text(source.get('kind','other')).strip()
        target.update(kind=categories.FORM_NAMES.get(kind,kind),variation=choice(source.get('variation','unknown'),VARIATIONS,'变体关系'),features=ids(source.get('features',[])))
        for key in ('pronunciation','conditions','source','notes'):target[key]=text(source.get(key,''))
        types=source.get('condition_types',[])
        if not isinstance(types,list) or any(t not in CONDITIONS for t in types):raise ValueError('出现条件类型无效')
        target['condition_types']=list(dict.fromkeys(types))
    for source,target in zip(body.get('usages',[]),result['usages']):
        target['features']=ids(source.get('features',[]))
        for source_sense,target_sense in zip(source.get('senses',[]),target['senses']):target_sense['features']=ids(source_sense.get('features',[]))
    import multipart_forms
    return multipart_forms.normalize_body(body,result)

def form_selection(body,form_id):
    if not form_id:return None
    form=next((f for f in body.get('variants',[]) if f['id']==form_id),None)
    if not form:raise ValueError('关联的形式已不存在，请先调整用例关联再删除形式')
    return form

def check_features(db,lid,features):
    values=ids(features)
    for fid in values:
        r=db.execute('SELECT language_id FROM grammar_tags WHERE id=?',(fid,)).fetchone()
        if not r or r[0]!=lid:raise ValueError('形态分析引用的语法标签不存在或属于其他语言；请先调整引用')
    return values

def set_analysis(db,link_id,body,lexeme):
    if 'component_selection' in body:
        component_links.write(db,link_id,component_links.choose(lexeme['body'],body['component_selection']))
    elif 'component_ref' in body:
        component_links.write(db,link_id,body['component_ref'])
    form_id=body.get('form_id') or None
    form_selection(lexeme['body'],form_id)
    import paradigms
    paradigms.validate_selection(lexeme['body'],body.get('usage_id'),body.get('sense_id'),form_id)
    features=check_features(db,lexeme['language_id'],body.get('features',[]))
    db.execute('INSERT INTO morphology_analyses VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET form_id=excluded.form_id,features=excluded.features',(link_id,form_id,json.dumps(features)))

def analysis(db,link_id):
    r=db.execute('SELECT * FROM morphology_analyses WHERE id=?',(link_id,)).fetchone()
    import link_review
    return {'review_reason':link_review.reason(db,link_id),**({'form_id':r['form_id'],'features':json.loads(r['features'])} if r else {'form_id':None,'features':[]}), 'component_ref':component_links.read(db,link_id)}

def validate(db,entries=None,affected=None):
    if entries is None:entries={r['id']:{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT * FROM dictionary_targets')}
    word_structure.validate(db,entries)
    parents={}
    for xid,x in entries.items():
        b=x['body'];check_features(db,x['language_id'],b.get('features',[]))
        import paradigms
        paradigms.normalize(b,dict(b))
        for part in [*b.get('variants',[]),*b.get('usages',[]),*(s for u in b.get('usages',[]) for s in u.get('senses',[]))]:check_features(db,x['language_id'],part.get('features',[]))
        rel=b.get('relation')
        if rel:
            base=entries.get(rel['base_id'])
            if not base or base['language_id']!=x['language_id']:raise ValueError('所属基本条目不存在或语言不一致，请先调整形态关系')
            parents[xid]=rel['base_id']
    for start in parents:
        seen=set();p=start
        while p in parents:
            if p in seen:raise ValueError('所属基本条目不能形成循环关系')
            seen.add(p);p=parents[p]
    # Equal target/form/features tuples have the same validity regardless of how
    # many occurrences use them; the LEFT JOIN still exposes orphan analyses.
    import lexicon
    sql='SELECT DISTINCT l.lexeme_id,l.usage_id,l.sense_id,a.form_id,a.features FROM morphology_analyses a LEFT JOIN lexical_links l ON l.id=a.id'
    if affected is None:rows=db.execute(sql)
    else:
        from itertools import chain
        rows=chain(lexicon.scoped_rows(db,sql,[('a.id',affected['links'])]),lexicon.scoped_rows(db,'SELECT DISTINCT l.lexeme_id,l.usage_id,l.sense_id,a.form_id,a.features FROM lexical_links l JOIN morphology_analyses a ON a.id=l.id',[('l.lexeme_id',affected['targets'])]))
    for r in rows:
        x=entries.get(r['lexeme_id'])
        if not x:raise ValueError('形态分析缺少词典关联')
        form_selection(x['body'],r['form_id']);check_features(db,x['language_id'],json.loads(r['features']))
        import paradigms
        paradigms.validate_selection(x['body'],r['usage_id'],r['sense_id'],r['form_id'])
    for e in db.execute('SELECT language_id,body FROM dictionary_examples'):
        for t in json.loads(e['body'])['targets']:
            x=entries.get(t['lexeme_id'])
            if x:
                form_selection(x['body'],t.get('form_id'));check_features(db,e['language_id'],t.get('features',[]))
                import paradigms
                paradigms.validate_selection(x['body'],t.get('usage_id'),t.get('sense_id'),t.get('form_id'))

def options(db,lid,entry_id=''):
    sql="SELECT id,language_id,headword,body,revision,target_kind FROM dictionary_targets WHERE (?='all' OR language_id=?)";params=[lid,lid]
    if entry_id:
        row=db.execute('SELECT language_id,body FROM dictionary_targets WHERE id=?',(entry_id,)).fetchone()
        if not row or lid not in ('all',row['language_id']):raise ValueError('词条不存在或属于其他语言')
        body=json.loads(row['body']);refs={(body.get('relation') or {}).get('base_id','')}
        refs.update(c.get('lexeme_id','') for a in body.get('word_structure',{}).get('analyses',[]) for c in a.get('components',[]));refs.discard('')
        # A detail needs direct targets and reverse relations, not all entry drafts.
        sql+=' AND (id IN ('+','.join('?' for _ in refs)+") OR json_extract(body,'$.relation.base_id')=? OR EXISTS(SELECT 1 FROM json_each(body,'$.word_structure.analyses') a,json_each(a.value,'$.components') c WHERE json_extract(c.value,'$.lexeme_id')=?))"
        params.extend([*refs,entry_id,entry_id])
    sql+=' ORDER BY headword COLLATE NOCASE'
    return {'classes':categories.listing(db,lid),'writing_types':[dict(r) for r in db.execute("SELECT * FROM writing_types WHERE ?='all' OR language_id=? ORDER BY position,name",(lid,lid))],'tags':grammar.listing(db,lid),'entries':[dict(r) for r in db.execute(sql,params)]}

def suggested_features(db,lid,gloss):
    lookup=grammar.index(grammar.listing(db,lid));found=[]
    for token in grammar.tokens(gloss,lid,lookup):
        tag=lookup.get((lid,token.casefold()))
        if tag and tag['id'] not in found:found.append(tag['id'])
    return found
