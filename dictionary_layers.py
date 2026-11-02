"""Read-only annotation tiers projected from explicit current dictionary links."""
import json
from categories import TAG_NAMES

def tag_type(value):
 return next((key for key,name in TAG_NAMES.items() if value==name),value)

FIELDS={
 'pos':('词类','Word class'),'subclass':('词类子类','Word subclass'),
 'entry_type':('条目类型','Entry type'),'short_gloss':('简短释义','Short gloss'),
 'semantic_class':('语义类','Semantic class'),'morph_class':('形态类','Morphological class'),
 'tag:register':('语体／语域','Register'),'tag:region':('地区','Region'),
 'tag:generation':('人群／代际','Social group / generation'),'tag:period':('年代／状态','Period / status'),
 'tag:domain':('领域','Domain'),'tag:other':('其他使用标签','Other usage labels')}
TYPES={'unspecified':('尚未分类','Unclassified'),'word':('词条','Word'),'root':('词根','Root'),'stem':('词干','Stem'),
 'affix':('词缀','Affix'),'clitic':('附着成分','Clitic'),'connector':('连接成分','Linker'),'infix':('中缀','Infix'),
 'circumfix':('环缀','Circumfix'),'multipart':('其他多部分语素','Other multipart'),'expression':('固定表达','Expression')}

def catalog(db,lid):
 fields=[dict(id=key,name=names[0],name_en=names[1]) for key,names in FIELDS.items()]
 for r in db.execute('SELECT id,name,font FROM writing_types WHERE language_id=? ORDER BY position,name',(lid,)):
  fields.append(dict(id='writing:'+r['id'],name='书写形式 · '+r['name'],name_en='Writing · '+r['name'],font=r['font']))
 # Custom usage-label categories are literal strings, scoped to this language.
 kinds={tag_type(r['name']) for r in db.execute("SELECT name FROM category_classes WHERE language_id=? AND kind='usage_tag'",(lid,))}
 def walk(v):
  if isinstance(v,dict):
   for t in v.get('tags',[]):
    if isinstance(t,dict) and isinstance(t.get('type'),str):kinds.add(tag_type(t['type']))
   for key,value in v.items():
    if key!='tags' and isinstance(value,(dict,list)):walk(value)
  elif isinstance(v,list):
   for item in v:walk(item)
 for row in db.execute('SELECT body FROM dictionary_targets WHERE language_id=?',(lid,)):walk(json.loads(row[0]))
 fields.extend(dict(id='tag:'+kind,name='使用标签 · '+kind,name_en='Usage label · '+kind) for kind in sorted(kinds) if 'tag:'+kind not in FIELDS)
 return fields

def configuration(db,b,old,lid,anchor):
 previous=dict(old or {});source=b.get('source',previous.get('source','manual'));field=b.get('dictionary_field',previous.get('dictionary_field',''))
 if source not in ('manual','dictionary'):raise ValueError('标注层内容来源无效')
 if source=='manual':return source,''
 if anchor!='word':raise ValueError('词典信息层须选择逐词位置')
 missing_ok=isinstance(field,str) and field.startswith(('writing:','tag:')) and (previous.get('source')=='dictionary' and previous.get('dictionary_field')==field or b.get('_unavailable_dictionary_field') is True)
 if not isinstance(field,str) or field not in {f['id'] for f in catalog(db,lid)} and not missing_ok:raise ValueError('请选择本语言可用的词典字段')
 if old and previous.get('source','manual')!='dictionary' and db.execute('SELECT 1 FROM annotation_cells WHERE layer_id=?',(old['id'],)).fetchone():raise ValueError('已有手动内容的层不能改为词典信息层，请新建标注层')
 return source,field

def unique(values):return list(dict.fromkeys(v for v in values if isinstance(v,str) and v.strip()))

