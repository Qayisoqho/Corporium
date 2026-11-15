"""Explicit basic-form provenance, materialized at the existing dictionary writes."""
import json


def normalize_source(value, *, stored=False):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'analysis_id', 'joiner'}:
        raise ValueError('请选择基本词形的语素分析来源')
    analysis_id = value.get('analysis_id')
    joiner = value.get('joiner', '')
    if not isinstance(analysis_id, str) or not analysis_id:
        raise ValueError('请选择基本词形的语素分析来源')
    # Older versions accepted these Unicode separators. Checking an existing
    # database must leave those forms readable and allow other entries to save.
    if (not isinstance(joiner, str) or len(joiner) > 32 or
            any(ord(c) < 32 or (not stored and c in '\x85\u2028\u2029') for c in joiner)):
        raise ValueError('词形连接符须为不超过32个字符的单行文本')
    return dict(analysis_id=analysis_id, joiner=joiner)


def normalize_body(source, result):
    if 'headword_source' in source:
        result['headword_source'] = normalize_source(source['headword_source'])
    return result


def realization(body, *, stored=False):
    source = normalize_source(body.get('headword_source'),stored=stored)
    if source is None:
        return None
    analysis = next((a for a in body.get('word_structure', {}).get('analyses', [])
                     if a['id'] == source['analysis_id']), None)
    if analysis is None:
        raise ValueError('基本词形引用的语素分析已不存在，请选择分析或改用独立词形')
    components = analysis.get('components', [])
    parents = {c.get('parent_id') for c in components if c.get('parent_id')}
    leaves = [c for c in components if c['id'] not in parents]
    if not leaves:
        raise ValueError('请至少填写一个用于生成基本词形的语素格')
    forms = []
    for component in leaves:
        form = component.get('form', '')
        if not isinstance(form, str) or not form.strip() or component.get('segments'):
            raise ValueError('基本词形须使用有明确形式的连续语素格；不连续分析可使用独立词形')
        forms.append(form)
    return source['joiner'].join(forms).strip()


def apply(db, lid, headword, body, old=None):
    derived = realization(body)
    if derived is None:
        return headword
    if not old or not old['body'].get('headword_source'):
        row = db.execute('SELECT metadata FROM languages WHERE id=?', (lid,)).fetchone()
        if row is None or json.loads(row[0]).get('chinese_mode') is not True:
            raise ValueError('请先为所属语言开启汉语模式')
    return derived


def write_body(db, row, body):
    """Update a derived owner's materialized spelling, including homonym numbers."""
    if row['target_kind'] != 'lexeme' or not body.get('headword_source'):
        return False
    import dictionary_rows
    current = db.execute('SELECT id,language_id,headword,revision FROM lexemes WHERE id=?', (row['id'],)).fetchone()
    if current is None:
        raise ValueError('词条已不存在')
    old = {**dict(current), 'body': dictionary_rows.raw_bodies(db,'lexeme',[row['id']])[row['id']]}
    form = realization(body)
    if old['headword'] != form:
        import homonyms
        confirmation = homonyms.plan(db, old['language_id'], form, old['id'])['token']
        homonyms.prepare(db, old['language_id'], form, body, old, confirmation)
    dictionary_rows.write(db,'lexeme',row['id'],body,columns=dict(headword=form))
    if old['headword'] != form:
        homonyms.clear_singleton(db, old['language_id'], old['headword'])
    return True
