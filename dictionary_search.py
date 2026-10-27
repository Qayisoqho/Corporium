import long_tasks
"""Field-aware dictionary search. Index user-visible values, never storage IDs."""
import json
import gloss_inheritance
import unicodedata
from collections import defaultdict,OrderedDict
import categories
import grammar
import annotations
import evidence_index
import dictionary_targets
import paradigms
from itertools import islice

HIDDEN_KEYS=frozenset(('gloss_mode','gloss_addition','default_base_sense_id','status','id','font','font_variant','language_id','parent_id','targets','revision','segmentation_ref','token_id','annotation_id','gloss_frozen','gloss_sources','gloss_revision','_gloss_active_bindings'))
PLAIN_WORDS=(frozenset(('form','gloss')),frozenset(('form','gloss','form_kind','gloss_kind')))

LABELS=dict(headword='词形',notes='备注',homonym_note='同形词辨析',homonym_number='同形词编号',entry_type='条目类型',features='语法特征',tags='使用标签',usages='词类用法',pos='词类',subclass='词类子类',senses='义项',short_gloss='简短释义',definition='详细释义',variants='形式与变体',form='形式',pronunciation='读音',readings='读音',conditions='出现条件',condition_types='条件类型',variation='变体关系',status='分析状态',name='名称',source='研究依据',kind='形式类型',orthographies='自定义书写',label='名称',text='内容',type='类型',value='值',note='说明',relation='条目关系',base_id='基本条目',word_structure='形态分析与语素构成',memberships='形态类与主要部分',class_id='形态类',usage_id='所属用法',parts='主要部分',title='标题',variant_id='关联变体',writings='组分书写',analyses='分析方案',level='分析层面',default='默认分析',components='组分',role='角色',gloss='标注',lexeme_id='关联词条',sense_id='关联义项',form_id='关联形式',segments='不连续片段',semantic_classes='语义类',media='媒体',caption='说明',creator='创作者',speakers='发言人',examples='例句与例证',ipa='IPA',translation='自由翻译',words='词格',punctuation='标点',start_ms='起始毫秒',end_ms='结束毫秒',target_id='关联形式',type_id='书写类型')
LABELS.update(paradigms='变形表',dimensions='栏目',rows='表格行',labels='类别',realizations='变形形式',meanings='变形意义',base_sense_id='基本义项',state='填写状态',template_id='来源模板')
ENUMS=dict(unspecified='尚未指定',lexeme='词条',morpheme='普通语素',root='词根',affix='词缀',clitic='附着成分',infix='中缀',circumfix='环缀',connector='连接成分',multipart='其他多部分语素',stem='词干',expression='多词表达',hypothesis='待确认',confirmed='已确认',disputed='有争议',synchronic='共时',diachronic='历时',inherit='随分析方案',unknown='关系尚未确定',free='自由变体',conditioned='条件变体',na='不适用',phonological='音系',morphological='形态',syntactic='句法',lexical='词汇',inflection='屈折',derivation='派生',allomorph='语素变体',prefix='前缀',suffix='后缀',both='屈折与派生')
ENUMS.update(unfilled='未填写',missing='无此形式',filled='已填写')
# Empty fields remain available before the first word fills them in.
BASE_PATHS=['paradigms','paradigms.title','paradigms.rows.realizations.meanings.short_gloss','paradigms.rows.realizations.meanings.definition','headword','notes','homonym_note','homonym_number','entry_type','features','tags','tags.type','tags.value','tags.note','semantic_classes','orthographies','orthographies.label','orthographies.text','usages','usages.pos','usages.subclass','usages.notes','usages.tags','usages.features','usages.senses','usages.senses.short_gloss','usages.senses.definition','usages.senses.notes','usages.senses.tags','usages.senses.features','variants','variants.form','variants.kind','variants.pronunciation','variants.variation','variants.conditions','variants.condition_types','variants.source','variants.notes','variants.tags','variants.features','relation','relation.type','relation.base_id','word_structure','word_structure.memberships','word_structure.memberships.class_id','word_structure.memberships.parts','word_structure.memberships.parts.form','word_structure.memberships.parts.features','word_structure.analyses','word_structure.analyses.title','word_structure.analyses.level','word_structure.analyses.notes','word_structure.analyses.source','word_structure.analyses.components','word_structure.analyses.components.form','word_structure.analyses.components.gloss','word_structure.analyses.components.features','word_structure.analyses.components.role','word_structure.analyses.components.notes','word_structure.analyses.components.source','word_structure.analyses.components.segments','media','media.name','media.target_id','media.caption','media.creator','media.source','media.speakers','examples','examples.ipa','examples.translation','examples.notes','examples.words.form','examples.words.gloss']

