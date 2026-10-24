"""Explicit dictionary intake and blank-gloss completion for one saved sentence."""
import copy
import hashlib
import json
import re
import unicodedata
import uuid

import annotations
import corpus
import dictionary_gloss_sync
import homonyms
import lexicon
import morphology
import paradigms
import morpheme_registry
import segmentation


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def canon(value):
    return unicodedata.normalize('NFC', value)


def completion_form_key(value):
    """Ignore citation hyphens without editing the source or inferring a split.

    Internal hyphens may mark the structure of a dictionary citation form even
    when that form corresponds to one already segmented sentence unit. Other
    citation markers retain the existing edge-only rule. Exact candidates are
    listed first without hiding other matching meanings or forms.
    """
    return canon(value).replace('-', '').strip('=.')


def context(db, b, lid):
    d = segmentation.get(db, b.get('kind'), b.get('id'))
    if d['owner_language'] != lid:
        raise ValueError('例句所属语言已变化，请重新打开')
    if b.get('revision') != d['revision']:
        raise ValueError('例句已修改，请重新打开后重试')
    return d


def unit(word, key):
    if key == '@word':
        return dict(key=key, form=word['form'], gloss=word['gloss'], fragments=[], unit_id=word.get('unit_id'))
    return next((m for m in word.get('morphemes', []) if m['key'] == key), None)


def link_at(db, d, index, key):
    w = d['body']['words'][index]
    u = unit(w, key)
    if d['kind'] == 'corpus':
        return lexicon.unit_info(db, u['unit_id'])['link'] if u and u.get('unit_id') else {}
    matches = [t for t in d['body'].get('targets', [])
               if t.get('segmentation_ref', {}).get('word') == index
               and t['segmentation_ref'].get('key') == key
               and not t['segmentation_ref'].get('detached')]
    if len(matches) > 1:
        return {'review_reason': '此处有多个旧关联，请先核对'}
    if matches and matches[0].get('segmentation_review'):
        return {**matches[0], 'review_reason': '此处的旧关联已失效，请先核对'}
    return copy.deepcopy(matches[0]) if matches else {}


def bind(db, d, index, key, target, lid, previous=None):
    old = link_at(db, d, index, key) if previous is None else previous
    segmentation.link(db, dict(kind=d['kind'], id=d['id'], revision=d['revision'],
        word=index, key=key, link_revision=old.get('revision', 0),
        lexeme_id=target['lexeme_id'], lexeme_revision=target['lexeme_revision'],
        usage_id=target['usage_id'], sense_id=target['sense_id'], form_id=target.get('form_id'),
        features=old.get('features', []), notes=old.get('notes', '')), lid)


def intake_preview(db, b, lid):
    d = context(db, b, lid)
    index = b.get('word')
    if type(index) is not int or not 0 <= index < len(d['body']['words']):
        raise ValueError('请选择当前词格')
    w = d['body']['words'][index]
    u = unit(w, b.get('key'))
    if not u or w.get('unit_type') != 'word' or not u['form'].strip():
        raise ValueError('请选择有效的整词、语素或已确认组合')
    old = link_at(db, d, index, b['key'])
    target = lexicon.get_lexeme(db, b['target_id']) if b.get('target_id') else None
    if target and target['language_id'] != d['language_id']:
        raise ValueError('不能关联其他语言的词典条目')
    form = lexicon.text(b.get('form', u['form'])).strip()
    normalized_form = canon(form)
    peers = []
    for row in db.execute('SELECT id,headword,revision,target_kind FROM dictionary_targets WHERE language_id=?', (d['language_id'],)):
        if canon(row['headword']) == normalized_form:
            peers.append(dict(row))
    data = dict(kind=d['kind'], id=d['id'], revision=d['revision'], word=index, key=b['key'],
                language_id=d['language_id'], owner_language=lid, source_form=u['form'],
                source_gloss=u.get('display_gloss', u['gloss']), linked=bool(old), peers=peers, target=target)
    # Bind the source association, chosen target, and reviewed fields as well as revisions.
    data['token'] = digest([data, old, {k: b.get(k) for k in
        ('mode', 'target_kind', 'entry_type', 'form', 'gloss', 'pos', 'usage_id', 'sense_id', 'form_id', 'query')}])
    # A search result is not part of the saved decision. Recheck only the source,
    # selected target and same-form peers when saving, never the whole catalog.
    if b.get('include_items', True):
        query = lexicon.text(b.get('query', u['form'])).strip()
        result = lexicon.list_lexemes(db, d['language_id'], query, page_size=30, targets=True, counts=False)
        data.update(items=result['items'], total=result['total'])
    return data


