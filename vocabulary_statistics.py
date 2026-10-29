"""Occurrence-based vocabulary profiles; never infer roots by stripping strings."""
import json
import math
import unicodedata
from collections import defaultdict
import corpus
import component_links
import long_tasks


def category(body,role=''):
    kind=body.get('entry_type','unspecified')
    if kind in ('infix','circumfix'):return 'affix'
    if kind!='unspecified':return kind
    return {'词根':'root','多部分词根':'root','root':'root','词干':'stem','复合词干':'stem','stem':'stem',
            '派生词缀':'affix','屈折词缀':'affix','中缀':'affix','环缀':'affix','affix':'affix',
            '连接成分':'connector','connector':'connector','multipart root':'root','discontinuous root':'root',
            'compound stem':'stem','derivational affix':'affix','inflectional affix':'affix','infix':'affix',
            'circumfix':'affix','linking element':'connector'}.get((role or body.get('role','')).strip().casefold(),'unspecified')


class Collector:
    def __init__(self,db,case=True,selection=None):
        self.selection=selection
        self.db=db;self.case=case;self.hits=[];self.forms={};self.morphemes={};self.row_types=defaultdict(set)
        self.native={}
        sql="""SELECT id,language_id,form,json_object('entry_type',COALESCE(json_extract(body,'$.entry_type'),'unspecified'),
          'role',COALESCE(json_extract(body,'$.role'),''),'gloss',COALESCE(json_extract(body,'$.gloss'),''),
          'variants',json(COALESCE(json_extract(body,'$.variants'),'[]')),
          'usages',json(COALESCE(json_extract(body,'$.usages'),'[]')),
          'paradigms',json(COALESCE(json_extract(body,'$.paradigms'),'[]')),
          'senses',json(COALESCE(json_extract(body,'$.senses'),'[]'))) body FROM morphemes"""
        for r in long_tasks.steps(db.execute(sql)):
            m={**dict(r),'body':json.loads(r['body'])};usages=m['body'].pop('usages',[])
            m['senses']={u['id']:{s['id'] for s in u.get('senses',[])} for u in usages} if usages else {'@morpheme':{'@main',*(s['id'] for s in m['body'].pop('senses',[]))}}
            for table in m['body'].pop('paradigms',[]):
                for row in table.get('rows',[]):
                    if row.get('state')=='filled':
                        for form in row.get('realizations',[]):m['senses'].setdefault(table['usage_id'],set()).update(s['id'] for s in form.get('meanings',[]))
            self.native[r['id']]=m
        self.targets={};self.components={};self.links=defaultdict(list);self.morpheme_words=set();self.root_words=set()

    def load_batch(self,ids):
        self.links.clear()
        if not ids:return
        sql='''SELECT l.*,u.entry_id,u.kind,COALESCE(p.position,u.position) word_position,
                 c.body component_ref_json,a.form_id
          FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id
          LEFT JOIN corpus_units p ON p.id=u.parent_id
          LEFT JOIN lexical_reviews v ON v.id=l.id
          LEFT JOIN component_links c ON c.id=l.id
          LEFT JOIN morphology_analyses a ON a.id=l.id
          WHERE u.active=1 AND v.id IS NULL AND u.entry_id IN ('''+','.join('?' for _ in ids)+')'
        for r in self.db.execute(sql,ids):
            link=dict(r);link['component_ref']=json.loads(r['component_ref_json']) if r['component_ref_json'] else None
            link['key']='@word' if r['kind']=='word' else r['unit_id'];link['word']=r['word_position']
            self.links[r['entry_id']].append(link)

    def resolve(self,link,language):
        if link.get('review_reason') or link.get('component_review') or link.get('segmentation_review'):return None
        owner=link.get('lexeme_id');ref=link.get('component_ref');mid=owner;role=''
        if ref:
            if owner not in self.targets:
                row=self.db.execute('SELECT body FROM dictionary_targets WHERE id=?',(owner,)).fetchone()
                self.targets[owner]=json.loads(row[0]) if row else None
            body=self.targets[owner]
            if body is None or component_links.review(body,ref):return None
            key=(owner,ref['analysis_id'],ref['component_id'])
            if key not in self.components:
                row=self.db.execute('SELECT morpheme_id FROM morpheme_components WHERE lexeme_id=? AND analysis_id=? AND component_id=?',key).fetchone()
                self.components[key]=row[0] if row else None
            mid=self.components[key];role=ref['snapshot']['component'].get('role','')
        m=self.native.get(mid)
        if not m or m['language_id']!=language:return None
        if not ref and link.get('usage_id'):
            senses=m['senses'].get(link['usage_id'])
            if senses is None or link.get('sense_id') and link['sense_id'] not in senses:return None
        if not ref and link.get('form_id') and not any(v['id']==link['form_id'] for v in m['body'].get('variants',[])):return None
        return m,category(m['body'],role)

    def record(self,rid,body,language,text_id,is_word):
        positions={}
        for pos,word in enumerate(body.get('words',[])):
            if not is_word(word):continue
            form=unicodedata.normalize('NFC',word['form'].strip());key=(language,form if self.case else form.casefold())
            index=len(self.hits);positions[pos]=index
            self.hits.append(dict(entry_id=rid,word=pos,form=form,value=form,unit_id=''))
            self.row_types[text_id or '@independent'].add(key)
            row=self.forms.setdefault(key,dict(key=json.dumps(key,ensure_ascii=False),form=key[1],language_id=language,indices=[],sentences=set(),texts=set()))
            row['indices'].append(index);row['sentences'].add(rid)
            if text_id:row['texts'].add(text_id)
        if rid.startswith('independent:'):
            import copy,segmentation
            parsed=corpus.analyze(copy.deepcopy(body));segmentation.decorate_refs(parsed);links=[]
            for target in parsed.get('targets',[]):
                ref=target.get('segmentation_ref')
                if not ref or ref.get('detached') or target.get('segmentation_review'):continue
                links.append({**target,'word':ref['word'],'key':ref['key']})
        else:links=self.links.get(rid,[])
        candidates=[]
        selected=[]
        for link in links:
            index=positions.get(link.get('word'))
            if index is None:continue
            if self.selection and self.selection.value['target']=='lexeme':
                target=self.selection.resolve(link,language)
                if target:selected.append((index,link['key'],target))
            resolved=self.resolve(link,language)
            if resolved:
                m,kind=resolved;candidates.append((index,link['key'],m,kind))
                if self.selection and self.selection.value['target']=='morpheme' and m['id'] in self.selection.eligible:selected.append((index,link['key'],self.selection.eligible[m['id']]))
        if self.selection:self.selection.record(selected,self.hits,rid,text_id)
        # An unsegmented word and its identical single-morpheme link denote one
        # occurrence. Distinct repeated morpheme units remain separate tokens.
        children={(i,m['id']) for i,key,m,kind in candidates if key!='@word'};seen=set()
        for index,unit,m,kind in candidates:
            if unit=='@word' and (index,m['id']) in children:continue
            identity=(index,unit,m['id'])
            if identity in seen:continue
            seen.add(identity);self.morpheme_words.add(index)
            if kind=='root':self.root_words.add(index)
            key=(m['id'],kind)
            row=self.morphemes.setdefault(key,dict(key=json.dumps(key),id=m['id'],form=m['form'],gloss=m['body'].get('gloss',''),language_id=language,kind=kind,count=0,indices=set(),sentences=set(),texts=set(),forms=set()))
            row['count']+=1;row['indices'].add(index);row['sentences'].add(rid)
            form=self.hits[index]['form'];row['forms'].add(form if self.case else form.casefold())
            if text_id:row['texts'].add(text_id)
        return len(positions)

    def finish(self,stats):
        for row in stats['rows']:row['types']=len(self.row_types[row['id'] if row['kind']!='independent' else '@independent'])
        stats.update(types=len(self.forms),morpheme_words=len(self.morpheme_words),root_words=len(self.root_words),case=self.case)
        def finish(row):
            indices=sorted(row['indices']);result={k:v for k,v in row.items() if k not in ('indices','sentences','texts','forms')}
            result.update(indices=indices,count=row.get('count',len(indices)),words=len(indices),sentences=len(row['sentences']),texts=len(row['texts']))
            if 'forms' in row:result['types']=len(row['forms'])
            return result
        return dict(forms=[finish(r) for r in self.forms.values()],morphemes=[finish(r) for r in self.morphemes.values()],**({'selection':self.selection.finish()} if self.selection else {}))


