"""Free meaning text and optional literal tag additions stay separate in storage."""
import re

def atoms(value):
    seen={p.casefold() for p in value.split('.')}
    for part in value.split('.'):
        person=re.fullmatch(r'([0-9]+)([A-Za-z][A-Za-z0-9_]*)',part)
        if person:seen.update(p.casefold() for p in person.groups())
    return seen

def join(parts):
    """Person digits join the following label directly: pron.3 + SG -> pron.3SG."""
    value=''
    for atom in parts:
        value+=('' if not value or value[-1] in '0123456789' else '.')+atom
    return value
def normalize(source,target):
    from paradigms import addition
    if 'gloss_addition' in source:target['gloss_addition']=addition(source['gloss_addition'])
    if 'show_gloss_addition' in source:
        if type(source['show_gloss_addition']) is not bool:raise ValueError('附加标签显示设置无效')
        target['show_gloss_addition']=source['show_gloss_addition']
    return target

def effective(sense,field='short_gloss'):
    base=sense.get(field,'')
    extra=sense.get('gloss_addition','') if sense.get('show_gloss_addition',True) else ''
    if not extra:return base
    parts=base.strip().split('.') if base.strip() else []
    seen=atoms(base.strip())
    for atom in extra.split('.'):
        if atom and atom.casefold() not in seen:parts.append(atom);seen.add(atom.casefold())
    return join(parts)
