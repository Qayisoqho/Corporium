"""Free meaning text and optional literal tag additions stay separate in storage."""
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
    seen={p.casefold() for p in parts}
    for atom in extra.split('.'):
        if atom and atom.casefold() not in seen:parts.append(atom);seen.add(atom.casefold())
    return '.'.join(parts)