def label(path):return ' › '.join(LABELS.get(k,k) for k in path.split('.'))

def descendants(rows,root):
    ids={root}
    while True:
        more={r['id'] for r in rows if r.get('parent_id') in ids}-ids
        if not more:return ids
        ids.update(more)

def needs_examples(spec,query=None):
    """Keep example/media/class searches complete; entry-only predicates stay local."""
    if isinstance(spec,dict) and spec.get('scope')=='entry':return False
    if spec is None or spec.get('class_id'):return True
    conditions=spec.get('conditions',[])
    if not isinstance(conditions,list) or any(not isinstance(c,dict) for c in conditions):return True
    primary=spec.get('field','all')
    # An empty free-text box does not apply its "all" predicate. Local field
    # conditions can be evaluated without rendering every linked sentence.
    # Keep nondefault primary fields for the same dynamic-field validation.
    fields=([primary] if query is None or query.strip() or primary!='all' else [])+[c.get('field') for c in conditions]
    return any(not isinstance(f,str) or f in ('all','examples','media') or f.startswith(('examples.','media.','layer:')) for f in fields)


def example_rows(db,rows,kind,index):
    """Validate cached documents before preparing their full render inputs."""
    if index is None:
        for row in gloss_inheritance.iter_rows(db,rows,kind):yield row,None
        return
    iterator=iter(rows)
    while batch:=list(islice(iterator,100)):
        # All versions stay in the evidence fingerprint, but only changed words
        # need full bindings and rendering, including on the very first search.
        stamps=gloss_inheritance.revisions(db,kind,[row['id'] for row in batch]);hits={};misses=[]
        for row in batch:
            stamp=stamps[row['id']]
            lookup=index.lookup((kind,row['id']),row['body']+('\0'+stamp if stamp else ''))
            hits[row['id']]=lookup
            if lookup[1] is None:misses.append(row['id'])
        gloss_inheritance.prefetch(db,kind,misses,changed_only=True)
        for row in batch:yield row,hits[row['id']]


