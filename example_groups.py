"""Ordered groups of existing independent examples; sentence identities stay intact."""
import hashlib
import json
import uuid
import sqlite3
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
    initialize_validation(db)


def drop_validation(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'example_group_checked_*'").fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    db.execute('DROP TABLE IF EXISTS example_group_validation')


def initialize_validation(db):
    db.execute('''CREATE TABLE IF NOT EXISTS example_group_validation(
        id INTEGER PRIMARY KEY,epoch INTEGER,checked_epoch INTEGER,checked_schema INTEGER)''')
    db.execute('INSERT OR IGNORE INTO example_group_validation VALUES(1,0,-1,-1)')
    for table in ('example_groups','example_group_members','languages','dictionary_examples'):
        for event in ('INSERT','UPDATE','DELETE'):
            when = ''
            if table in ('languages','dictionary_examples'):
                if event == 'INSERT' and table == 'languages':
                    continue
                if event == 'UPDATE':
                    when = ' WHEN OLD.id IS NOT NEW.id'
                    if table == 'dictionary_examples':
                        when += ' OR OLD.language_id IS NOT NEW.language_id'
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS example_group_checked_{table}_{event}
              AFTER {event} ON {table}{when} BEGIN
              UPDATE example_group_validation SET epoch=epoch+1 WHERE id=1; END''')
    # A fresh startup or repaired schema re-establishes the current validator.
    db.execute('UPDATE example_group_validation SET checked_epoch=-1,checked_schema=-1 WHERE id=1')


def validate_changes(db):
    schema = db.execute('PRAGMA main.schema_version').fetchone()[0]
    try:
        state = db.execute('SELECT epoch,checked_epoch,checked_schema FROM example_group_validation WHERE id=1').fetchone()
    except sqlite3.OperationalError as error:
        if 'no such table' not in str(error):raise
        state = None
    if state and state[0] == state[1] and state[2] == schema:
        return
    initialize_validation(db)
    validate(db)
    schema = db.execute('PRAGMA main.schema_version').fetchone()[0]
    db.execute('UPDATE example_group_validation SET checked_epoch=epoch,checked_schema=? WHERE id=1',(schema,))


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
                record = dict(db.execute('SELECT * FROM dictionary_examples_documents WHERE id=?', (member['example_id'],)).fetchone())
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
    for row in db.execute('SELECT m.*,g.language_id owner,d.language_id source FROM example_group_members m LEFT JOIN example_groups g ON g.id=m.group_id LEFT JOIN dictionary_examples_documents d ON d.id=m.example_id'):
        if not row['owner'] or row['owner'] != row['language_id'] or (row['source'] and row['source'] != row['owner']): raise ValueError('例句组成员语言或所属关系无效')
        if row['active'] not in (0, 1) or not isinstance(row['role'], str) or len(row['role']) > 40: raise ValueError('例句组成员设置无效')


import read_views
LIBRARY_CARDS=read_views.Cache(24*1024**2)
LIBRARY_PLANS=read_views.Cache(48*1024**2)


def library(db, lid, query):
    """Page display units in SQLite. A shared example counts once as a sentence."""
    import annotations
    import code_switching
    from corpus import normalize
    if not db.in_transaction:
        db.execute('BEGIN')
    if lid != 'all':
        import languages
        languages.require(db,lid)
    only = query.get('group_filter','all')
    order = query.get('sort_order','added-asc')
    if only not in ('groups','ungrouped','all'):
        raise ValueError('分组筛选无效')
    if order not in ('added-asc','added-desc'):
        raise ValueError('独立例句排序方式无效')
    direction = ' DESC' if order=='added-desc' else ' ASC'
    term = query.get('q','')
    field = query.get('field','all')
    restricted = any(query.get(k) for k in ('grammaticality','code_mode','code_id'))
    filtered = bool(term or restricted or field=='reduplication')
    lang = '' if lid=='all' else ' AND d.language_id=:lid'
    params = dict(lid=lid)
    stamp=read_views.token(db,'dictionary')
    plan_key=(stamp,lid,tuple(sorted((k,str(v)) for k,v in query.items() if k not in ('page','focus')))) if stamp else None
    plan=LIBRARY_PLANS.get(plan_key)
    if plan is not None:
        ordered,group_hits,totals=plan
        return library_page(db,ordered,group_hits,totals,query,stamp)
    if filtered:
        db.execute('DROP TABLE IF EXISTS temp.library_hits')
        db.execute('CREATE TEMP TABLE library_hits(id TEXT PRIMARY KEY) WITHOUT ROWID')
        def receive(ids):
            db.executemany('INSERT OR IGNORE INTO library_hits VALUES(?)',((rid,) for rid in ids))
        annotations.search(db,dict(query,language=lid,source='independent'),ids_only=receive)
    hit_join = ' JOIN library_hits h ON h.id=d.id' if filtered else ''
    candidates='library_hits h CROSS JOIN dictionary_examples d ON d.id=h.id' if filtered else 'dictionary_examples d'
    singles=("SELECT n.ordering,'independent' kind,d.id,d.language_id FROM "+candidates+
             " JOIN example_numbers n ON n.id=d.id AND n.language_id=d.language_id WHERE 1=1"+lang)
    groups_exist = db.execute('SELECT 1 FROM example_groups d WHERE 1=1'+lang+' LIMIT 1',params).fetchone()
    groups = 0
    if filtered and not db.execute('SELECT 1 FROM library_hits LIMIT 1').fetchone() and not (only!='ungrouped' and term and field=='all' and not restricted):
        groups_exist=False
    if groups_exist:
        db.execute('DROP TABLE IF EXISTS temp.library_units')
        db.execute('CREATE TEMP TABLE library_units(ordering INTEGER,kind TEXT,id TEXT,language_id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID')
        if only!='groups':
            db.execute('INSERT INTO library_units '+singles+''' AND NOT EXISTS(
                SELECT 1 FROM example_group_members m JOIN example_groups g ON g.id=m.group_id
                WHERE m.example_id=d.id AND m.active=1 AND (:lid='all' OR g.language_id=:lid))''',params)
        if only!='ungrouped':
            eligible = ''
            if filtered:
                eligible = ''' AND (EXISTS(SELECT 1 FROM example_group_members m JOIN library_hits h ON h.id=m.example_id
                                       WHERE m.group_id=d.id AND m.active=1)'''
                if term and field=='all' and not restricted:
                    case = query.get('case')=='true'
                    needle = normalize(term,case)
                    mode = query.get('mode','contains')
                    def group_hit(raw):
                        body=json.loads(raw)
                        for key in ('name','context'):
                            value=normalize(body.get(key,''),case)
                            if (value==needle if mode=='exact' else value.startswith(needle) if mode=='prefix'
                                else value.endswith(needle) if mode=='suffix' else needle in value):
                                return True
                        return False
                    db.create_function('library_group_hit',1,group_hit)
                    eligible += ' OR library_group_hit(d.body)'
                eligible += ')'
            db.execute("""INSERT INTO library_units SELECT COALESCE((SELECT min(n.ordering)
                FROM example_group_members m JOIN dictionary_examples e ON e.id=m.example_id
                JOIN example_numbers n ON n.language_id=e.language_id AND n.id=e.id
                WHERE m.group_id=d.id AND m.active=1),1000000000000000+d.rowid),
                'group',d.id,d.language_id FROM example_groups d WHERE 1=1"""+lang+eligible,params)
        units = 'SELECT * FROM library_units'
        groups = db.execute("SELECT count(*) FROM library_units WHERE kind='group'").fetchone()[0]
    else:
        units = singles + (' AND 0' if only=='groups' else '')
    total = db.execute('SELECT count(*) FROM ('+units+')',params).fetchone()[0]
    pages=max(1,(total+19)//20)
    requested_page=max(1,min(pages,int(query.get('page',1))))
    cacheable=bool(plan_key) and total<=100000
    if cacheable and filtered and groups:
        cacheable=not db.execute("""SELECT 1 FROM library_units g JOIN example_group_members m ON m.group_id=g.id AND m.active=1
            JOIN library_hits h ON h.id=m.example_id WHERE g.kind='group' LIMIT 1 OFFSET 65536""").fetchone()
    sql='SELECT * FROM ('+units+') ORDER BY ordering'+direction+',kind'+direction+',id'+direction
    if not cacheable:
        if query.get('focus'):
            rank=db.execute('SELECT rank FROM (SELECT id,row_number() OVER (ORDER BY ordering'+direction+',kind'+direction+',id'+direction+') rank FROM ('+units+')) WHERE id=:focus',{**params,'focus':query['focus']}).fetchone()
            if rank:requested_page=(rank[0]-1)//20+1
            query={**query,'page':requested_page,'_focus_found':bool(rank)}
        sql+=' LIMIT 20 OFFSET :off'
    ordered=list(db.execute(sql,{**params,'off':(requested_page-1)*20}))
    if groups:
        counted = """SELECT id FROM library_units WHERE kind='independent' UNION
            SELECT d.id FROM library_units g JOIN example_group_members m ON g.kind='group' AND m.group_id=g.id
            JOIN dictionary_examples d ON d.id=m.example_id"""+hit_join+' WHERE m.active=1'+lang
        sentence_total=db.execute('SELECT count(*) FROM ('+counted+')',params).fetchone()[0]
    else:
        counted='SELECT id FROM ('+units+')'
        sentence_total=total
    codes=list(db.execute("SELECT c.* FROM code_sentence_index c WHERE c.owner_kind='independent' AND EXISTS(SELECT 1 FROM ("+counted+") s WHERE s.id=c.record_id)",params))
    group_hits={}
    if filtered and groups:
        query_groups="""SELECT m.group_id,m.example_id FROM library_units g
                JOIN example_group_members m ON m.group_id=g.id AND m.active=1 JOIN library_hits h ON h.id=m.example_id
                WHERE g.kind='group'"""
        group_args=[]
        if not cacheable:
            group_args=[r['id'] for r in ordered if r['kind']=='group']
            query_groups+=" AND m.group_id IN ("+(','.join('?' for _ in group_args) or 'NULL')+")"
        for g,rid in db.execute(query_groups+' ORDER BY m.group_id,m.position,m.id',group_args):
            group_hits.setdefault(g,[]).append(rid)
    cited=[]
    if query.get('survey_node'):
        import grammar_survey
        grammar_survey.require(db,lid,query['survey_node'])
        cited=[r[0] for r in db.execute('SELECT record_id FROM survey_evidence WHERE node_id=? AND kind=?',(query['survey_node'],KIND))]
    if groups_exist:db.execute('DROP TABLE library_units')
    if filtered:db.execute('DROP TABLE library_hits')
    totals=dict(total=total,sentence_total=sentence_total,group_total=groups,ungrouped_total=total-groups,
                code_summary=code_switching.summary_rows(db,codes),cited_ids=cited,filtered=filtered)
    cost=512+sum(240+4*(len(r['id'])+len(r['language_id'])) for r in ordered)+sum(160+sum(80+4*len(v) for v in members) for members in group_hits.values())
    if cacheable:LIBRARY_PLANS.put(plan_key,(ordered,group_hits,totals),cost)
    return library_page(db,ordered,group_hits,totals,query,stamp,windowed=not cacheable)


def library_page(db,ordered,group_hits,totals,query,stamp,*,windowed=False):
    import annotations,copy,gloss_inheritance
    pages=max(1,(totals['total']+19)//20)
    page=max(1,min(pages,int(query.get('page',1))))
    focused=query.get('_focus_found',False)
    if query.get('focus') and not windowed:
        from dictionary_paging import focused_page
        target=focused_page((r['id'] for r in ordered),query['focus'],20)
        focused=target is not None
        if focused:page=target
    rows=ordered if windowed else ordered[(page-1)*20:page*20]
    items=[]
    selected=[r['id'] for r in rows if r['kind']=='independent' and LIBRARY_CARDS.get((stamp,r['id'])) is None]
    if selected:
        gloss_inheritance.prefetch(db,'independent',selected)
    for row in rows:
        rid=row['id']
        if row['kind']=='group':
            cache_key=(stamp,'group',rid) if stamp else None
            raw=LIBRARY_CARDS.get(cache_key)
            if raw is None:
                group=detail(db,row['language_id'],rid)
                if cache_key:
                    raw=json.dumps(group,ensure_ascii=False,separators=(',',':')).encode()
                    LIBRARY_CARDS.put(cache_key,raw,len(raw)+256)
            else:group=json.loads(raw)
            items.append(dict(kind='group',id=rid,group=group,matched_ids=list(group_hits.get(rid,()))))
        else:
            key=(stamp,rid) if stamp else None
            raw=LIBRARY_CARDS.get(key)
            if raw is None:
                body=annotations.independent_card(db,rid)
                if key:
                    raw=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode('utf8')
                    LIBRARY_CARDS.put(key,raw,len(raw)+256)
            else:body=json.loads(raw)
            items.append(dict(kind='independent',id=rid,language_id=row['language_id'],body=body,ordering=row['ordering']))
    return dict(items=items,page=page,pages=pages,**copy.deepcopy(totals),**({'focus_found':focused} if query.get('focus') else {}))


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
