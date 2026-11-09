"""Occurrence-local code addresses and read-only interlinear cell projections.

Word IDs survive reordering. Within them a saved form and explicit segmentation
shape are required: a new positional cell must never inherit an old code by guess.
The snapshot lives in code_spans; no display fields are written to source words.
"""
import copy
import json


def address(word_id, key):
    return json.dumps([word_id, key], ensure_ascii=False, separators=(',', ':'))


def shape(unit):
    return {k: copy.deepcopy(unit.get(k, [] if k in ('members', 'fragments') else ''))
            for k in ('key', 'kind', 'form', 'members', 'fragments')}


def modern(snapshot):
    return isinstance(snapshot, dict) and snapshot.get('version') == 2


def matching(saved, word, unit):
    return modern(saved) and saved['form'] == word['form'] and unit['shape'] in saved['units']


def saved_text(value):
    if isinstance(value, str):
        return value
    return ' · '.join(u['form'] for u in value['units'])


def snapshot(word, units):
    return dict(version=2, form=word['form'], units=[copy.deepcopy(u['shape']) for u in units])


def validate(value):
    if isinstance(value, str):
        return True  # Historical whole-word evidence.
    if not modern(value) or not isinstance(value.get('form'), str):
        return False
    units = value.get('units')
    if not isinstance(units, list) or not units or len(units) > 10000:
        return False
    keys = set()
    for u in units:
        if not isinstance(u, dict) or any(not isinstance(u.get(k), str) for k in ('key', 'kind', 'form')):
            return False
        if not u['key'] or u['key'] in keys or not isinstance(u.get('members'), list) or any(not isinstance(k, str) for k in u['members']):
            return False
        keys.add(u['key'])
        if not isinstance(u.get('fragments'), list) or not u['fragments']:
            return False
        for f in u['fragments']:
            if (not isinstance(f, dict) or not isinstance(f.get('text'), str)
                    or type(f.get('start')) is not int or type(f.get('end')) is not int
                    or not 0 <= f['start'] <= f['end'] <= 1000000):
                return False
    return True


def overlaps(a, b):
    """Old word marks reserve the whole word; new marks reserve logical units."""
    if isinstance(a, str) or isinstance(b, str):
        return True
    return bool({u['key'] for u in a['units']} & {u['key'] for u in b['units']})


def layout(data):
    import corpus
    import segmentation
    from morpheme_colors import plain_map
    body = corpus.analyze(copy.deepcopy(data['body']))
    result = []
    for info, w in zip(data['words'], body.get('words', [])):
        live = bool(w['form'].strip()) and not corpus.boundary_count(w['form']) and not w.get('punctuation')
        word = {**info, 'form': w['form'], 'live': live, 'selectable': False, 'morphemes': [], 'cells': []}
        result.append(word)
        if not live or not w.get('morphemes') or w.get('infix_ambiguous'):
            continue
        units = {u['key']: u for u in w['morphemes']}
        owners = {k: u['key'] for u in units.values() for k in u.get('members', [u['key']])}
        _, fm = plain_map(w['form']); _, gm = plain_map(w['gloss'])

        def span(f, mapping):
            a, z = f['start'], f['end']
            if not 0 <= a <= z <= len(mapping):
                raise ValueError('invalid fragment')
            if a == z:
                p = mapping[a][0] if a < len(mapping) else mapping[-1][1] if mapping else 0
                return [p, p]
            return [mapping[a][0], mapping[z - 1][1]]

        try:
            pieces = []
            # Include zero-width host slots around an infix. A host's gloss may
            # occur only once (so<l>ma / home<PL>); that must not make the actual
            # infix or its discontinuous host unselectable or duplicate its text.
            fs = segmentation.split_parts(corpus.clean(w['form']), not w.get('_legacy_tilde', False))
            gs = segmentation.split_parts(corpus.clean(w['gloss']), not w.get('_legacy_tilde', False))
            hosts = [u for u in w['segments'] if u['kind'] != 'infix']
            for host, (f, fo, _), (g, go, _) in zip(hosts, fs, gs):
                fg, _ = segmentation.angles(f); gg, _ = segmentation.angles(g, True)
                fa = ga = 0
                for j in range(len(fg) + 1):
                    fz = fg[j][0] if j < len(fg) else len(f)
                    gz = gg[j][0] if j < len(gg) else len(g)
                    if fz > fa or gz > ga:
                        pieces.append(dict(form=span(dict(start=fo + fa, end=fo + fz), fm),
                            gloss=span(dict(start=go + ga, end=go + gz), gm),
                            key=owners.get(host['key']), grammatical=False))
                    if j == len(fg): break
                    a, z, _ = fg[j]; b, e, _ = gg[j]
                    key = host['key'].replace(':host', ':infix:' + str(j))
                    pieces.append(dict(form=span(dict(start=fo + a + 1, end=fo + z - 1), fm),
                        gloss=span(dict(start=go + b + 1, end=go + e - 1), gm), key=owners.get(key), grammatical=True))
                    fa, ga = z, e
            pieces.sort(key=lambda p: p['form'])
            cells = []; fa = ga = 0
            for p in pieces:
                fz, gz = p['form'][0], p['gloss'][0]
                if fz < fa or gz < ga:
                    raise ValueError('overlapping script fragments')
                if fz > fa or gz > ga:
                    cells.append(dict(form=[fa, fz], gloss=[ga, gz], key=None, grammatical=False))
                cells.append(p); fa, ga = p['form'][1], p['gloss'][1]
            if fa < len(w['form']) or ga < len(w['gloss']):
                cells.append(dict(form=[fa, len(w['form'])], gloss=[ga, len(w['gloss'])], key=None, grammatical=False))
            word['cells'] = cells
            for u in units.values():
                if not u.get('lookup_form', u['form']).strip() or not any(c['key'] == u['key'] for c in cells):
                    continue
                word['morphemes'].append(dict(id=address(info['id'], u['key']), key=u['key'], shape=shape(u),
                    form=u.get('display_form', u['form']), gloss=u.get('display_gloss', u['gloss']), kind=u['kind']))
            selectable = {u['key'] for u in word['morphemes']}
            for cell in cells:
                if cell['key'] not in selectable: cell['key'] = None
            word['selectable'] = bool(word['morphemes'])
        except (ValueError, IndexError, KeyError):
            # Unsupported/mismatched analyses keep their legacy evidence and
            # ordinary reading. The editor offers resegmentation, not a guess.
            word['cells'] = []; word['morphemes'] = []
    return result
