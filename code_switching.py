"""Word identities describe code use; optional audio links never infer word times."""
import hashlib
import json
import uuid

TABLES = ('code_spans', 'code_time_links')


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def initialize(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS code_spans(id TEXT PRIMARY KEY,owner_kind TEXT NOT NULL,
        record_id TEXT NOT NULL,language_id TEXT NOT NULL,code_id TEXT,word_ids TEXT NOT NULL,
        snapshot TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 1);
      CREATE INDEX IF NOT EXISTS code_span_owner ON code_spans(owner_kind,record_id);
      CREATE INDEX IF NOT EXISTS code_span_language ON code_spans(language_id,code_id);
      CREATE TABLE IF NOT EXISTS code_time_links(id TEXT PRIMARY KEY,span_id TEXT NOT NULL,
        interval_id TEXT NOT NULL UNIQUE,revision INTEGER NOT NULL DEFAULT 1);
      CREATE INDEX IF NOT EXISTS code_time_span ON code_time_links(span_id);
      CREATE TABLE IF NOT EXISTS code_sentence_index(id TEXT PRIMARY KEY,owner_kind TEXT NOT NULL,
        record_id TEXT NOT NULL,language_id TEXT NOT NULL,mixed INTEGER NOT NULL,
        code_ids TEXT NOT NULL,review INTEGER NOT NULL);
      CREATE INDEX IF NOT EXISTS code_sentence_filter ON code_sentence_index(language_id,mixed);
      CREATE UNIQUE INDEX IF NOT EXISTS code_sentence_owner ON code_sentence_index(owner_kind,record_id);
    ''')


def catalog(db):
    return [dict(r) for r in db.execute('SELECT * FROM timeline_codes ORDER BY name,id')]


def rows(db, kind, rid):
    return [dict(r) for r in db.execute('SELECT * FROM code_spans WHERE owner_kind=? AND record_id=? ORDER BY rowid', (kind, rid))]


def owner(db, kind, rid):
    import annotations
    return annotations.get(db, kind, rid)


def profile(db, kind, rid, data=None, spans=None, codes=None):
    d = data or owner(db, kind, rid)
    spans = rows(db, kind, rid) if spans is None else spans
    codes = {r['id']: r for r in catalog(db)} if codes is None else codes
    words = {w['id']: (i, d['body']['words'][i]) for i, w in enumerate(d['words'])}
    import corpus
    live = {uid for uid, (_, w) in words.items() if w['form'].strip() and not corpus.boundary_count(w['form']) and not w.get('punctuation')}
    live_prefix = [0]
    for unit in d['words']: live_prefix.append(live_prefix[-1] + (unit['id'] in live))
    base = d['language_id']
    base_row = db.execute('SELECT name FROM languages WHERE id=?', (base,)).fetchone()
    labels = {}; marked = {}; used = set(); covered = set(); reviews = 0; result = []
    for s in spans:
        s = dict(s); ids = json.loads(s['word_ids']); snap = json.loads(s['snapshot'])
        code = codes.get(s['code_id']); meta = json.loads(code['metadata']) if code else {}
        s.update(word_ids=ids, snapshot=snap, name=code['name'] if code else '未确定',
                 short=meta.get('number') or (code['name'] if code else '?'))
        missing = [uid for uid in ids if uid not in words]
        changed = [uid for uid in ids if uid in words and snap.get(uid) != words[uid][1]['form']]
        s['review'] = bool(missing or changed)
        s['review_reason'] = '词格已删除或形式已改变，请核对标记范围' if s['review'] else ''
        display_ids=sorted(ids,key=lambda uid:words[uid][0] if uid in words else len(words)+ids.index(uid))
        s['positions'] = sorted(words[uid][0] for uid in ids if uid in words)
        s['text'] = ' '.join(words[uid][1]['form'] if uid in words else snap.get(uid, '（原词格）') for uid in display_ids)
        if s['review']: reviews += 1
        key = 'language:' + meta['workspace_language_id'] if meta.get('workspace_language_id') else 'code:' + str(s['code_id'])
        previous = -2
        ordered = sorted((u for u in ids if u in words), key=lambda u: words[u][0])
        for j, uid in enumerate(ordered):
            index, w = words[uid]
            next_index = words[ordered[j + 1]][0] if j + 1 < len(ordered) else None
            marked[uid] = dict(span_id=s['id'], code_id=s['code_id'], name=s['name'], short=s['short'],
                               notes=s['notes'], review=s['review'], start=index != previous + 1,
                               end=next_index is None or live_prefix[next_index] > live_prefix[index + 1])
            previous = index
            if uid not in live: continue
            covered.add(uid)
            # Uncertain/deleted/replaced words do not silently establish code identity.
            if code and uid not in changed:
                used.add(s['code_id']); labels[key] = code['name']
        result.append(s)
    if live - covered: labels.setdefault('language:' + base, base_row['name'] if base_row else base)
    return dict(mixed=len(labels) > 1, languages=list(labels.values()), code_ids=sorted(used),
                review=reviews, has_annotations=bool(spans), spans=result, marked=marked,
                base_language=base, base_name=base_row['name'] if base_row else base)


def attach(db, body, kind, rid, d=None):
    body.pop('code_profile', None)
    for w in body.get('words', []):
        for field in ('code_unit', 'code_mark'): w.pop(field, None)
    if not db.execute('SELECT 1 FROM code_spans WHERE owner_kind=? AND record_id=? LIMIT 1', (kind, rid)).fetchone():
        return body
    d = d or owner(db, kind, rid)
    p = profile(db, kind, rid, d)
    body['code_profile'] = {k: p[k] for k in ('mixed', 'languages', 'review', 'has_annotations')}
    for w, unit in zip(body.get('words', []), d['words']):
        w['code_unit'] = unit['id']
        if unit['id'] in p['marked']: w['code_mark'] = p['marked'][unit['id']]
    return body


def token(db, d):
    spans = rows(db, d['kind'], d['id'])
    links = [dict(r) for r in db.execute('SELECT l.* FROM code_time_links l JOIN code_spans s ON s.id=l.span_id WHERE s.owner_kind=? AND s.record_id=? ORDER BY l.id', (d['kind'], d['id']))]
    return hashlib.sha256(dump([d['revision'], d['words'], spans, links, catalog(db)]).encode()).hexdigest()


def detail(db, kind, rid):
    d = owner(db, kind, rid); p = profile(db, kind, rid, d)
    audio_id = rid if kind == 'corpus' else 'independent:' + rid
    options = [dict(r) for r in db.execute('''SELECT i.id,i.code_id,i.start_ms,i.end_ms,i.revision,
        s.name session_name,s.id session_id,s.revision session_revision,t.name track_name,l.span_id
        FROM timeline_intervals i JOIN timeline_tracks t ON t.id=i.track_id
        JOIN timeline_intervals parent ON parent.id=i.parent_id
        JOIN timeline_sessions s ON s.id=i.session_id LEFT JOIN code_time_links l ON l.interval_id=i.id
        WHERE t.kind='language' AND parent.entry_id=? AND s.language_id=? ORDER BY s.position,i.start_ms,i.id''', (audio_id, d['owner_language']))]
    return {k: d[k] for k in ('kind', 'id', 'revision', 'language_id', 'owner_language', 'words')} | dict(
        words=[{**w, 'form': d['body']['words'][i]['form'], 'selectable': bool(d['body']['words'][i]['form'].strip()) and not __import__('corpus').boundary_count(w['form']) and not d['body']['words'][i].get('punctuation')} for i, w in enumerate(d['words'])],
        spans=p['spans'], codes=catalog(db), profile={k: p[k] for k in ('mixed', 'languages', 'review', 'base_name')},
        intervals=options, token=token(db, d))


def update_index(db, kind, rid):
    key = kind + ':' + rid
    if not rows(db, kind, rid):
        db.execute('DELETE FROM code_sentence_index WHERE id=?', (key,)); return
    try: d = owner(db, kind, rid)
    except ValueError:
        db.execute('DELETE FROM code_sentence_index WHERE id=?', (key,)); return
    p = profile(db, kind, rid, d)
    db.execute('INSERT OR REPLACE INTO code_sentence_index VALUES(?,?,?,?,?,?,?)',
               (key, kind, rid, d['owner_language'], int(p['mixed']), dump(p['code_ids']), p['review']))


def rebuild(db):
    db.execute('DELETE FROM code_sentence_index')
    for r in db.execute('SELECT DISTINCT owner_kind,record_id FROM code_spans').fetchall():
        __import__('long_tasks').checkpoint()
        update_index(db, *r)


def check_link(db, span, interval_id):
    row = db.execute('''SELECT i.*,t.kind,p.entry_id parent_entry,s.language_id owner_language
        FROM timeline_intervals i JOIN timeline_tracks t ON t.id=i.track_id
        JOIN timeline_intervals p ON p.id=i.parent_id JOIN timeline_sessions s ON s.id=i.session_id WHERE i.id=?''', (interval_id,)).fetchone()
    expected = span['record_id'] if span['owner_kind'] == 'corpus' else 'independent:' + span['record_id']
    if not row or row['kind'] != 'language' or row['parent_entry'] != expected or row['owner_language'] != span['language_id']:
        raise ValueError('语言区间必须属于这条例句及同一语言工作区')
    if row['code_id'] != span['code_id']: raise ValueError('正文与时间片段须使用相同语言；已关联的语言请在正文语码标记中修改')
    return row


def touch_audio(db, intervals):
    sessions = set()
    for iid in intervals:
        row = db.execute('SELECT session_id FROM timeline_intervals WHERE id=?', (iid,)).fetchone()
        if row:
            db.execute('UPDATE timeline_intervals SET revision=revision+1 WHERE id=?', (iid,))
            sessions.add(row[0])
    for sid in sessions: db.execute('UPDATE timeline_sessions SET revision=revision+1 WHERE id=?', (sid,))


def detach_audio(db, span_id):
    touch_audio(db, [r[0] for r in db.execute('SELECT interval_id FROM code_time_links WHERE span_id=?', (span_id,))])
    db.execute('DELETE FROM code_time_links WHERE span_id=?', (span_id,))


def mutate(db, action, b, lid):
    d = owner(db, b['kind'], b['record_id'])
    if d['owner_language'] != lid: raise ValueError('请在例句所属语言中编辑语码标记')
    if b.get('token') != token(db, d): raise ValueError('例句、语码标记或语言目录已更新，请重新打开后操作')
    old = db.execute('SELECT * FROM code_spans WHERE id=?', (b.get('id'),)).fetchone()
    if b.get('id') and (not old or old['owner_kind'] != b['kind'] or old['record_id'] != b['record_id']): raise ValueError('语码标记不属于这条例句')
    if action == 'delete':
        if not old or b.get('confirmed') is not True: raise ValueError('请确认移除正文语码标记；录音时间片段会保留')
        detach_audio(db, old['id'])
        db.execute('DELETE FROM code_spans WHERE id=?', (old['id'],))
    elif action in ('link', 'unlink'):
        if not old: raise ValueError('请先保存正文语码标记')
        interval = check_link(db, old, b.get('interval_id'))
        if interval['revision'] != b.get('interval_revision'): raise ValueError('时间片段已修改，请刷新后重新关联')
        linked = db.execute('SELECT * FROM code_time_links WHERE interval_id=?', (interval['id'],)).fetchone()
        if linked and linked['span_id'] != old['id']: raise ValueError('这个时间片段已关联其他正文范围，请先解除关联')
        if action == 'link' and not linked:
            db.execute('INSERT INTO code_time_links VALUES(?,?,?,1)', (str(uuid.uuid4()), old['id'], interval['id']))
            touch_audio(db, [interval['id']])
        elif action == 'unlink' and linked:
            db.execute('DELETE FROM code_time_links WHERE id=?', (linked['id'],))
            touch_audio(db, [interval['id']])
    elif action == 'save':
        ids = b.get('word_ids'); live = {w['id']: (i, d['body']['words'][i]) for i, w in enumerate(d['words'])}
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) or any(i not in live for i in ids): raise ValueError('请选择现有词格')
        positions = sorted(live[i][0] for i in ids)
        # Existing identities may become discontinuous after inserting/moving words.
        omitted=[w for uid,(i,w) in live.items() if positions[0]<=i<=positions[-1] and uid not in ids]
        skips_words=any(w['form'].strip() and not __import__('corpus').boundary_count(w['form']) and not w.get('punctuation') for w in omitted)
        if skips_words and (not old or set(ids) != set(json.loads(old['word_ids']))): raise ValueError('新标记请选择连续词格；已有标记会跟随原词格')
        if any(not live[i][1]['form'].strip() or __import__('corpus').boundary_count(live[i][1]['form']) or live[i][1].get('punctuation') for i in ids): raise ValueError('空词格、标点和音系边界不单独指定语码')
        for other in rows(db, b['kind'], b['record_id']):
            if other['id'] != b.get('id') and set(ids) & set(json.loads(other['word_ids'])): raise ValueError('所选词格已有语码标记，请先编辑或移除原标记')
        code_id = b.get('code_id') or None
        if code_id and not db.execute('SELECT 1 FROM timeline_codes WHERE id=?', (code_id,)).fetchone(): raise ValueError('语言标记已不存在')
        notes = b.get('notes', '')
        if not isinstance(notes, str) or len(notes) > 20000: raise ValueError('备注须为不超过20000字的文字')
        sid = old['id'] if old else str(uuid.uuid4())
        ordered = sorted(ids, key=lambda i: live[i][0]); snap = {i: live[i][1]['form'] for i in ordered}
        if old and old['code_id']==code_id and old['notes']==notes and json.loads(old['word_ids'])==ordered and json.loads(old['snapshot'])==snap:return dict(ok=True)
        if old and (set(ids) != set(json.loads(old['word_ids'])) or snap != json.loads(old['snapshot'])):
            detach_audio(db, sid)
        db.execute('''INSERT INTO code_spans VALUES(?,?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET
            code_id=excluded.code_id,word_ids=excluded.word_ids,snapshot=excluded.snapshot,notes=excluded.notes,revision=code_spans.revision+1''',
                   (sid, b['kind'], b['record_id'], lid, code_id, dump(ordered), dump(snap), notes))
        if old and old['code_id'] != code_id:
            sessions = set()
            for r in db.execute('SELECT i.* FROM timeline_intervals i JOIN code_time_links l ON l.interval_id=i.id WHERE l.span_id=?', (sid,)).fetchall():
                name = db.execute('SELECT name FROM timeline_codes WHERE id=?', (code_id,)).fetchone()
                db.execute('UPDATE timeline_intervals SET code_id=?,label=?,revision=revision+1 WHERE id=?', (code_id, name[0] if name else '未确定', r['id']))
                sessions.add(r['session_id'])
            for session in sessions: db.execute('UPDATE timeline_sessions SET revision=revision+1 WHERE id=?', (session,))
    else: raise ValueError('未知语码标记操作')
    update_index(db, b['kind'], b['record_id'])
    return dict(ok=True)


def sync_changes(db, changes):
    affected = set(); tables = {t for t, _ in changes}
    if not tables & {'entries', 'texts', 'dictionary_examples', 'corpus_units', 'code_spans', 'code_time_links', 'timeline_intervals', 'timeline_codes', 'languages'}: return
    # Deleting audio never deletes text annotations; deleting the original sentence does.
    db.execute("DELETE FROM code_spans WHERE (owner_kind='corpus' AND record_id NOT IN (SELECT id FROM entries)) OR (owner_kind='independent' AND record_id NOT IN (SELECT id FROM dictionary_examples))")
    db.execute('DELETE FROM code_time_links WHERE span_id NOT IN (SELECT id FROM code_spans) OR interval_id NOT IN (SELECT id FROM timeline_intervals)')
    indexed={tuple(r) for r in db.execute('SELECT owner_kind,record_id FROM code_sentence_index UNION SELECT owner_kind,record_id FROM code_spans')}
    for (table, _), (a, b) in list(changes.items()):
        if table=='entries' and a and b and a['body']==b['body'] and a['text_id']==b['text_id']:continue
        for r in (a, b):
            if not r: continue
            if table == 'code_spans': affected.add((r['owner_kind'], r['record_id']))
            elif table in ('entries', 'dictionary_examples'):
                key=('corpus' if table=='entries' else 'independent',r['id'])
                if key in indexed:affected.add(key)
    text_language_changed=any(t=='texts' and a and b and a['language_id']!=b['language_id'] for (t,_),(a,b) in changes.items())
    if tables & {'timeline_codes', 'languages'} or text_language_changed:
        affected.update(tuple(r) for r in db.execute('SELECT DISTINCT owner_kind,record_id FROM code_spans'))
    for kind, rid in affected: update_index(db, kind, rid)
    if tables & {'code_spans', 'code_time_links', 'timeline_codes', 'timeline_intervals', 'languages', 'texts'}:
        validate_changes(db, [{'table':t,'before':a,'after':b} for (t,_),(a,b) in list(changes.items())])


def validate(db, span_ids=None):
    for r in db.execute('SELECT * FROM timeline_codes'):
        target = json.loads(r['metadata']).get('workspace_language_id')
        if target and not db.execute('SELECT 1 FROM languages WHERE id=?', (target,)).fetchone(): raise ValueError('语言标记所对应的语言工作区已不存在')
    owners = {}; spans=list(db.execute('SELECT * FROM code_spans')) if span_ids is None else [r for sid in span_ids if (r:=db.execute('SELECT * FROM code_spans WHERE id=?',(sid,)).fetchone())]
    for r in spans:
        key = (r['owner_kind'], r['record_id'])
        if key not in owners: owners[key] = owner(db, *key)
        if owners[key]['owner_language'] != r['language_id']: raise ValueError('语码标记的所属语言不一致')
        if r['code_id'] and not db.execute('SELECT 1 FROM timeline_codes WHERE id=?', (r['code_id'],)).fetchone(): raise ValueError('语言标记仍被正文引用，不能删除或撤销其创建')
        ids = json.loads(r['word_ids']); snap = json.loads(r['snapshot'])
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) or not isinstance(snap, dict) or set(snap) != set(ids) or any(not isinstance(v, str) for v in snap.values()): raise ValueError('语码标记的词格快照无效')
    seen = {}
    for r in spans:
        key = (r['owner_kind'], r['record_id']); used = seen.setdefault(key, set()); ids = set(json.loads(r['word_ids']))
        if used & ids: raise ValueError('同一词格不能有重叠的语码标记')
        used.update(ids)
    links=list(db.execute('SELECT * FROM code_time_links')) if span_ids is None else [r for sid in span_ids for r in db.execute('SELECT * FROM code_time_links WHERE span_id=?',(sid,))]
    for r in links:
        span = db.execute('SELECT * FROM code_spans WHERE id=?', (r['span_id'],)).fetchone()
        if not span: raise ValueError('正文语码关联已不存在')
        check_link(db, span, r['interval_id'])


def validate_changes(db, changes):
    if any(c['table'] in ('timeline_codes','languages') or (c['table']=='texts' and c['before'] and c['after'] and c['before']['language_id']!=c['after']['language_id']) for c in changes):
        validate(db);return
    span_ids=set()
    for c in changes:
        for row in (c['before'],c['after']):
            if not row:continue
            if c['table']=='code_spans':span_ids.add(row['id'])
            elif c['table']=='code_time_links':span_ids.add(row['span_id'])
            elif c['table']=='timeline_intervals':
                span_ids.update(r[0] for r in db.execute('SELECT span_id FROM code_time_links WHERE interval_id=?',(row['id'],)))
    validate(db, span_ids)


def after_undo(db, changes):
    validate_changes(db,changes)
    if any(c['table'] in ('timeline_codes','languages') or (c['table']=='texts' and c['before'] and c['after'] and c['before']['language_id']!=c['after']['language_id']) for c in changes):rebuild(db);return
    affected=set();indexed={tuple(r) for r in db.execute('SELECT owner_kind,record_id FROM code_sentence_index UNION SELECT owner_kind,record_id FROM code_spans')}
    for c in changes:
        if c['table']=='entries' and c['before'] and c['after'] and c['before']['body']==c['after']['body'] and c['before']['text_id']==c['after']['text_id']:continue
        for row in (c['before'],c['after']):
            if not row:continue
            if c['table']=='code_spans':affected.add((row['owner_kind'],row['record_id']))
            elif c['table'] in ('entries','dictionary_examples'):
                key=('corpus' if c['table']=='entries' else 'independent',row['id'])
                if key in indexed:affected.add(key)
    for kind,rid in affected:update_index(db,kind,rid)


def filter_sql(q, kind, rid):
    mode = q.get('code_mode', ''); code = q.get('code_id', '')
    if mode not in ('', 'mixed', 'marked', 'review'): raise ValueError('语码筛选方式无效')
    if not mode and not code: return '', []
    where = ['c.owner_kind=' + kind, 'c.record_id=' + rid]; args = []
    if mode == 'mixed': where.append('c.mixed=1')
    elif mode == 'review': where.append('c.review>0')
    if code: where.append('EXISTS(SELECT 1 FROM json_each(c.code_ids) WHERE value=?)'); args.append(code)
    return ' AND EXISTS(SELECT 1 FROM code_sentence_index c WHERE ' + ' AND '.join(where) + ')', args


def summary(db, sql, args, matched=None):
    results = list(db.execute('SELECT c.* FROM code_sentence_index c WHERE EXISTS(SELECT 1 FROM (' + sql + ') q WHERE q.kind=c.owner_kind AND q.id=c.record_id)', args))
    if matched is not None: results = [r for r in results if (r['owner_kind'], r['record_id']) in matched]
    return summary_rows(db, results)


def summary_records(db, records):
    """Summarize distinct hit sentences in bounded, cancellable indexed reads."""
    import long_tasks
    results = []
    for kind in ('corpus', 'independent'):
        ids = sorted({rid for k, rid in records if k == kind})
        for start in long_tasks.steps(range(0, len(ids), 400)):
            chunk = ids[start:start + 400]
            results.extend(db.execute('SELECT * FROM code_sentence_index WHERE owner_kind=? AND record_id IN (' + ','.join('?' for _ in chunk) + ')', [kind, *chunk]))
    return summary_rows(db, results)


def summary_rows(db, results):
    counts = {}; codes = {r['id']: r for r in catalog(db)}
    for r in results:
        for cid in json.loads(r['code_ids']): counts[cid] = counts.get(cid, 0) + 1
    return dict(marked=len(results), mixed=sum(r['mixed'] for r in results), review=sum(bool(r['review']) for r in results),
                languages=[dict(id=cid, name=codes[cid]['name'], sentences=n) for cid, n in sorted(counts.items()) if cid in codes])


def copy_spans(db, source_kind, source_id, target_kind, target_id, mapping, move=False):
    """Copy selected identities, without copying their recording-specific links."""
    target = owner(db, target_kind, target_id)
    copied = {}
    for s in rows(db, source_kind, source_id):
        ids = json.loads(s['word_ids']); picked = [i for i in ids if i in mapping]
        if not picked: continue
        snap = json.loads(s['snapshot']); sid = str(uuid.uuid4())
        copied[s['id']] = sid
        db.execute('INSERT INTO code_spans VALUES(?,?,?,?,?,?,?,?,1)', (sid, target_kind, target_id, target['owner_language'], s['code_id'], dump([mapping[i] for i in picked]), dump({mapping[i]: snap[i] for i in picked}), s['notes']))
        if move:
            rest = [i for i in ids if i not in mapping]
            # Moving text invalidates the old audio correspondence; never guess new times.
            detach_audio(db, s['id'])
            if rest: db.execute('UPDATE code_spans SET word_ids=?,snapshot=?,revision=revision+1 WHERE id=?', (dump(rest), dump({i: snap[i] for i in rest}), s['id']))
            else: db.execute('DELETE FROM code_spans WHERE id=?', (s['id'],))
    return copied


def export_bundle(db, lid, stream=False):
    import streaming_json
    spans = streaming_json.Rows(db, 'SELECT * FROM code_spans WHERE language_id=? ORDER BY rowid', (lid,)) if stream else [dict(r) for r in db.execute('SELECT * FROM code_spans WHERE language_id=? ORDER BY rowid', (lid,))]
    links = streaming_json.Rows(db, 'SELECT l.* FROM code_time_links l JOIN code_spans s ON s.id=l.span_id WHERE s.language_id=?', (lid,)) if stream else [dict(r) for r in db.execute('SELECT l.* FROM code_time_links l JOIN code_spans s ON s.id=l.span_id WHERE s.language_id=?', (lid,))]
    return dict(code_spans=spans, code_time_links=links)


def import_bundle(db, bundle, lid, entries, examples, units, independent_units, timelines):
    maps = {}; codes = timelines.get('timeline_codes', {}); intervals = timelines.get('timeline_intervals', {})
    for s in __import__('long_tasks').steps(bundle.get('code_spans', [])):
        kind = s['owner_kind']; rid = (entries if kind == 'corpus' else examples).get(s['record_id'])
        if kind not in ('corpus', 'independent') or not rid: raise ValueError('语码标记缺少所属例句')
        umap = units if kind == 'corpus' else independent_units
        old_ids = json.loads(s['word_ids']); snap = json.loads(s['snapshot'])
        # Retain unavailable identities as review-only references; never reattach by position.
        ids = [umap.setdefault(i, str(uuid.uuid4())) for i in old_ids]
        cid = codes.get(s['code_id'])
        if s['code_id'] and not cid: raise ValueError('语码标记缺少语言目录')
        sid = str(uuid.uuid4()); maps[s['id']] = sid
        db.execute('INSERT INTO code_spans VALUES(?,?,?,?,?,?,?,?,1)', (sid, kind, rid, lid, cid, dump(ids), dump({new: snap[old] for old, new in zip(old_ids, ids)}), s.get('notes', '')))
    for r in __import__('long_tasks').steps(bundle.get('code_time_links', [])):
        if r['span_id'] not in maps or r['interval_id'] not in intervals: raise ValueError('语码时间关联缺少正文或时间片段')
        db.execute('INSERT INTO code_time_links VALUES(?,?,?,1)', (str(uuid.uuid4()), maps[r['span_id']], intervals[r['interval_id']]))
    validate(db)
