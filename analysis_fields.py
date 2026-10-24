"""Explicit, ID-based research fields; no per-hit database queries."""
import categories
import grammar

PREFIXES=('layer_word','layer_sentence','writing','class','usage_tag')
KINDS={'pos':'词类','morph':'形态类','form':'形式分类','grammar':'语法标签分类','usage_tag':'使用标签'}

def custom(field):return isinstance(field,str) and field.partition(':')[0] in PREFIXES and bool(field.partition(':')[2])
def sentence(field):return field.startswith('layer_sentence:')

def catalog(db,lid):
    result=[]
    languages={r['id']:r['name'] for r in db.execute('SELECT id,name FROM languages')}
    for table in ('annotation_layers','writing_types','category_classes'):
        for row in db.execute('SELECT * FROM '+table+' WHERE (?=\'all\' OR language_id=?) ORDER BY rowid',(lid,lid)):
            r=dict(row)
            if table=='annotation_layers':
                prefix='layer_word' if r['anchor']=='word' else 'layer_sentence';group='词级额外标注层' if r['anchor']=='word' else '整句额外标注层'
            elif table=='writing_types':prefix='writing';group='关联词条书写'
            else:
                if r['kind'] not in KINDS:continue
                prefix='usage_tag' if r['kind']=='usage_tag' else 'class';group=KINDS[r['kind']]
            result.append(dict(r,field=prefix+':'+r['id'],group=group,label=r['name']+(' · '+languages.get(r['language_id'],'') if lid=='all' else '')))
    names={r['id']:r['name'] for r in result}
    for r in result:
        if r.get('parent_id') in names:r['label']=names[r['parent_id']]+' / '+r['label']
    return result

def prepare(db,lid,q):
    available={r['field']:r for r in catalog(db,lid)}
    for c in q.get('conditions',[]):
        if custom(c['field']):
            r=available.get(c['field'])
            if not r:raise ValueError('自定义检索字段已删除或不属于当前语言，请重新选择')
            c['label']=r['group']+' · '+r['label']
    return q

class Context:
    def __init__(self,db,q):
        self.defs={r['field']:r for r in catalog(db,'all')}
        self.classes={r['id']:r for r in self.defs.values() if r['field'].startswith(('class:','usage_tag:'))}
        self.by_name={(r['language_id'],r['kind'],r['name']):r['id'] for r in self.classes.values()}
        self.cells={}
        wanted={c['field'].partition(':')[2] for c in q['conditions'] if c['field'].startswith(('layer_word:','layer_sentence:'))}
        if wanted:
            for r in db.execute("SELECT owner_kind,record_id,unit_id,layer_id,value FROM annotation_cells WHERE layer_id IN ("+','.join('?' for _ in wanted)+')',tuple(wanted)):
                key=('independent:' if r['owner_kind']=='independent' else '')+r['record_id']
                self.cells[(key,r['unit_id'],r['layer_id'])]=r['value']
        self.forms={r['id']:r['form_id'] for r in db.execute('SELECT id,form_id FROM morphology_analyses')} if any(custom(c['field']) for c in q['conditions']) else {}
        self.lookup=grammar.index(grammar.listing(db,'all'))
        self.cache={}

    def linked_values(self,c,links):
        field=c['field'];d=self.defs[field];prefix=field.partition(':')[0];out=[]
        for link,lexeme in links:
            key=(field,link['id'])
            if key not in self.cache:
                import paradigms
                b=lexeme['body'];usage=next((u for u in paradigms.usages(b) if u['id']==link['usage_id']),{})
                variant=next((v for v in b.get('variants',[]) if v['id']==self.forms.get(link['id'])),{})
                sense=next((s for s in usage.get('senses',[]) if s['id']==link['sense_id']),{})
                values=[]
                if prefix=='writing':
                    # Entry-level spellings are properties of the linked lexeme, not of every component in its analyses.
                    values=[w.get('text','') for w in b.get('orthographies',[]) if w.get('type_id')==d['id']]
                elif prefix=='usage_tag':
                    values=[t.get('value','') for owner in (b,usage,variant,sense) for t in owner.get('tags',[]) if categories.TAG_NAMES.get(t.get('type'),t.get('type'))==d['name']]
                elif d['kind']=='morph':
                    values=[m['class_id'] for m in b.get('word_structure',{}).get('memberships',[]) if not m.get('usage_id') or m['usage_id']==usage.get('id')]
                else:
                    names=[usage.get('subclass') or usage.get('pos')] if d['kind']=='pos' else [categories.FORM_NAMES.get(variant.get('kind'),variant.get('kind'))] if d['kind']=='form' else []
                    values=[self.by_name.get((d['language_id'],d['kind'],name),'') for name in names]
                self.cache[key]=[v for v in values if v]
            out.extend(self.cache[key])
        return list(dict.fromkeys(out))

    def matched(self,c,entry,unit,language,links,tags,accepts,case):
        field=c['field'];d=self.defs[field]
        if d['language_id']!=language:return []
        prefix=field.partition(':')[0]
        if prefix.startswith('layer_'):
            values=[self.cells.get((entry,'@sentence' if prefix=='layer_sentence' else unit,d['id']),'')]
        elif prefix=='class' and d['kind']=='grammar':
            rows=[self.lookup.get((language,t.casefold()),{}) for t in tags]
            values=list(dict.fromkeys(self.by_name.get((language,'grammar',r.get('category')),'') for r in rows));values=[v for v in values if v]
        else:values=self.linked_values(c,links)
        if prefix=='class':
            selected={d['id']}
            if c.get('include_children',True):selected.update(r['id'] for r in self.classes.values() if r.get('parent_id')==d['id'])
            matching=[v for v in values if v in selected]
            if c['mode']=='not_belongs':return ['不属于 '+d['name']] if values and not matching else []
            return [self.classes[v]['name'] for v in matching]
        return [v for v in values if v.strip() and accepts(v,c,case)]