class Projection:
 def __init__(self,db,body,kind,rid,lid):
  self.db=db;self.body=body;self.lid=lid;self.links={};self.targets={}
  if kind=='corpus':
   sql='''SELECT l.*,COALESCE(p.position,u.position) word_position,u.position morph_position,u.kind,
    a.form_id,a.features,c.body component_ref,r.reason review_reason
    FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id LEFT JOIN corpus_units p ON p.id=u.parent_id
    LEFT JOIN morphology_analyses a ON a.id=l.id LEFT JOIN component_links c ON c.id=l.id LEFT JOIN lexical_reviews r ON r.id=l.id
    WHERE u.entry_id=? AND u.active=1 AND (p.id IS NULL OR p.active=1) ORDER BY u.kind,u.position,l.id'''
   for raw in db.execute(sql,(rid,)):
    row=dict(raw);index=row['word_position']
    if not 0<=index<len(body.get('words',[])):continue
    units=body['words'][index].get('morphemes',[])
    key='@word' if row['kind']=='word' else units[row['morph_position']]['key'] if 0<=row['morph_position']<len(units) else None
    if key is None:continue
    if row['component_ref']:row['component_ref']=json.loads(row['component_ref'])
    self.links.setdefault(index,{}).setdefault(key,[]).append(row)
  else:
   import segmentation
   segmentation.decorate_refs(body)
   for t in body.get('targets',[]):
    ref=t.get('segmentation_ref')
    if not ref or t.get('segmentation_review') or ref.get('detached'):continue
    self.links.setdefault(ref['word'],{}).setdefault(ref['key'],[]).append(t)
  ids={t['lexeme_id'] for groups in self.links.values() for values in groups.values() for t in values}
  for start in range(0,len(ids),300):
   batch=list(ids)[start:start+300]
   for row in db.execute('SELECT id,language_id,headword,body,target_kind FROM dictionary_targets WHERE id IN ('+','.join('?' for _ in batch)+')',batch):
    if row['language_id']==lid:self.targets[row['id']]={**dict(row),'body':json.loads(row['body'])}
  self.classes=None;self.semantic=None;self.writings=None

 def extract(self,target,link,field):
  import paradigms,sense_gloss,component_links
  if link.get('review_reason'):return [],'stale'
  body=target['body'];usages=paradigms.usages(body)
  usage=next((u for u in usages if u['id']==link.get('usage_id')),None)
  sense=next((s for s in (usage or {}).get('senses',[]) if s['id']==link.get('sense_id')),None)
  if link.get('usage_id') and usage is None or link.get('sense_id') and sense is None:return [],'stale'
  ref=link.get('component_ref')
  if ref and component_links.review(body,ref):return [],'stale'
  component=ref.get('snapshot',{}).get('component') if ref else None
  form=next((v for v in body.get('variants',[]) if v['id']==link.get('form_id')),None)
  scopes=[body]+([usage] if usage else [])+([sense] if sense else [])+([component] if component else [])+([form] if form else [])
  if field=='pos':return unique([usage.get('pos','')] if usage else [u.get('pos','') for u in usages]),''
  if field=='subclass':return unique([usage.get('subclass','')] if usage else [u.get('subclass','') for u in usages]),''
  if field=='entry_type':return [body.get('entry_type','unspecified')],''
  if field=='short_gloss':return unique([component.get('gloss','')] if component else [sense_gloss.effective(sense)] if sense else [sense_gloss.effective(s) for u in ([usage] if usage else usages) for s in u.get('senses',[])]),''
  if field.startswith('tag:'):return unique([t.get('value','') for scope in scopes for t in scope.get('tags',[]) if tag_type(t.get('type'))==tag_type(field[4:])]),''
  if field=='semantic_class':
   if self.semantic is None:self.semantic={r['id']:r['name'] for r in self.db.execute('SELECT id,name FROM semantic_classes WHERE language_id=?',(self.lid,))}
   return unique([self.semantic.get(i,'') for i in body.get('semantic_classes',[])]),''
  if field=='morph_class':
   if self.classes is None:self.classes={r['id']:r['name'] for r in self.db.execute("SELECT id,name FROM category_classes WHERE language_id=? AND kind='morph'",(self.lid,))}
   return unique([self.classes.get(m.get('class_id'),'') for m in body.get('word_structure',{}).get('memberships',[]) if not m.get('usage_id') or m.get('usage_id')==link.get('usage_id')]),''
  if field.startswith('writing:'):
   writing=field[8:];rows=component.get('writings',[]) if component else [*form.get('writings',[]),*form.get('orthographies',[])] if form else [*body.get('orthographies',[]),*body.get('writings',[])]
   if form and not component:
    rows=rows+[w for membership in body.get('word_structure',{}).get('memberships',[]) if not membership.get('usage_id') or membership.get('usage_id')==link.get('usage_id') for part in membership.get('parts',[]) if part.get('variant_id')==link.get('form_id') for w in part.get('writings',[])]
   return unique([r.get('text','') for r in rows if r.get('type_id')==writing]),''
  return [],'field_missing'

 def layer(self,index,definition):
  field=definition.get('dictionary_field','');groups=self.links.get(index,{});word=self.body['words'][index]
  if self.writings is None:self.writings={r['id']:dict(r) for r in self.db.execute('SELECT * FROM writing_types WHERE language_id=?',(self.lid,))}
  missing=field.startswith('writing:') and field[8:] not in self.writings
  keys=['@word'] if groups.get('@word') else [m['key'] for m in word.get('morphemes',[])] or ['@word']
  segments=[];all_values=[]
  for key in keys:
   refs=[];values=[];state='field_missing' if missing else 'unlinked'
   for link in groups.get(key,[]):
    target=self.targets.get(link['lexeme_id'])
    if target is None:continue
    found,reason=([],'field_missing') if missing else self.extract(target,link,field)
    if reason:state=reason;continue
    state='value' if found else 'empty';values.extend(found)
    refs.append(dict(id=target['id'],headword=target['headword'],target_kind=target['target_kind'],values=found))
   values=unique(values);all_values.extend(values)
   unit=next((m for m in word.get('morphemes',[]) if m['key']==key),{})
   segments.append(dict(key=key,boundary=unit.get('boundary') or '-',values=values,refs=refs,state='value' if values else state))
  result={**definition,'value':''.join((' '+s['boundary']+' ' if i else '')+(' / '.join(s['values']) if s['values'] else '—') for i,s in enumerate(segments)),
   'derived':True,'segments':segments,'entry_type_labels':{v:TYPES[v] for v in unique(all_values) if v in TYPES} if field=='entry_type' else {}}
  if field.startswith('writing:') and not missing:result['font']=self.writings[field[8:]]['font']
  return result