def save_target(db, x, body):
    if x['target_kind'] == 'lexeme':
        return lexicon.mutate(db, 'lexeme-save', dict(id=x['id'], revision=x['revision'], headword=x['headword'], body=body), x['language_id'])
    morpheme_registry.mutate(db, 'morpheme-save', dict(id=x['id'], revision=x['revision'], form=x['headword'], body=body), x['language_id'])
    return lexicon.get_lexeme(db, x['id'])


def intake_apply(db, b, lid):
    p = intake_preview(db, {**b, 'include_items': False}, lid)
    if b.get('token') != p['token']:
        raise ValueError('录入内容或关联已变化，请重新核对')
    if p['linked'] and b.get('replace_link') is not True:
        raise ValueError('此处已有词典关联，请明确确认替换关联')
    d = context(db, b, lid)
    mode = b.get('mode', 'new')
    form = lexicon.text(b.get('form', '')).strip()
    gloss = lexicon.text(b.get('gloss', '')).strip()
    x = p['target']
    uid, sid, fid = b.get('usage_id') or None, b.get('sense_id') or None, b.get('form_id') or None
    if mode == 'new':
        if not form or not gloss:
            raise ValueError('请填写词形与简短标注')
        if p['peers'] and b.get('confirm_homonym') is not True:
            raise ValueError('存在同形条目，请确认建立独立记录')
        kind = b.get('target_kind', 'lexeme')
        if kind == 'lexeme':
            uid, sid = str(uuid.uuid4()), str(uuid.uuid4())
            x = lexicon.mutate(db, 'lexeme-save', dict(headword=form,
                homonym_confirmation=homonyms.plan(db, d['language_id'], form)['token'],
                body=dict(entry_type=b.get('entry_type', 'unspecified'), usages=[dict(id=uid,
                    pos=lexicon.text(b.get('pos', '')), senses=[dict(id=sid, short_gloss=gloss)])])), d['language_id'])
        elif kind == 'morpheme':
            m = morpheme_registry.mutate(db, 'morpheme-save', dict(form=form,
                body=dict(gloss=gloss, entry_type=b.get('entry_type', 'unspecified'))), d['language_id'])
            x = lexicon.get_lexeme(db, m['id']); uid, sid = '@morpheme', '@main'
        else:
            raise ValueError('请选择词条或语素')
        fid = None
    elif mode in ('existing', 'sense', 'variant'):
        if not x:
            raise ValueError('请选择已有条目')
        if mode == 'sense':
            if not gloss:
                raise ValueError('请填写新义项的简短标注')
            sid = str(uuid.uuid4())
            if x['target_kind'] == 'morpheme':
                body = copy.deepcopy(morpheme_registry.get(db, x['id'])['body'])
                body.setdefault('senses', []).append(dict(id=sid, gloss=gloss))
                if body.get('primary_sense_id'):
                    u, _ = lexicon.selection(x['body'], uid, None)
                    if not u:raise ValueError('请选择意义分组')
                    next(v for v in body['usages'] if v['id'] == uid)['senses'].append(dict(id=sid, short_gloss=gloss))
                else:uid = '@morpheme'
            else:
                body = copy.deepcopy(x['body'])
                if uid:
                    u, _ = lexicon.selection(body, uid, None)
                else:
                    uid = str(uuid.uuid4()); u = dict(id=uid, pos=lexicon.text(b.get('pos', '')), senses=[])
                    body['usages'].append(u)
                u['senses'].append(dict(id=sid, short_gloss=gloss))
            x = save_target(db, x, body)
        elif mode == 'variant':
            if not form:raise ValueError('请填写变体形式')
            if canon(form) in {canon(x['headword']), *(canon(v['form']) for v in x['body'].get('variants', []))}:
                raise ValueError('此形式已登记，请直接选择已有形式')
            fid = str(uuid.uuid4())
            body = copy.deepcopy(x['body'] if x['target_kind'] == 'lexeme' else morpheme_registry.get(db, x['id'])['body'])
            body.setdefault('variants', []).append(dict(id=fid, form=form, variation='unknown', kind='other'))
            x = save_target(db, x, body)
        _, sense = lexicon.selection(x['body'], uid, sid)
        if not sense:raise ValueError('请选择具体义项或意义／功能')
        morphology.form_selection(x['body'], fid)
    else:
        raise ValueError('录入方式无效')
    bind(db, d, b['word'], b['key'], dict(lexeme_id=x['id'], lexeme_revision=x['revision'],
         usage_id=uid, sense_id=sid, form_id=fid), lid)
    return dict(ok=True, id=x['id'], target_kind=x['target_kind'])


def prepared_word(word):
    """Mirror existing explicit boundaries when the entire gloss is empty."""
    w = copy.deepcopy(word)
    if not corpus.clean(w['gloss']).strip() and not w.get('morph_groups') and not w.get('infix_confirmation'):
        form = corpus.clean(w['form'])
        if '<' not in form and '>' not in form:
            w['gloss'] = ''.join(p[2] for p in segmentation.split_parts(form))
            corpus.analyze(dict(ipa='', translation='', words=[w]))
    return w


