"""Review removed dictionary identities, then freeze and detach only invalid links."""
import copy
import hashlib
import json
import long_tasks


def canonical(data):
    if 'usages' in data:return data
    # Native morphemes use the same stable read identities as dictionary_targets.
    return {**data,'usages':[dict(id='@morpheme',pos='',senses=[
        {**s,'short_gloss':s.get('gloss','')} for s in data.get('senses',[])
    ]+[dict(id='@main',short_gloss=data.get('gloss',''),definition=data.get('definition',''))]) ]}


def reason(data,ref):
    import lexicon,morphology,paradigms
    try:lexicon.selection(data,ref.get('usage_id'),ref.get('sense_id'))
    except ValueError:return 'meaning'
    try:morphology.form_selection(data,ref.get('form_id'))
    except ValueError:return 'form'
    try:paradigms.validate_selection(data,ref.get('usage_id'),ref.get('sense_id'),ref.get('form_id'))
    except ValueError:return 'ownership'
    return None


def collect(db,old,data):
    import lexicon
    data=canonical(data);links=[];examples=[];groups={}
    def identities(body):
        items={('usage',u['id']) for u in body.get('usages',[])}
        items.update(('sense',u['id'],s['id']) for u in body.get('usages',[]) for s in u.get('senses',[]))
        items.update(('form',f['id']) for f in body.get('variants',[]))
        items.update(('paradigm',t['usage_id'],m['id'],f['form_id']) for t in body.get('paradigms',[]) for r in t['rows'] for f in r['realizations'] for m in f['meanings'])
        return items
    # Ordinary spelling/gloss changes and additions do not remove an identity;
    # keep the existing save path independent of the number of its examples.
    if identities(old['body'])<=identities(data):return dict(links=[],examples=[],items=[],corpus=0,independent=0,sentences=0)
    def add(ref,kind,rid,why):
        key=(ref.get('usage_id'),ref.get('sense_id'),ref.get('form_id'),why)
        if key not in groups:
            try:
                usage,sense=lexicon.selection(old['body'],key[0],key[1]);label=(sense or {}).get('short_gloss') or (sense or {}).get('definition') or (usage or {}).get('pos') or '—'
            except ValueError:label=key[1] or key[0] or '—'
            form=next((v.get('form','') for v in old['body'].get('variants',[]) if v['id']==key[2]),'')
            context=next((t['title']+' / '+' · '.join(r['labels']) for t in old['body'].get('paradigms',[]) for r in t['rows'] for f in r['realizations'] for m in f['meanings'] if m['id']==key[1]),'')
            groups[key]=dict(usage_id=key[0],sense_id=key[1],form_id=key[2],reason=why,label=label,form=form,context=context,corpus=0,independent=0)
        groups[key][kind]+=1
    sql='SELECT l.*,a.form_id,u.entry_id FROM lexical_links l LEFT JOIN morphology_analyses a ON a.id=l.id LEFT JOIN corpus_units u ON u.id=l.unit_id WHERE l.lexeme_id=? ORDER BY l.id'
    for row in long_tasks.steps(list(db.execute(sql,(old['id'],)))):
        ref=dict(row);why=reason(data,ref)
        if why:links.append(ref);add(ref,'corpus',row['id'],why)
    for row in long_tasks.steps(list(db.execute("SELECT * FROM dictionary_examples WHERE EXISTS(SELECT 1 FROM json_each(body,'$.targets') WHERE json_extract(value,'$.lexeme_id')=?) ORDER BY id",(old['id'],)))):
        body=json.loads(row['body']);removed=[]
        for i,ref in enumerate(body.get('targets',[])):
            if ref['lexeme_id']!=old['id']:continue
            why=reason(data,ref)
            if why:removed.append(i);add(ref,'independent',row['id'],why)
        if removed:examples.append(dict(row=dict(row),indexes=removed))
    return dict(links=links,examples=examples,items=list(groups.values()),corpus=len(links),independent=sum(len(e['indexes']) for e in examples),sentences=len({e['row']['id'] for e in examples})+len({l['entry_id'] for l in links if l['entry_id']}))


def token(db,old,request):
    import journal
    proposal={k:request.get(k) for k in ('id','revision','headword','form','body')}
    return hashlib.sha256(json.dumps([old['target_kind'],proposal,journal.workspace_revision(db)],ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def preview(db,lid,request):
    import lexicon,morpheme_registry,multipart_forms
    if not db.in_transaction:db.execute('BEGIN')
    old=lexicon.get_lexeme(db,request.get('id'))
    if old['language_id']!=lid:raise ValueError('词条或语言范围已变化，请重新打开')
    if request.get('revision')!=old['revision']:raise ValueError('词条已修改，请重新打开后编辑')
    kind=request.get('kind',old['target_kind'])
    if kind!=old['target_kind']:raise ValueError('条目类型已变化，请重新打开')
    fingerprint=token(db,old,request)
    proposal=copy.deepcopy(request)
    if kind=='lexeme':
        data=lexicon.normalize(multipart_forms.align_spellings(proposal.get('body',{}),proposal.get('headword',''),old,'headword'))
        if 'paradigms' not in proposal.get('body',{}) and old['body'].get('paradigms'):data['paradigms']=old['body']['paradigms']
    else:
        native=morpheme_registry.get(db,old['id'],lid)
        _,data=morpheme_registry.prepare_body(db,lid,proposal,native)
    plan=collect(db,old,data)
    return {k:plan[k] for k in ('items','corpus','independent','sentences')}|dict(token=fingerprint)


def detach(db,plan):
    import gloss_inheritance
    owners={}
    for link in plan['links']:
        row=db.execute('SELECT e.id,e.body FROM corpus_units u JOIN entries e ON e.id=u.entry_id WHERE u.id=?',(link['unit_id'],)).fetchone()
        if row:owners[('corpus',row['id'])]=row['body']
    for table in ('component_links','lexical_reviews','morphology_analyses','lexical_links'):
        db.executemany('DELETE FROM '+table+' WHERE id=?',[(r['id'],) for r in plan['links']])
    for item in long_tasks.steps(plan['examples']):
        row=item['row'];body=json.loads(row['body']);drop=set(item['indexes'])
        body['targets']=[ref for i,ref in enumerate(body.get('targets',[])) if i not in drop]
        owners[('independent',row['id'])]=row['body']
        db.execute('UPDATE dictionary_examples SET body=?,revision=revision+1 WHERE id=?',(json.dumps(body,ensure_ascii=False),row['id']))
    for (kind,rid),before in owners.items():gloss_inheritance.reconcile_owner(db,kind,rid,before)


def apply(db,old,data,request,fingerprint=None):
    plan=collect(db,old,data);current=fingerprint or token(db,old,request)
    if request.get('link_change_token') and request['link_change_token']!=current:raise ValueError('词条或例句关联已变化，请重新预览后确认')
    if plan['items'] and (request.get('confirm_link_changes') is not True or request.get('link_change_token')!=current):
        raise ValueError('要移除的义项、用法或形式仍被例句直接引用，请先预览并确认解除关联后保存；稳定身份不会按编号自动转移。')
    detach(db,plan)
    return plan
