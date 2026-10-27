"""Ordered groups of existing independent examples; sentence identities stay intact."""
import hashlib
import json
import uuid
import long_tasks

TABLES = ('example_groups', 'example_group_members')
KIND = 'independent-group'


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS example_groups(
      id TEXT PRIMARY KEY,language_id TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS example_group_members(
      id TEXT PRIMARY KEY,language_id TEXT NOT NULL,group_id TEXT NOT NULL,example_id TEXT NOT NULL,
      position INTEGER NOT NULL,role TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,
      revision INTEGER NOT NULL DEFAULT 1,UNIQUE(group_id,example_id));
    CREATE INDEX IF NOT EXISTS example_groups_language ON example_groups(language_id);
    CREATE INDEX IF NOT EXISTS example_group_order ON example_group_members(group_id,active,position);
    CREATE INDEX IF NOT EXISTS example_group_source ON example_group_members(example_id);''')


def label(numbering, position):
    if numbering == 'none': return ''
    if numbering == 'numbers': return str(position + 1) + '.'
    result = ''; n = position + 1
    while n:
        n, r = divmod(n - 1, 26); result = chr(97 + r) + result
    return result + '.'


def require(db, lid, gid):
    row = db.execute('SELECT * FROM example_groups WHERE id=? AND language_id=?', (gid, lid)).fetchone()
    if not row: raise ValueError('例句组已不存在或不属于当前语言')
    return dict(row)


def reference_count(db, gid):
    return db.execute('SELECT COUNT(*) FROM survey_evidence WHERE kind=? AND record_id=?', (KIND, gid)).fetchone()[0]


def detail(db, lid, gid, enrich=True):
    import annotations
    row = require(db, lid, gid); row['body'] = json.loads(row['body'])
    rows = [dict(r) for r in db.execute('SELECT * FROM example_group_members WHERE group_id=? ORDER BY position,id', (gid,))]
    row['members'] = []; row['retired'] = [r for r in rows if not r['active']]; source_versions=[]
    for member in rows:
        if not member['active']: continue
        item = dict(member, label=label(row['body']['numbering'], len(row['members'])), record=None)
        source = db.execute('SELECT d.language_id,n.ordering,n.number,d.revision FROM dictionary_examples d LEFT JOIN example_numbers n ON n.id=d.id AND n.language_id=d.language_id WHERE d.id=?', (member['example_id'],)).fetchone()
        source_versions.append((member['example_id'],source['revision'] if source else None))
        if source and source[0] == lid:
            if enrich:
                from corpus import analyze
                record = annotations.get(db, 'independent', member['example_id'])
                record['body'] = annotations.enrich(db, analyze(record['body']), 'independent', member['example_id'])
            else:
                record = dict(db.execute('SELECT * FROM dictionary_examples WHERE id=?', (member['example_id'],)).fetchone())
                record['body'] = json.loads(record['body'])
            record['ordering']=source['ordering'];record['library_number']=source['number'];item['record'] = record
        row['members'].append(item)
    row['references'] = reference_count(db, gid)
    row['token'] = hashlib.sha256(dump([row['id'], row['revision'], rows, row['references'],source_versions]).encode()).hexdigest()
    return row


def clean_body(body):
    if not isinstance(body, dict): raise ValueError('例句组设置格式无效')
    out = {}
    for key, limit in (('name', 200), ('context', 20000)):
        value = body.get(key, '')
        if not isinstance(value, str) or len(value) > limit: raise ValueError('例句组名称或语境过长')
        out[key] = value.strip()
    out['numbering'] = body.get('numbering', 'letters')
    if out['numbering'] not in ('letters', 'numbers', 'none'): raise ValueError('组内标号方式无效')
    return out


def mutate(db, lid, action, data):
    import languages
    languages.require(db, lid)
    gid = data.get('id'); old = detail(db, lid, gid, False) if gid else None
    if old and data.get('token') != old['token']: raise ValueError('例句组或引用已变化，请重新打开；当前草稿仍保留')
    if action == 'delete':
        if not old: raise ValueError('请选择例句组')
        if old['references']: raise ValueError('该组仍被语法调查整组引用，请先处理这些引用')
        if data.get('confirmed') is not True: raise ValueError('请确认解散例句组；所有原句保留')
        db.execute('DELETE FROM example_group_members WHERE group_id=?', (gid,))
        db.execute('DELETE FROM example_groups WHERE id=?', (gid,))
        return dict(ok=True)
    if action != 'save': raise ValueError('未知例句组操作')
    body = clean_body(data.get('body', {})); members = data.get('members')
    if not isinstance(members, list) or len(members) > 200 or (not old and len(members) < 2):
        raise ValueError('新组至少选择两句，每组最多200句')
    existing = {m['example_id']: m for m in ((old['members'] + old['retired']) if old else [])}
    seen = set(); checked = []
    for member in members:
        if not isinstance(member, dict): raise ValueError('组成员格式无效')
        eid = member.get('example_id'); role = member.get('role', '')
        if not isinstance(eid, str) or eid in seen: raise ValueError('同组不能重复加入同一句')
        if not isinstance(role, str) or len(role) > 40: raise ValueError('角色请填写40字以内的文字')
        source = db.execute('SELECT language_id FROM dictionary_examples WHERE id=?', (eid,)).fetchone()
        previous = existing.get(eid)
        if not source and not (previous and previous['active']): raise ValueError('只能加入仍存在的独立例句')
        if source and source[0] != lid: raise ValueError('例句组只能加入本语言独立例句，不能加入文本句子')
        if member.get('id') and (not previous or member['id'] != previous['id']): raise ValueError('组成员身份已变化')
        checked.append((eid, role.strip(), previous)); seen.add(eid)
    if not gid:
        gid = str(uuid.uuid4()); db.execute('INSERT INTO example_groups VALUES(?,?,?,1)', (gid, lid, dump(body)))
    else:
        db.execute('UPDATE example_groups SET body=?,revision=revision+1 WHERE id=?', (dump(body), gid))
        db.execute('UPDATE example_group_members SET active=0,revision=revision+1 WHERE group_id=? AND active=1', (gid,))
    for position, (eid, role, previous) in enumerate(checked):
        if previous:
            db.execute('UPDATE example_group_members SET position=?,role=?,active=1,revision=revision+1 WHERE id=?', (position, role, previous['id']))
        else:
            db.execute('INSERT INTO example_group_members VALUES(?,?,?,?,?,?,1,1)', (str(uuid.uuid4()), lid, gid, eid, position, role))
    return detail(db, lid, gid, False)


def validate(db):
    for row in db.execute('SELECT * FROM example_groups'):
        clean_body(json.loads(row['body']))
        if not db.execute('SELECT 1 FROM languages WHERE id=?', (row['language_id'],)).fetchone(): raise ValueError('例句组语言不存在')
    for row in db.execute('SELECT m.*,g.language_id owner,d.language_id source FROM example_group_members m LEFT JOIN example_groups g ON g.id=m.group_id LEFT JOIN dictionary_examples d ON d.id=m.example_id'):
        if not row['owner'] or row['owner'] != row['language_id'] or (row['source'] and row['source'] != row['owner']): raise ValueError('例句组成员语言或所属关系无效')
        if row['active'] not in (0, 1) or not isinstance(row['role'], str) or len(row['role']) > 40: raise ValueError('例句组成员设置无效')


def library(db, lid, query):
    """Paginate groups as units, count matching sentences separately from context."""
    import annotations
    from corpus import normalize
    if lid != 'all':
        import languages
        languages.require(db, lid)
    term = query.get('q', ''); field = query.get('field', 'all'); case = query.get('case') == 'true'
    mode = query.get('mode', 'contains')
    def text_hit(value):
        a,b=normalize(value,case),normalize(term,case)
        return a==b if mode=='exact' else a.startswith(b) if mode=='prefix' else a.endswith(b) if mode=='suffix' else b in a
    # Reuse the ordinary search for layer/code/grammaticality semantics, including
    # its complete paginated hit set. Empty ordinary browsing uses only narrow rows.
    filtered = bool(term or query.get('grammaticality') or query.get('code_mode') or query.get('code_id') or field == 'reduplication')
    if filtered:
        matches = set(annotations.search(db, dict(query, language=lid, source='independent'), ids_only=True)['ids'])
    else: matches = {r[0] for r in db.execute("SELECT id FROM dictionary_examples WHERE ?='all' OR language_id=?", (lid, lid))}
    units = []; grouped = set(); groups = list(db.execute("SELECT rowid,* FROM example_groups WHERE ?='all' OR language_id=? ORDER BY rowid", (lid, lid)))
    only = query.get('group_filter', 'all')
    if only not in ('all', 'groups', 'ungrouped'): raise ValueError('分组筛选无效')
    for row in groups:
        members = list(db.execute('SELECT m.example_id,n.ordering FROM example_group_members m LEFT JOIN dictionary_examples d ON d.id=m.example_id LEFT JOIN example_numbers n ON n.id=d.id AND n.language_id=d.language_id WHERE m.group_id=? AND m.active=1 ORDER BY m.position,m.id', (row['id'],)))
        grouped.update(m['example_id'] for m in members)
        hits = [m['example_id'] for m in members if m['example_id'] in matches]
        body = json.loads(row['body']); name_hit = bool(term and field == 'all' and any(text_hit(body.get(k, '')) for k in ('name', 'context')))
        if only != 'ungrouped' and (not filtered or hits or (name_hit and not query.get('grammaticality') and not query.get('code_mode') and not query.get('code_id'))):
            order = min((m['ordering'] for m in members if m['ordering'] is not None), default=10**15 + row['rowid'])
            units.append((order, 'group', row['id'], row['language_id'], hits))
    if only != 'groups':
        for row in db.execute("SELECT n.ordering,d.id,d.language_id FROM dictionary_examples d JOIN example_numbers n ON n.id=d.id AND n.language_id=d.language_id WHERE ?='all' OR d.language_id=?", (lid, lid)):
            if row['id'] in matches and row['id'] not in grouped: units.append((row['ordering'], 'independent', row['id'], row['language_id'], []))
    sort=query.get('sort_order','added-asc')
    if sort not in ('added-asc','added-desc'):raise ValueError('独立例句排序方式无效')
    units.sort(key=lambda u:(u[0],u[1],u[2]),reverse=sort=='added-desc'); total = len(units); pages = max(1, (total + 19)//20); page = max(1, min(pages, int(query.get('page', 1))))
    counted={rid for u in units for rid in (u[4] if u[1]=='group' else [u[2]])}
    items = []
    for ordering, kind, rid, language, hits in units[(page-1)*20:page*20]:
        if kind == 'group': items.append(dict(kind=kind, id=rid, group=detail(db, language, rid), matched_ids=hits if filtered else []))
        else:
            record = annotations.get(db, 'independent', rid)
            from corpus import analyze
            record['body'] = annotations.enrich(db, analyze(record['body']), 'independent', rid)
            items.append(dict(kind=kind, id=rid, language_id=language, body=record['body'],ordering=ordering))
    import code_switching
    summary=code_switching.summary_records(db,{('independent',rid) for rid in counted})
    cited=[]
    if query.get('survey_node'):
        import grammar_survey
        grammar_survey.require(db,lid,query['survey_node'])
        cited=[r[0] for r in db.execute('SELECT record_id FROM survey_evidence WHERE node_id=? AND kind=?',(query['survey_node'],KIND))]
    return dict(items=items,total=total,page=page,pages=pages,sentence_total=len(counted),group_total=sum(u[1]=='group' for u in units),ungrouped_total=sum(u[1]=='independent' for u in units),code_summary=summary,cited_ids=cited,filtered=filtered)


def export_bundle(db, lid):
    return {t:[dict(r) for r in db.execute('SELECT * FROM '+t+' WHERE language_id=?', (lid,))] for t in TABLES}


def import_bundle(db, bundle, lid, examples):
    groups = {}; members = {}
    for row in bundle.get('example_groups', []):
        gid = groups[row['id']] = str(uuid.uuid4())
        db.execute('INSERT INTO example_groups VALUES(?,?,?,1)', (gid,lid,dump(clean_body(json.loads(row['body'])))))
    for row in bundle.get('example_group_members', []):
        if row['group_id'] not in groups: raise ValueError('例句组缺少所属关系')
        mid = members[row['id']] = str(uuid.uuid4())
        eid = examples.get(row['example_id'], 'missing:'+str(uuid.uuid4()))
        db.execute('INSERT INTO example_group_members VALUES(?,?,?,?,?,?,?,1)', (mid,lid,groups[row['group_id']],eid,row['position'],row['role'],row['active']))
    validate(db)
    return groups, members