def candidate(x, usage, sense, form, tags, extra=()):
    features = list(dict.fromkeys([*x['body'].get('features', []), *usage.get('features', []),
        *sense.get('features', []), *(form.get('features', []) if form else []), *extra]))
    value = sense.get('short_gloss', '').strip()
    if not value:return None
    # Existing registered trailing tags are not repeated in the generated label.
    lookup = {canon(t['symbol']).casefold(): t['id'] for t in tags.values()}
    for t in tags.values():
        for alias in t['aliases']:lookup[canon(alias).casefold()] = t['id']
    present = {lookup.get(canon(v).casefold()) for v in re.split(r'[._:;\\]', value)}
    added = [tags[f]['symbol'] for f in features if f in tags and f not in present]
    if added and any(c in value for c in '-=+<>[](){}'):
        return None  # Attaching features to an opaque structure would invent scope.
    value = '.'.join([value, *added])
    c = dict(lexeme_id=x['id'], lexeme_revision=x['revision'], target_kind=x['target_kind'],
        headword=x['headword'], homonym_number=x['body'].get('homonym_number'),
        usage_id=usage['id'], sense_id=sense['id'], form_id=form['id'] if form else None,
        matched_form=form['form'] if form else x['headword'], gloss=value,
        definition=sense.get('definition', ''), pos=usage.get('pos', ''), features=features)
    c['sense_label'] = str(next(i for i,u in enumerate(x['body']['usages'],1) if u['id']==usage['id']))+'.'+str(usage['senses'].index(sense)+1)
    c['id'] = digest([c['lexeme_id'], c['usage_id'], c['sense_id'], c['form_id']])
    return c


def fill_word(word, rules):
    w = copy.deepcopy(word)
    parts = segmentation.split_parts(corpus.clean(w['gloss']))
    # The shared parser represents empty strings with no fragments. Supply their
    # zero-width insertion point, using the already confirmed boundary positions.
    for m in [*w.get('morphemes', []), *w.get('segments', [])]:
        if m['key'] in rules and not m.get('gloss_fragments') and m['kind'] == 'simple':
            at = parts[int(m['key'].split(':')[0])][1]
            m['gloss_fragments'] = [dict(start=at, end=at, text='')]
    return dictionary_gloss_sync.transform(w, rules)


def compatible(word, key, value):
    try:
        new = fill_word(word, {key: ('', value)})
        check_roundtrip(dict(ipa='', translation='', words=[new], function='pass'))
        return True
    except ValueError:
        return False


def check_roundtrip(body):
    check, errors = corpus.parse(corpus.export_entry({**body, 'edited': True, 'function': body.get('function', 'pass')}), analyze_entries=False)
    if errors or len(check) != 1 or [(w['form'], w['gloss']) for w in check[0]['words']] != [(w['form'], w['gloss']) for w in body['words']]:
        raise ValueError('标注包含无法安全导出的结构，请核对括号与语素边界')