class SearchIndex:
    def __init__(self,db,lid,rows,catalog_only=False,search_spec=None,query=None):
        self.rows=rows;self.fields={p:label(p) for p in BASE_PATHS};self.paths={}
        self.classes=categories.listing(db,lid)
        self.classes += [{**dict(r),'kind':'semantic'} for r in db.execute("SELECT * FROM semantic_classes WHERE ?='all' OR language_id=? ORDER BY position,name",(lid,lid))]
        self.classmap={r['id']:r for r in self.classes}
        self.tags={t['id']:t for t in grammar.listing(db,lid)}
        self.names={r['id']:r['name'] for r in self.classes}
        self.types={r['id']:r['name'] for r in db.execute("SELECT id,name FROM writing_types WHERE ?='all' OR language_id=?",(lid,lid))}
        self.names.update(self.types)
        self.people={r['id']:r['name'] for r in db.execute("SELECT id,name FROM timeline_speakers")}
        for r in rows:
            if catalog_only:continue
            self.names[r['id']]=r['headword']
            def register(v):
                if isinstance(v,dict):
                    if v.get('id'):
                        name=v.get('form') or v.get('short_gloss') or v.get('definition') or ' / '.join(filter(None,[v.get('pos'),v.get('subclass')])) or v.get('label','')
                        if name:self.names[v['id']]=name
                    for sub in v.values():register(sub)
                elif isinstance(v,list):
                    for sub in v:register(sub)
            register(paradigms.project(r['body']))
        for key,name in self.types.items():self.fields['writing:'+key]='自定义书写 › '+name
        for c in self.classes:
            if c['kind']=='usage_tag':self.fields['tag:'+c['name']]='使用标签 › '+c['name']
        for c in self.classes:
            for slot in c.get('template',{}).get('slots',[]):self.fields['part:'+c['id']+':'+slot['label']]='主要部分 › '+c['name']+' / '+slot['label']
        self.extra=defaultdict(lambda:defaultdict(list));self.example_owners=defaultdict(set);self.layer_values=defaultdict(lambda:defaultdict(list))
        for layer in db.execute("SELECT id,name FROM annotation_layers WHERE ?='all' OR language_id=?",(lid,lid)):
            self.fields['layer:'+layer['id']]='例句附加标注 › '+layer['name']
        if catalog_only:
            self.discover(r['body'] for r in rows)
            return
        # Association pickers search the target's own fields, never its evidence.
        # Exit before reading example bodies, annotation cells or attached media.
        if (search_spec or {}).get('scope')=='entry':
            self.documents={r['id']:self.document(r,include_extra=False) for r in rows}
            return
        # The ordinary all-field query only needs to know whether ANY evidence
        # contains the needle. Share that boolean across owners instead of
        # retaining and re-normalizing every sentence string for each lexeme.
        simple_query=query is not None and query.strip() and search_spec is not None and search_spec.get('field','all')=='all' and not search_spec.get('conditions') and not search_spec.get('class_id')
        self.evidence_case=bool((search_spec or {}).get('case',False))
        normalize=lambda v:unicodedata.normalize('NFC',v) if self.evidence_case else unicodedata.normalize('NFC',v).casefold()
        self.evidence_needle=normalize(query.strip()) if simple_query else None
        self.evidence_hits=set()
        self.word_values=OrderedDict();self.word_value_bytes=0
        # Only possible layer matches need a per-sentence identity check. A
        # negative Unicode-aware scan avoids thousands of empty unit lookups.
        layer_candidates=None
        if self.evidence_needle is not None:
            layer_candidates=set()
            for cell in long_tasks.steps(db.execute('SELECT owner_kind,record_id,value FROM annotation_cells')):
                if cell['value'].strip() and self.evidence_needle in normalize(cell['value']):layer_candidates.add((cell['owner_kind'],cell['record_id']))
        self.example_documents=defaultdict(lambda:defaultdict(set))
        layer_definitions=defaultdict(list)
        for layer in db.execute('SELECT * FROM annotation_layers'):layer_definitions[layer['language_id']].append(dict(layer))
        def add_example(kind,rid,source,owners,scope,index=None,lookup=None):
            long_tasks.checkpoint(None,'正在检索词条及关联例句…')
            if not owners:return
            body=None;cached=None;key=(kind,rid)
            if index is not None:
                if lookup is None:
                    stamp=gloss_inheritance.revision(db,kind,rid)
                    lookup=index.lookup(key,source+('\0'+stamp if stamp else ''))
                fingerprint,cached=lookup
            if cached is not None:
                hit,fields=cached;self.fields.update(fields);doc={}
            else:
                body=gloss_inheritance.load(db,kind,rid,source,metadata=False,changed_only=index is not None)
                if index is not None:
                    # Collect values independently of this query, so another
                    # query can use the same derived index without walking JSON.
                    fields={}
                    doc=self.document({'id':'','headword':'','body':body},include_extra=False,prefix=('examples',),all_only=True,field_catalog=fields)
                    hit=index.remember(key,fingerprint,doc.get('all',[]),fields)
                else:
                    doc=self.document({'id':'','headword':'','body':body},include_extra=False,prefix=('examples',),all_only=self.evidence_needle is not None)
                    hit=self.evidence_needle is not None and (bool(doc.get('_evidence_match')) or any(self.evidence_needle in normalize(v) for v in doc.get('all',[]) if v.strip()))
            for xid in owners:
                if self.evidence_needle is None:
                    for field,values in doc.items():self.example_documents[xid][field].update(values)
                elif hit:self.evidence_hits.add(xid)
                self.example_owners[(kind,rid)].add(xid)
            cells=[] if layer_candidates is not None and (hit or (kind,rid) not in layer_candidates) else list(db.execute('SELECT * FROM annotation_cells WHERE owner_kind=? AND record_id=?',(kind,rid)))
            if cells:
                if body is None:body=gloss_inheritance.load(db,kind,rid,source,metadata=False)
                live={w['id'] for w in annotations.units(db,kind,rid,body)}
                definitions=layer_definitions[body.get('language_id') or scope]
                for cell in cells:
                    if annotations.valid_cell(cell,live,definitions):
                        if self.evidence_needle is None:
                            for xid in owners:self.layer_values[xid]['layer:'+cell['layer_id']].append(cell['value'])
                        elif cell['value'].strip() and self.evidence_needle in normalize(cell['value']):self.evidence_hits.update(owners)
        for m in db.execute("SELECT record_id,body FROM object_media WHERE kind='lexeme' AND (?='all' OR language_id=?)",(lid,lid)):
            self.extra[m['record_id']]['media'].append(json.loads(m['body']))
        if needs_examples(search_spec,query):
            from contextlib import nullcontext
            catalog=(self.names,self.tags,self.types,self.people)
            with evidence_index.query(db,lid,catalog,self.evidence_needle,self.evidence_case) if self.evidence_needle is not None else nullcontext(None) as index:
                for e,lookup in example_rows(db,db.execute("SELECT e.id,e.body,e.language_id,(SELECT json_group_array(DISTINCT json_extract(value,'$.lexeme_id')) FROM json_each(e.body,'$.targets')) owners FROM dictionary_examples e WHERE ?='all' OR e.language_id=?",(lid,lid)),'independent',index):
                    add_example('independent',e['id'],e['body'],json.loads(e['owners']),e['language_id'],index,lookup)
                # Build a narrow ID map before reading any sentence bodies. SQL
                # aggregation/join plans can otherwise materialize/sort the wide
                # JSON stream; dictionary result ordering is applied later.
                targets={r[0]:r[0] for r in db.execute('SELECT id FROM '+dictionary_targets.IDENTITIES+" WHERE ?='all' OR language_id=?",(lid,lid))}
                owners=defaultdict(set)
                for link in long_tasks.steps(db.execute('SELECT u.entry_id,l.lexeme_id FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id')):
                    if link['lexeme_id'] in targets:owners[link['entry_id']].add(targets[link['lexeme_id']])
                ids=list(owners)
                for start in range(0,len(ids),400):
                    batch=ids[start:start+400]
                    for e,lookup in example_rows(db,db.execute('SELECT e.id,e.body,t.language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id IN ('+','.join('?' for _ in batch)+')',batch),'corpus',index):
                        add_example('corpus',e['id'],e['body'],owners[e['id']],e['language_id'],index,lookup)
        for m in db.execute("SELECT m.kind,m.record_id,m.body,a.name FROM object_media m JOIN timeline_media a ON a.id=m.asset_id WHERE ?='all' OR m.language_id=?",(lid,lid)):
            owners={m['record_id']} if m['kind']=='lexeme' else self.example_owners.get(('independent',m['record_id']),set())
            for xid in owners:
                self.extra[xid]['media'].append({'name':m['name'],**(json.loads(m['body']) if m['kind']=='independent' else {})})
        for r in rows:
            rel=r['body'].get('relation') or {}
            if rel.get('base_id'):self.extra[rel['base_id']]['relation'].append({'type':rel['type'],'base_id':r['id']})
        self.documents={r['id']:self.document(r) for r in rows}

    def discover(self,bodies):
        """Discover field paths without building thousands of searchable documents."""
        def add(path):
            for n in range(1,len(path)+1):
                key='.'.join(path[:n])
                if key not in self.fields:self.fields[key]=label(key)
        def walk(v,path=(),membership=''):
            key=path[-1] if path else ''
            if isinstance(v,list):
                if key in ('features','semantic_classes','speakers'):return
                for item in v:walk(item,path,membership)
            elif isinstance(v,dict):
                if key=='memberships':membership=v.get('class_id','')
                if key in ('orthographies','writings'):
                    field='writing:'+(v.get('type_id') or v.get('label',''));self.fields[field]='自定义书写 › '+(self.types.get(v.get('type_id')) or v.get('label','未命名'))
                if key=='tags':
                    kind=categories.TAG_NAMES.get(v.get('type'),v.get('type',''));self.fields['tag:'+kind]='使用标签 › '+kind
                if key=='parts':self.fields['part:'+membership+':'+v.get('label','')]='主要部分 › '+self.names.get(membership,'')+' / '+v.get('label','')
                for k,x in v.items():
                    if k in HIDDEN_KEYS:continue
                    if k.endswith('_id'):
                        if k in LABELS and self.names.get(x):add(path+(k,))
                    else:walk(x,path+(k,),membership)
            elif isinstance(v,(str,int,float,bool)) and v!='':add(path)
        for body in bodies:walk(body)

    def document(self,row,include_extra=True,prefix=(),all_only=False,field_catalog=None):
        out=defaultdict(list)
        def add(path,value):
            if value is None or value=='':return
            values=value if isinstance(value,list) else [str(value)]
            keys=self.paths.get(path)
            if keys is None:
                keys=['.'.join(path[:n]) for n in range(1,len(path)+1)];self.paths[path]=keys
                for key in keys:
                    if key not in self.fields:self.fields[key]=label(key)
            if field_catalog is not None:
                for key in keys:field_catalog[key]=self.fields[key]
            if not all_only:
                for key in keys:out[key].extend(values)
            out['all'].extend(values)
        def walk(v,path=(),membership=''):
            nonlocal field_catalog
            key=path[-1] if path else ''
            if isinstance(v,list):
                if all_only and path==('examples','words'):
                    for word in v:
                        visible={k:x for k,x in word.items() if k not in HIDDEN_KEYS} if isinstance(word,dict) else word
                        # Most untouched corpus slots contain only these scalar
                        # fields. Their tuple is already an exact identity and
                        # needs no JSON serialization on every occurrence.
                        plain=isinstance(visible,dict) and visible.keys() in PLAIN_WORDS and all(isinstance(v,str) for v in visible.values())
                        encoded=tuple(sorted(visible.items())) if plain else json.dumps(visible,ensure_ascii=False,sort_keys=True).encode('utf-8')
                        saved=self.word_values.get(encoded)
                        if saved is None:
                            start=len(out['all']);parent_catalog=field_catalog;field_catalog={}
                            try:walk(word,path,membership);fields=field_catalog
                            finally:field_catalog=parent_catalog
                            if field_catalog is not None:field_catalog.update(fields)
                            values=tuple(dict.fromkeys(out['all'][start:]));del out['all'][start:]
                            key_size=192+sum(128+4*(len(k)+len(v)) for k,v in encoded) if plain else len(encoded)
                            size=key_size+sum(128+4*len(v) for v in values)+sum(256+4*(len(k)+len(v)) for k,v in fields.items())
                            if size<=8*1024**2:
                                while self.word_values and (self.word_value_bytes+size>8*1024**2 or len(self.word_values)>=512):
                                    _,(_,_,cost)=self.word_values.popitem(last=False);self.word_value_bytes-=cost
                                self.word_values[encoded]=(values,fields,size);self.word_value_bytes+=size
                        else:
                            self.word_values.move_to_end(encoded);values,fields,_=saved
                            self.fields.update(fields)
                            if field_catalog is not None:field_catalog.update(fields)
                        out['all'].extend(values)
                    return
                if key=='features':
                    out['_grammar_classes'].extend(self.tags[fid].get('category','') for fid in v if fid in self.tags)
                    add(path,[s for fid in v for s in [self.tags.get(fid,{}).get('symbol',''),self.tags.get(fid,{}).get('description',''),*self.tags.get(fid,{}).get('aliases',[])] if s]);return
                if key=='semantic_classes':add(path,[self.names.get(fid,'') for fid in v]);return
                if key=='speakers':add(path,[self.people.get(fid,'') for fid in v]);return
                for item in v:walk(item,path,membership)
            elif isinstance(v,dict):
                if key=='memberships':membership=v.get('class_id','')
                if key in ('orthographies','writings'):
                    field='writing:'+(v.get('type_id') or v.get('label',''));self.fields[field]='自定义书写 › '+(self.types.get(v.get('type_id')) or v.get('label','未命名'));out[field].append(v.get('text',''))
                    if field_catalog is not None:field_catalog[field]=self.fields[field]
                if key=='tags':
                    kind=categories.TAG_NAMES.get(v.get('type'),v.get('type',''));field='tag:'+kind;self.fields[field]='使用标签 › '+kind;out[field].extend([v.get('value',''),v.get('note','')])
                    if field_catalog is not None:field_catalog[field]=self.fields[field]
                part_values=[]
                for k,x in v.items():
                    if k in HIDDEN_KEYS or (not include_extra and not prefix and k in ('examples','media')):continue
                    before=len(out['all'])
                    if k.endswith('_id'):
                        if k in LABELS:add(path+(k,),self.names.get(x,''))
                    else:walk(x,path+(k,),membership)
                    if key=='parts' and k!='label':part_values.extend(out['all'][before:])
                if key=='parts':
                    field='part:'+membership+':'+v.get('label','');self.fields[field]='主要部分 › '+self.names.get(membership,'')+' / '+v.get('label','');out[field].extend(part_values)
                    if field_catalog is not None:field_catalog[field]=self.fields[field]
            elif isinstance(v,(str,int,float,bool)):
                value=('是' if v else '否') if isinstance(v,bool) else str(v)
                if key in ('entry_type','affix_function','affix_position','variation','status','level','condition_types','state') or path==('relation','type'):value=ENUMS.get(value,value)
                if key=='type' and 'tags' in path:value=categories.TAG_NAMES.get(value,value)
                add(path,value)
        walk({'headword':row['headword'],**paradigms.project(row['body'])},prefix)
        if include_extra:
            for k,v in self.extra[row['id']].items():walk(v,(k,))
            for field,values in getattr(self,'example_documents',{}).get(row['id'],{}).items():out[field].extend(values)
            for field,values in self.layer_values[row['id']].items():out[field].extend(values);out['examples'].extend(values);out['all'].extend(values)
        # Search predicates depend on membership, not repeated occurrence counts.
        return {key:list(dict.fromkeys(values)) for key,values in out.items()}

    def catalog(self):
        items=[]
        for c in self.classes:
            parts=[c['name']];parent=c.get('parent_id');seen={c['id']}
            while parent in self.classmap and parent not in seen:
                seen.add(parent);p=self.classmap[parent];parts.insert(0,p['name']);parent=p.get('parent_id')
            items.append({k:c[k] for k in ('id','kind','language_id')}|{'name':' / '.join(parts)})
        return {'fields':[{'id':'all','name':'词条全部内容'}]+[{'id':k,'name':v} for k,v in self.fields.items()], 'classes':items}

    def prepare(self,spec):
        if isinstance(spec,str):
            try:spec=json.loads(spec or '{}')
            except (ValueError,TypeError):raise ValueError('搜索条件格式不正确')
        if not isinstance(spec,dict):raise ValueError('搜索条件格式不正确')
        if spec.get('scope','all') not in ('all','entry'):raise ValueError('搜索范围无效')
        conditions=spec.get('conditions',[])
        if not isinstance(conditions,list) or len(conditions)>50:raise ValueError('搜索条件最多 50 项')
        valid=set(self.fields)|{'all'}
        if not isinstance(spec.get('field','all'),str) or spec.get('field','all') not in valid:raise ValueError('搜索字段已不存在，请重新选择')
        if spec.get('combine','all') not in ('all','any') or type(spec.get('case',False)) is not bool:raise ValueError('搜索匹配设置无效')
        for c in conditions:
            if not isinstance(c,dict) or not isinstance(c.get('field'),str) or c.get('field') not in valid or c.get('op','contains') not in ('contains','exact','prefix','suffix','empty','present','not_contains') or not isinstance(c.get('value',''),str):raise ValueError('请检查搜索字段、匹配方式和内容')
            if c.get('op','contains') not in ('empty','present') and not c.get('value','').strip():raise ValueError('请填写搜索条件内容，或选择“已填写”或“未填写”')
        cid=spec.get('class_id','')
        if not isinstance(cid,str):raise ValueError('类别筛选无效')
        if cid and cid!='@unclassified' and cid not in self.classmap:raise ValueError('该类已不存在或属于其他语言，请重新选择')
        self.spec=spec;self.class_ids=descendants(self.classes,cid) if cid else set()
        return self

    def in_class(self,row):
        cid=self.spec.get('class_id','');b=row['body']
        if not cid:return True
        if cid=='@unclassified':return not b.get('semantic_classes')
        matched=set(b.get('semantic_classes',[]))|{m['class_id'] for m in b.get('word_structure',{}).get('memberships',[])}
        doc=self.documents[row['id']]
        for c in self.classes:
            if c['language_id']!=row['language_id']:continue
            kind,name=c['kind'],c['name']
            if kind=='pos':
                parent=self.classmap.get(c.get('parent_id'),{})
                if any((u.get('subclass')==name and u.get('pos')==parent.get('name')) if parent else u.get('pos')==name for u in b.get('usages',[])):matched.add(c['id'])
            elif kind=='form' and any(v.get('kind')==name for v in b.get('variants',[])):matched.add(c['id'])
            elif kind=='usage_tag' and name in [categories.TAG_NAMES.get(t['type'],t['type']) for t in categories.usage_tags(b)]:matched.add(c['id'])
            elif kind=='grammar' and name in doc.get('_grammar_classes',[]):matched.add(c['id'])
        return bool(matched & self.class_ids)

    def matches(self,row,query=''):
        if not self.in_class(row):return False
        doc=self.documents[row['id']];s=self.spec
        def norm(v):
            v=unicodedata.normalize('NFC',v)
            return v if s.get('case',False) else v.casefold()
        def match(field,op,value):
            values=(norm(v) for v in doc.get(field,[]) if v.strip());needle=norm(value)
            if op=='empty':return not any(v.strip() for v in doc.get(field,[]))
            if op=='present':return any(v.strip() for v in doc.get(field,[]))
            if op=='not_contains':return not any(needle in v for v in values)
            return any(v==needle if op=='exact' else v.startswith(needle) if op=='prefix' else v.endswith(needle) if op=='suffix' else needle in v for v in values)
        evidence_hit=(getattr(self,'evidence_needle',None)==norm(query.strip()) and bool(s.get('case',False))==getattr(self,'evidence_case',None) and row['id'] in getattr(self,'evidence_hits',()) and s.get('field','all')=='all' and not s.get('conditions') and not s.get('class_id'))
        if query.strip() and not evidence_hit and not match(s.get('field','all'),'contains',query.strip()):return False
        checks=[match(c['field'],c.get('op','contains'),c.get('value','')) for c in s.get('conditions',[])]
        return not checks or (any(checks) if s.get('combine')=='any' else all(checks))


def catalog(db,lid):
    import dictionary_data
    types={r['id']:r for r in db.execute('SELECT * FROM writing_types')}
    rows=[{**dict(r),'body':dictionary_data.resolve(db,json.loads(r['body']),types)} for r in db.execute("SELECT * FROM lexemes WHERE ?='all' OR language_id=?",(lid,lid))]
    return SearchIndex(db,lid,rows,catalog_only=True).catalog()