def page(result,request):
    view=request.get('vocabulary_view','overview')
    if view not in ('overview','forms','morphemes','roots','stems','affixes','custom'):raise ValueError('词汇统计视图无效')
    order=request.get('vocabulary_order','frequency')
    if order not in ('frequency','form'):raise ValueError('词汇统计排序无效')
    data=result['vocabulary'];rows=data['forms'] if view in ('overview','forms') else data['morphemes']
    selection=data.get('selection')
    if view=='custom':
        if not selection:raise ValueError('此结果没有自定义条目统计，请重新运行')
        rows=selection['rows']
    kind={'roots':'root','stems':'stem','affixes':'affix'}.get(view)
    if kind:rows=[r for r in rows if r['kind']==kind]
    denominator=selection['occurrences'] if view=='custom' else sum(r['count'] for r in rows)
    query=request.get('vocabulary_query','')
    if not isinstance(query,str) or len(query)>2000:raise ValueError('词频筛选内容无效')
    def norm(value):
        value=unicodedata.normalize('NFC',value)
        return value if result['statistics'].get('case',True) else value.casefold()
    needle=norm(query.strip())
    if needle:rows=[r for r in rows if needle in norm(r['form']) or view not in ('overview','forms') and needle in norm(r.get('gloss',''))]
    rows=sorted(rows,key=(lambda r:(-r['count'],r['form'],r['language_id'],r['key'])) if order=='frequency' else (lambda r:(r['form'],r['language_id'],r['key'])))
    total=len(rows);pages=max(1,math.ceil(total/100))
    try:requested_page=int(request.get('vocabulary_page',1))
    except (ValueError,TypeError):raise ValueError('词频页码无效')
    p=max(1,min(requested_page,pages));selected=None;indices=[]
    if request.get('vocabulary_item'):
        selected=next((r for r in rows if r['key']==request['vocabulary_item']),None)
        if selected is None:raise ValueError('词频项目已不存在于当前结果中')
        indices=selected['indices'];pages=max(1,math.ceil(len(indices)/30));p=max(1,min(requested_page,pages));indices=indices[(p-1)*30:p*30]
    def public(row):return {k:v for k,v in row.items() if k!='indices'}
    return dict(view=view,order=order,total=total,denominator=denominator,page=p,pages=pages,rows=[] if selected or view=='overview' else [public(r) for r in rows[(p-1)*100:p*100]],selected=public(selected) if selected else None,example_total=len(selected['indices']) if selected else 0,**({'selection':{k:v for k,v in selection.items() if k!='rows'}} if selection else {})),indices