def completion_preview(db, b, lid):
    import grammar
    d = context(db, b, lid)
    tags = {t['id']: t for t in grammar.listing(db) if t['language_id'] == d['language_id']}
    targets = {r['id']: {**dict(r), 'body': json.loads(r['body'])} for r in db.execute('SELECT * FROM dictionary_targets WHERE language_id=? ORDER BY id', (d['language_id'],))}
    homonyms.decorate_many(db, [x for x in targets.values() if x['target_kind'] == 'lexeme'])
    exact, relaxed = {}, {}
    for x in targets.values():
        for u,s,f in paradigms.candidates(x['body']):
            c = candidate(x, u, s, f, tags)
            if c:
                exact.setdefault(canon(c['matched_form']), []).append(c)
                relaxed.setdefault(completion_form_key(c['matched_form']), []).append(c)
    rows, skipped, links = [], [], []
    for i, original in enumerate(d['body']['words']):
        if original.get('unit_type') != 'word' or not original['form'].strip():continue
        w = prepared_word(original)
        morphs = w.get('morphemes', [])
        if not morphs or w.get('infix_ambiguous') or w.get('group_reviews'):
            skipped.append(dict(word=i, form=w['form'], reason='语素与标注边界无法可靠对应，请先核对切分'))
            continue
        if len(morphs) == 1 and morphs[0]['form'] == corpus.clean(w['form']):
            # The whole-word reference keeps punctuation for display/storage;
            # matching uses the already analyzed surface form (e.g. kele!).
            units = [{**unit(w, '@word'), 'lookup_form': morphs[0].get('lookup_form', morphs[0]['form'])}]
        else:
            units = morphs
        for m in units:
            if corpus.clean(m['gloss']).strip() or not m['form'].strip():continue
            old = link_at(db, d, i, m['key']); links.append([i, m['key'], old])
            if old.get('review_reason') or old.get('component_review'):
                skipped.append(dict(word=i, form=m['form'], reason='已有失效关联，请先核对'))
                continue
            cs = []
            if old.get('lexeme_id'):
                x = targets.get(old['lexeme_id'])
                if x:
                    for u in paradigms.usages(x['body']):
                        if old.get('usage_id') and u['id'] != old['usage_id']:continue
                        for s in u['senses']:
                            if old.get('sense_id') and s['id'] != old['sense_id']:continue
                            if s.get('paradigm_form_id') and s['paradigm_form_id']!=old.get('form_id'):continue
                            forms = [morphology.form_selection(x['body'], old['form_id'])] if old.get('form_id') else [None]
                            for f in forms:
                                c = candidate(x, u, s, f, tags, old.get('features', []))
                                if c and (old.get('sense_id') or canon(c['matched_form']) == canon(m['form'])):
                                    cs.append({**c, 'reason': '沿用已保存关联', 'relaxed': False})
            else:
                cs = [{**c, 'reason': '形式完全匹配', 'relaxed': False} for c in exact.get(canon(m.get('lookup_form', m['form'])), [])]
                # A bare-form noun must not hide a verb cited with a trailing
                # hyphen (kele / kele-). Preserve exact-first ordering and only
                # deduplicate the same target/meaning/form from both indexes.
                seen = {c['id'] for c in cs}
                for c in relaxed.get(completion_form_key(m.get('lookup_form', m['form'])), []):
                    if c['id'] not in seen:
                        cs.append({**c, 'reason': '忽略词形中的 - 及首尾 = .，确认后填入', 'relaxed': True})
                        seen.add(c['id'])
            cs = [c for c in cs if compatible(w, m['key'], c['gloss'])]
            for c in cs:
                c['citation_match']=lexicon.morpheme_citation_match(c['target_kind'],m.get('lookup_form',m['form']),c['matched_form'])
                if c['relaxed'] and c['citation_match']:c['reason']='语素形式匹配（忽略首尾引用标记），确认后填入'
            rows.append(dict(word=i, key=m['key'], form=m['form'], candidates=cs,
                automatic=len(cs) == 1, linked=bool(old)))
    p = dict(kind=d['kind'], id=d['id'], revision=d['revision'], owner_language=lid,
             language_id=d['language_id'], rows=rows, skipped=skipped)
    p['token'] = digest([p, links, d['words'], annotations.owner(db, d['kind'], d['id'])[0]])
    return p


def completion_apply(db, b, lid):
    p = completion_preview(db, b, lid)
    if b.get('token') != p['token']:
        raise ValueError('例句、词典或关联已变化，请重新预览')
    choices = b.get('choices')
    if not isinstance(choices, list) or not choices:raise ValueError('请选择要填入的标注')
    available = {(r['word'], r['key']): r for r in p['rows']}
    selected, seen = [], set()
    for choice in choices:
        if not isinstance(choice, dict) or type(choice.get('word')) is not int or not isinstance(choice.get('key'), str):
            raise ValueError('标注选择无效')
        key = (choice['word'], choice['key'])
        row = available.get(key)
        c = next((c for c in row['candidates'] if c['id'] == choice.get('candidate_id')), None) if row else None
        if not c or key in seen:raise ValueError('同一处只能选择一个有效候选')
        seen.add(key); selected.append((key, c))
    d = context(db, b, lid)
    original = copy.deepcopy(d['body']); body = copy.deepcopy(original)
    rules = {}
    for (index, key), c in selected:rules.setdefault(index, {})[key] = ('', c['gloss'])
    for i, edits in rules.items():
        body['words'][i] = fill_word(prepared_word(body['words'][i]), edits)
    check_roundtrip(body)
    corpus.analyze(body)
    if d['kind'] == 'independent':
        from text_replace import preserve_independent_refs
        preserve_independent_refs(original, body, list(rules), set())
    else:body['edited'] = True
    table = 'entries' if d['kind'] == 'corpus' else 'dictionary_examples'
    db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?', (json.dumps(body, ensure_ascii=False), d['id']))
    if d['kind'] == 'corpus':
        words = list(db.execute("SELECT id FROM corpus_units WHERE entry_id=? AND kind='word' AND active=1 ORDER BY position", (d['id'],)))
        mids = {w['id']: [m['id'] for m in db.execute("SELECT id FROM corpus_units WHERE parent_id=? AND active=1 ORDER BY position", (w['id'],))] for w in words}
        lexicon.sync_entry(db, d['id'], [w['id'] for w in words], mids, preserve_complex=True)
    for (i, key), c in selected:
        fresh = segmentation.get(db, d['kind'], d['id'])
        bind(db, fresh, i, key, c, lid)
    return dict(ok=True, count=len(selected))