def project(db,body,kind,rid,lid,definitions,*,linked_only=False):
 derived=[d for d in definitions if d.get('source')=='dictionary']
 if not derived:return body
 resolver=Projection(db,body,kind,rid,lid)
 for index,word in enumerate(body.get('words',[])):
  # Search consumes actual values only; unlinked placeholders cannot match.
  # Normal rendering still constructs every position, including placeholders.
  if linked_only and index not in resolver.links:
   word['extra_layers']=[]
   continue
  existing={l['id']:l for l in word.get('extra_layers',[])}
  for definition in derived:existing[definition['id']]=resolver.layer(index,definition)
  word['extra_layers']=[existing[d['id']] for d in definitions if d.get('anchor','word')=='word' and d['id'] in existing]
 return body

def text(layer,locale='zh-CN'):
 labels=layer.get('entry_type_labels',{});column=1 if locale=='en' else 0
 return ''.join((' '+s.get('boundary','-')+' ' if i else '')+(' / '.join(labels.get(v,(v,v))[column] for v in s['values']) if s['values'] else '—') for i,s in enumerate(layer.get('segments',[]))) if layer.get('derived') else layer.get('value','')

def export_definitions(db,definitions):
 fonts={r['id']:r['font'] for r in db.execute('SELECT id,font FROM writing_types')}
 return [{**d,'font':fonts[d['dictionary_field'][8:]]} if d.get('source')=='dictionary' and d.get('dictionary_field','').startswith('writing:') and d['dictionary_field'][8:] in fonts else d for d in definitions]
