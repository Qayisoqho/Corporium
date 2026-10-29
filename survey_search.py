"""Read-only survey text search. Stable targets are resolved again before navigation."""
import json
import re
import unicodedata
from collections import defaultdict
import long_tasks
import grammar_survey

LABELS = dict(title='标题', content='问题说明', notes='研究笔记', context='调查提示',
              judgment='判断', local_notes='本处研究笔记', original='原文', ipa='IPA',
              form='词形', gloss='标注', translation='翻译', sentence_notes='句子备注', language_notes='句子语言备注', layers='附加标注层', writings='自定义书写形式')


def normalize(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', text).lower().replace('ς', 'σ'))


def rich_text(runs):
    return ''.join(r.get('text', '') for r in runs or [])


def visible(text):
    text = re.sub(r'#(?:sub|super|sup)\[([^\[\]]*)\]', r'\1', str(text or ''))
    return re.sub(r'\\([\\"\[\]#~?])', r'\1', text)


def excerpt(text, query):
    # Keep snippets plain; the client highlights safely after escaping.
    text = unicodedata.normalize('NFC', re.sub(r'\s+', ' ', text))
    value = normalize(text); term = normalize(query); at = value.find(term); stop = at + len(term)
    if len(value) != len(text):
        offsets = [i for i, ch in enumerate(text) for _ in normalize(ch)]
        at, stop = offsets[at], offsets[stop - 1] + 1
    start = max(0, at - 25); end = min(len(text), max(start + 110, stop + 25))
    return ('…' if start else '') + text[start:end] + ('…' if end < len(text) else '')


def options(lid, q):
    if lid == 'all': raise ValueError('请先选择一种语言，再检索语法调查')
    query = q.get('q', '')
    if not isinstance(query, str) or len(query) > 200: raise ValueError('检索文字请控制在200字以内')
    scope = q.get('scope', 'all')
    if scope not in ('all','survey','examples','layers','writings') and not scope.startswith(('layer:','writing:')): raise ValueError('调查检索范围无效')
    return query.strip(), scope


def examples_only(scope):return scope not in ('all','survey')


def outline(db, lid):
    nodes = {r['id']: {**dict(r), 'body': json.loads(r['body'])} for r in db.execute('SELECT * FROM survey_nodes WHERE language_id=? ORDER BY position,rowid', (lid,))}
    children = defaultdict(list)
    for n in nodes.values(): children[n['parent_id']].append(n)
    ordered = []; stack = [(n, []) for n in reversed(children[None])]; seen = set()
    while stack:
        n, path = stack.pop()
        if n['id'] in seen: continue
        seen.add(n['id']); path = path + [n['title']]; n['path'] = path; ordered.append(n)
        stack.extend((c, path) for c in reversed(children[n['id']]))
    return nodes, ordered


def node_fields(n):
    return dict(title=n['title'], content=rich_text(n['body'].get('content')), notes=rich_text(n['body'].get('notes')))


def evidence_fields(e, source, scope):
    body = json.loads(e['body'])
    fields = {} if examples_only(scope) else dict(judgment=body.get('judgment', ''), context=rich_text(body.get('context')), local_notes=rich_text(body.get('notes')))
    if not examples_only(scope):
        for item in body.get('member_notes',{}).values():
            for key,value in (('judgment',item.get('judgment','')),('context',rich_text(item.get('context'))),('local_notes',rich_text(item.get('notes')))):
                fields[key]+='\n'+value
    if source is not None and scope != 'survey':
        if scope in ('all','examples'):
            fields.update({k: visible(source.get(k, '')) for k in ('original', 'ipa', 'translation', 'language_notes')})
            fields['sentence_notes'] = visible(source.get('notes', ''))
            for key in ('form', 'gloss'): fields[key] = ' '.join(visible(w.get(key, '')) for w in source.get('words', []))
        for prefix,key in (('layer:','layers'),('writing:','writings')):
            fields[key]='\n'.join(v['text'] for v in source.get('_search_fields',[]) if v['field'].startswith(prefix))
    return fields


def iter_sources(db, lid, evidence, query='', field='all'):
    import example_groups
    import annotations,gloss_inheritance
    custom=annotations.SearchFields(db,lid,dict(q=query,field=field))
    for eid in dict.fromkeys(e['record_id'] for e in evidence if e['kind']==example_groups.KIND):
        try:group=example_groups.detail(db,lid,eid)
        except ValueError:continue
        joined={'notes':group['body']['name']+' '+group['body']['context'],'words':[],'_search_fields':[]}
        for member in group['members']:
            if not member['record']:continue
            source=member['record']['body']
            joined['_search_fields'].extend(custom.values('independent',member['example_id'],source,lid))
            for key in ('ipa','original','translation','language_notes'):joined[key]=joined.get(key,'')+'\n'+str(source.get(key,''))
            joined['words'].extend(source.get('words',[]))
            joined['notes']+='\n'+str(source.get('notes',''))
        yield (example_groups.KIND,eid),joined
    for kind in ('corpus', 'independent'):
        ids = list(dict.fromkeys(e['record_id'] for e in evidence if e['kind'] == kind))
        for start in long_tasks.steps(range(0, len(ids), 400)):
            chunk = ids[start:start + 400]; marks = ','.join('?' for _ in chunk)
            sql = ('SELECT e.id,e.body FROM entries e JOIN texts t ON t.id=e.text_id WHERE t.language_id=? AND e.id IN (' + marks + ')' if kind == 'corpus' else 'SELECT id,body FROM dictionary_examples WHERE language_id=? AND id IN (' + marks + ')')
            for r in long_tasks.steps(db.execute(sql, [lid, *chunk])):
                body = gloss_inheritance.load(db,kind,r['id'],r['body'],metadata=False,lightweight=True)
                if (body.get('language_id') or lid) == lid:
                    body['_search_fields']=custom.values(kind,r['id'],body,lid)
                    yield (kind, r['id']), body


def sources(db, lid, evidence, query='', field='all'):
    return dict(iter_sources(db, lid, evidence, query, field))


def matches(fields, query):
    term = normalize(query)
    return [dict(field=k, label=LABELS[k], snippet=excerpt(v, query)) for k, v in fields.items() if term in normalize(v)]


def search(db, lid, q):
    query, scope = options(lid, q)
    if not query: return dict(items=[], total=0, nodes=0, page=1, pages=1, query=query, scope=scope)
    if not db.in_transaction: db.execute('BEGIN')
    nodes, ordered = outline(db, lid)
    evidence = [dict(r) for r in db.execute('SELECT * FROM survey_evidence WHERE language_id=? ORDER BY position,rowid', (lid,))]
    records = {}
    if scope != 'survey':
        for key, body in iter_sources(db, lid, evidence, query, 'all' if scope in ('all','examples') else scope):
            found = matches(evidence_fields(dict(body='{}'), body, scope), query)
            if found: records[key] = found
    by_node = defaultdict(list)
    for e in evidence: by_node[e['node_id']].append(e)
    result = []
    for n in long_tasks.steps(ordered):
        fields = matches(node_fields(n), query) if not examples_only(scope) else []
        if fields: result.append(dict(node_id=n['id'], evidence_id=None, path=n['path'], fields=fields))
        for e in long_tasks.steps(by_node[n['id']]):
            fields = (matches(evidence_fields(e, None, 'survey'), query) if not examples_only(scope) else []) + records.get((e['kind'], e['record_id']), [])
            if fields: result.append(dict(node_id=n['id'], evidence_id=e['id'], kind=e['kind'], path=n['path'], fields=fields))
    total = len(result); pages = max(1, (total + 19) // 20); page = max(1, min(pages, int(q.get('page', 1))))
    return dict(items=result[(page-1)*20:page*20], total=total, nodes=len({r['node_id'] for r in result}), page=page, pages=pages, query=query, scope=scope)


def locate(db, lid, q):
    query, scope = options(lid, q)
    if not db.in_transaction: db.execute('BEGIN')
    field = q.get('field')
    if field not in LABELS: raise ValueError('检索字段无效')
    eid = q.get('evidence_id'); page = 1
    if eid:
        row = db.execute('SELECT * FROM survey_evidence WHERE id=? AND language_id=?', (eid, lid)).fetchone()
        if not row: raise ValueError('这处例证引用已删除，请重新检索')
        e = dict(row); nid = e['node_id']
        ids = [r[0] for r in db.execute('SELECT id FROM survey_evidence WHERE node_id=? ORDER BY position,rowid', (nid,))]
        page = ids.index(eid) // 20 + 1
        fields = evidence_fields(e, sources(db, lid, [e], query, 'all' if scope in ('all','examples','survey') else scope).get((e['kind'], e['record_id'])), scope)
    else:
        nid = q.get('node_id'); n = grammar_survey.saved_node(db, lid, nid)['node']; fields = node_fields(n) if not examples_only(scope) else {}
    grammar_survey.require(db, lid, nid)
    return dict(node_id=nid, evidence_id=eid, page=page, field=field, matched=bool(query and field in fields and normalize(query) in normalize(fields[field])), text=fields.get(field, ''))
