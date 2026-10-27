"""Derived, incrementally refreshed lookup of linked word analyses.

The index is disposable: links, meanings and source revisions are always read
again for the preview. It is deliberately absent from business-data backups
and undo tables. SQLite triggers also cover undo, restores and external edits.
"""
import copy
import hashlib
import json
import unicodedata

import corpus
import lexicon
import morphology
import paradigms
import segmentation
import word_transfer
import reduplication

MARKERS=segmentation.FORM_MARKERS
INDEX_VERSION='word-analysis-markers-v2'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def form_key(form, boundaries=MARKERS):
    # Only the explicitly selected morphology markers are ignored. Keep tone,
    # punctuation and authored formatting, so replacement cannot alter them.
    value=unicodedata.normalize('NFC', form).replace(r'\~','~')
    out=[];square=0
    for char in value:
        if char=='[':square+=1
        if square or char not in boundaries:out.append(char)
        if char==']':square=max(0,square-1)
    return ''.join(out)


def drop_triggers(db):
    """Remove only our derived triggers from portable database snapshots.

    Restore must keep rejecting supplied SQL triggers; startup recreates these
    from trusted application code, rather than trusting their backup contents.
    """
    for table in ('entries', 'dictionary_examples'):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            db.execute(f'DROP TRIGGER IF EXISTS word_memory_{table}_{event}')
    db.execute('DROP TRIGGER IF EXISTS word_memory_text_language')


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS word_analysis_index(
          kind TEXT,owner_id TEXT,position INTEGER,word_id TEXT,language_id TEXT,
          form_key TEXT,structure TEXT,PRIMARY KEY(kind,owner_id,position));
        CREATE INDEX IF NOT EXISTS word_analysis_form ON word_analysis_index(language_id,form_key);
        CREATE TABLE IF NOT EXISTS word_analysis_dirty(kind TEXT,owner_id TEXT,PRIMARY KEY(kind,owner_id));
        CREATE TABLE IF NOT EXISTS word_analysis_owners(kind TEXT,owner_id TEXT,PRIMARY KEY(kind,owner_id));
        CREATE TABLE IF NOT EXISTS word_analysis_version(value TEXT PRIMARY KEY);
    ''')
    if not db.execute('SELECT 1 FROM word_analysis_version WHERE value=?',(INDEX_VERSION,)).fetchone():
        db.execute('DELETE FROM word_analysis_index');db.execute('DELETE FROM word_analysis_owners')
        db.execute('DELETE FROM word_analysis_version');db.execute('INSERT INTO word_analysis_version VALUES(?)',(INDEX_VERSION,))
    for table, kind in (('entries', 'corpus'), ('dictionary_examples', 'independent')):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            ref = 'OLD' if event == 'DELETE' else 'NEW'
            # WHERE avoids trigger conflict policies being overridden by an
            # outer INSERT ... ON CONFLICT DO UPDATE used by sentence saves.
            db.execute(f'DROP TRIGGER IF EXISTS word_memory_{table}_{event}')
            db.execute(f'''CREATE TRIGGER word_memory_{table}_{event}
                AFTER {event} ON {table} BEGIN
                INSERT INTO word_analysis_dirty SELECT '{kind}',{ref}.id
                WHERE NOT EXISTS(SELECT 1 FROM word_analysis_dirty WHERE kind='{kind}' AND owner_id={ref}.id); END''')
        db.execute(f'''INSERT OR IGNORE INTO word_analysis_dirty SELECT '{kind}',id FROM {table}
            WHERE NOT EXISTS(SELECT 1 FROM word_analysis_owners WHERE kind=? AND owner_id={table}.id)''', (kind,))
    db.execute('DROP TRIGGER IF EXISTS word_memory_text_language')
    db.execute('''CREATE TRIGGER word_memory_text_language AFTER UPDATE OF language_id ON texts
        BEGIN INSERT INTO word_analysis_dirty SELECT 'corpus',id FROM entries e WHERE text_id=NEW.id
        AND NOT EXISTS(SELECT 1 FROM word_analysis_dirty WHERE kind='corpus' AND owner_id=e.id); END''')


def refresh(db):
    import long_tasks
    # Bounded batches keep a large first index from retaining all sentence JSON.
    while True:
        dirty = db.execute('SELECT * FROM word_analysis_dirty LIMIT 200').fetchall()
        if not dirty:
            return
        for item in long_tasks.steps(dirty):
            kind, rid = item['kind'], item['owner_id']
            if kind == 'corpus':
                row = db.execute('SELECT e.body,t.language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?', (rid,)).fetchone()
                ids = {r['position']: r['id'] for r in db.execute("SELECT id,position FROM corpus_units WHERE entry_id=? AND active=1 AND kind='word'", (rid,))}
            else:
                row = db.execute('SELECT body,language_id FROM dictionary_examples WHERE id=?', (rid,)).fetchone()
                ids = {}
            db.execute('DELETE FROM word_analysis_index WHERE kind=? AND owner_id=?', (kind, rid))
            if row:
                body = json.loads(row['body'])
                lid = body.get('language_id') or row['language_id']
                for i, word in enumerate(body.get('words', [])):
                    if not word.get('form', '').strip():
                        continue
                    raw = {k: word[k] for k in ('form', 'gloss','morph_groups','infix_confirmation') if k in word}
                    # Relations remain separate from spelling. Preserve their
                    # semantic identity when grouping occurrences for lookup.
                    if word.get('redup_id'):
                        raw['reduplications']=[r for r in body.get('reduplications',[]) if any(r[n]['word_id']==word['redup_id'] for n in ('source','base'))]
                    db.execute('INSERT INTO word_analysis_index VALUES(?,?,?,?,?,?,?)',
                        (kind, rid, i, ids.get(i) if kind == 'corpus' else word.get('annotation_id'), lid,
                         form_key(word['form']), encoded(raw)))
                db.execute('INSERT OR IGNORE INTO word_analysis_owners VALUES(?,?)', (kind, rid))
            else:
                db.execute('DELETE FROM word_analysis_owners WHERE kind=? AND owner_id=?', (kind, rid))
            db.execute('DELETE FROM word_analysis_dirty WHERE kind=? AND owner_id=?', (kind, rid))


def candidates(db, destination, boundaries=MARKERS, notices=None):
    """Only complete, live, non-overridden associations provide reusable analyses."""
    wanted = {}
    for w in destination['body']['words']:
        if w.get('unit_type') == 'word' and not corpus.clean(w['gloss']).strip(' '+MARKERS):
            wanted.setdefault(form_key(w['form']), set()).add(form_key(w['form'], boundaries))
    if not wanted:
        return {}
    refresh(db)
    groups = {}
    for key in sorted(wanted):
        # Bindings separate identical-looking homonyms and analyses. The actual
        # link/form/features are checked and included below before offering one.
        rows = db.execute('''WITH hits AS MATERIALIZED (SELECT w.*,
            (SELECT json_group_array(json_array(unit_key,meaning_id,mode,override_text,pattern))
             FROM (SELECT * FROM gloss_bindings b WHERE b.owner_kind=w.kind AND b.owner_id=w.owner_id
                   AND b.word_id=w.word_id ORDER BY unit_key)) bindings,
            CASE WHEN w.kind='corpus' THEN
              (SELECT json_group_array(json_array(l.lexeme_id,l.usage_id,l.sense_id,a.form_id,a.features,s.body,c.body,r.reason))
               FROM corpus_units u JOIN lexical_links l ON l.unit_id=u.id
               LEFT JOIN morphology_analyses a ON a.id=l.id LEFT JOIN unit_segments s ON s.id=u.id
               LEFT JOIN component_links c ON c.id=l.id LEFT JOIN lexical_reviews r ON r.id=l.id
               WHERE u.active=1 AND (u.id=w.word_id OR u.parent_id=w.word_id))
            ELSE (SELECT json_group_array(json_object(
                'lexeme_id',json_extract(t.value,'$.lexeme_id'), 'usage_id',json_extract(t.value,'$.usage_id'),
                'sense_id',json_extract(t.value,'$.sense_id'), 'form_id',json_extract(t.value,'$.form_id'),
                'features',json_extract(t.value,'$.features'), 'component_ref',json_extract(t.value,'$.component_ref'),
                'segmentation_review',json_extract(t.value,'$.segmentation_review'),
                'reference',json_remove(json_extract(t.value,'$.segmentation_ref'),'$.word'),
                'key',json_extract(t.value,'$.segmentation_ref.key'),
                'detached',json_extract(t.value,'$.segmentation_ref.detached')))
                FROM json_each((SELECT body FROM dictionary_examples WHERE id=w.owner_id),'$.targets') t
                WHERE json_extract(t.value,'$.segmentation_ref.word')=w.position) END links
            FROM word_analysis_index w WHERE language_id=? AND form_key=?
            AND NOT(w.kind=? AND w.owner_id=?)
            AND NOT EXISTS(SELECT 1 FROM code_spans s WHERE s.owner_kind=w.kind AND s.record_id=w.owner_id)
            ) SELECT *,COUNT(*) occurrence_count FROM hits GROUP BY structure,bindings,links
            ORDER BY kind,owner_id,position''',
            (destination['language_id'], key, destination['kind'], destination['id']))
        for row in rows:
            if not row['links'] or row['links'] == '[]' or row['bindings'] == '[]':
                continue
            bindings = json.loads(row['bindings'])
            if any(b[2] != 'inherit' for b in bindings):
                continue  # A local wording decision must not become a default.
            structure = json.loads(row['structure'])
            if form_key(structure['form'], boundaries) not in wanted[key]:
                continue
            links = json.loads(row['links'])
            identity = encoded([structure, bindings, links])
            group = groups.setdefault(identity, dict(row=row, count=0, sources=[]))
            group['count'] += row['occurrence_count']
            if len(group['sources']) < 3:
                group['sources'].append(dict(kind=row['kind'], id=row['owner_id'], word=row['position']))
    result = {}
    target_cache = {}
    for group in groups.values():
        row = group['row']
        try:
            d = segmentation.get(db, row['kind'], row['owner_id'])
            w = d['body']['words'][row['position']]
            if d['language_id'] != destination['language_id'] or w.get('unit_type') != 'word' or w.get('group_reviews') or w.get('infix_ambiguous'):
                continue
            links = word_transfer.word_links(db, d, row['position'])
            if not links or any(t.get('review_reason') or t.get('segmentation_review') for t in links):
                continue
            # Copy word-local reduplication only. Cross-word endpoints cannot be
            # retargeted to an unrelated word merely because its spelling fits.
            relations=[r for r in d['body'].get('reduplications',[]) if w.get('redup_id') and any(r[n]['word_id']==w['redup_id'] for n in ('source','base'))]
            if any(any(r[n]['word_id']!=w.get('redup_id') for n in ('source','base')) or
                   any(reduplication.locate(d['body'],r[n]) is None for n in ('source','base')) for r in relations):
                if notices is not None:
                    notices[form_key(w['form'])]='匹配到的重叠分析含跨词格或失效基底，请在本句形态分析中确认基底'
                continue
            keys = [t['segmentation_ref']['key'] for t in links]
            morphs = w.get('morphemes', [])
            if len(keys) != len(set(keys)) or not morphs or any(not m['gloss'].strip() for m in morphs):
                continue
            if '@word' in keys:
                if len(keys) != 1:
                    continue
            elif set(keys) != {m['key'] for m in morphs}:
                continue
            checked, meanings = [], []
            for t in sorted(links, key=lambda t: t['segmentation_ref']['key']):
                xid = t['lexeme_id']
                if xid not in target_cache:
                    target_cache[xid] = lexicon.get_lexeme(db, xid)
                x = target_cache[xid]
                usage, sense = lexicon.selection(x['body'], t.get('usage_id'), t.get('sense_id'))
                if x['language_id'] != d['language_id'] or not sense:
                    raise ValueError('invalid association')
                paradigms.validate_selection(x['body'], t.get('usage_id'), t.get('sense_id'), t.get('form_id'))
                morphology.form_selection(x['body'], t.get('form_id'))
                morphology.check_features(db, d['language_id'], t.get('features', []))
                component=t.get('component_ref')
                if component and morphology.component_links.review(x['body'],component):raise ValueError('invalid component')
                label = str(x['body']['usages'].index(usage)+1)+'.'+str(usage['senses'].index(sense)+1)
                meanings.append(x['headword']+(' '+str(x['body']['homonym_number']) if x['body'].get('homonym_number') else '')
                    +' / '+label+(' · '+sense['definition'] if sense.get('definition') else ''))
                checked.append(dict(key=t['segmentation_ref']['key'], lexeme_id=xid,
                    lexeme_revision=x['revision'], usage_id=t.get('usage_id'), sense_id=t.get('sense_id'),
                    form_id=t.get('form_id'), features=t.get('features', []),
                    **(dict(component_selection={k:component[k] for k in ('analysis_id','component_id')}) if component else {})))
            structure={k:copy.deepcopy(w[k]) for k in ('morph_groups','infix_confirmation') if k in w}
            if relations:
                structure['redup_id']=w['redup_id'];structure['reduplications']=copy.deepcopy(relations)
            # Group IDs and local relation IDs are occurrence identities. Make
            # the preview canonical; accepting it assigns fresh identities.
            group_ids={g['id']:'memory-group-'+str(i) for i,g in enumerate(structure.get('morph_groups',[]))}
            for g in structure.get('morph_groups',[]):g['id']=group_ids[g['id']]
            for t in checked:
                if t['key'].startswith('group:'):t['key']='group:'+group_ids[t['key'][6:]]
            if relations:
                structure['redup_id']='memory-word'
                for i,r in enumerate(structure['reduplications']):
                    r['id']='memory-redup-'+str(i)
                    for n in ('source','base'):
                        r[n]['word_id']='memory-word'
                        if r[n]['key'].startswith('group:'):r[n]['key']='group:'+group_ids[r[n]['key'][6:]]
            value = dict(form=w['form'], gloss=w['gloss'], links=checked,structure=structure)
            cid = hashlib.sha256(encoded(value).encode()).hexdigest()
            cs = result.setdefault(form_key(w['form']), {})
            if cid in cs:
                cs[cid]['count'] += group['count']
                continue
            cs[cid] = dict(id=cid, **value, count=group['count'], sources=group['sources'],
                meanings=meanings,
                source_revision=d['revision'], source_ipa=d['body'].get('ipa', ''),
                source_translation=d['body'].get('translation', ''), reason='复用已有整词分析')
        except (ValueError, KeyError, IndexError):
            # A stale/unresolved source is never proposed as trusted analysis.
            continue
    return {key: list(cs.values()) for key, cs in result.items()}


def eligible(db, d, i, w):
    if corpus.clean(w['gloss']).strip(' '+MARKERS) or any(w.get(k) for k in ('morph_groups', 'infix_confirmation', 'redup_id')):
        return False
    if any(d['words'][i]['id'] in json.loads(r[0]) for r in db.execute(
            'SELECT word_ids FROM code_spans WHERE owner_kind=? AND record_id=?', (d['kind'], d['id']))):
        return False
    try:
        return not word_transfer.word_links(db, d, i)
    except ValueError:
        return False


def replacement(word, candidate, body=None):
    out = copy.deepcopy(word)
    out.update(form=candidate['form'], gloss=candidate['gloss'])
    import uuid
    fields=copy.deepcopy(candidate.get('structure',{}));links=copy.deepcopy(candidate['links'])
    group_ids={g['id']:str(uuid.uuid4()) for g in fields.get('morph_groups',[])}
    for g in fields.get('morph_groups',[]):g['id']=group_ids[g['id']]
    for t in links:
        if t['key'].startswith('group:'):t['key']='group:'+group_ids[t['key'][6:]]
    relations=fields.pop('reduplications',[])
    out.update(fields)
    if relations:
        if body is None:raise ValueError('重叠分析需要目标句子')
        red_id=str(uuid.uuid4());out['redup_id']=red_id
        for r in relations:
            r['id']=str(uuid.uuid4())
            for n in ('source','base'):
                r[n]['word_id']=red_id
                if r[n]['key'].startswith('group:'):r[n]['key']='group:'+group_ids[r[n]['key'][6:]]
        body.setdefault('reduplications',[]).extend(relations)
    return out,links
