"""User-selected entry statistics reuse the dictionary's entry-only predicates."""
import json
import categories
import dictionary_search
import long_tasks
import paradigms

CLASS_LABELS={'semantic':'语义类','morph':'形态类','pos':'词类与子类','form':'形式类型','usage_tag':'使用标签类型','grammar':'语法标签分类'}


def normalize(value):
    if value is None:return None
    if not isinstance(value,dict) or value.get('target','morpheme') not in ('morpheme','lexeme'):raise ValueError('统计对象无效')
    query=value.get('query','');group=value.get('group_by','entry');spec=value.get('search',{})
    if not isinstance(query,str) or len(query)>2000 or not isinstance(group,str) or len(group)>500 or not isinstance(spec,dict):raise ValueError('条目统计条件无效')
    conditions=spec.get('conditions',[])
    if not isinstance(conditions,list) or len(conditions)>50:raise ValueError('搜索条件最多 50 项')
    fields={k:spec.get(k,d) for k,d in [('field','all'),('case',False),('combine','all'),('class_id','')]}
    if not isinstance(fields['field'],str) or not isinstance(fields['class_id'],str) or type(fields['case']) is not bool or fields['combine'] not in ('all','any'):raise ValueError('搜索匹配设置无效')
    clean=[]
    for c in conditions:
        if not isinstance(c,dict) or not isinstance(c.get('field'),str) or not isinstance(c.get('value',''),str) or len(c.get('value',''))>2000 or c.get('op','contains') not in ('contains','exact','prefix','suffix','empty','present','not_contains'):raise ValueError('条目统计条件无效')
        clean.append(dict(field=c['field'],op=c.get('op','contains'),value=c.get('value','')))
    return dict(target=value.get('target','morpheme'),query=query,group_by=group,search={**fields,'conditions':clean,'scope':'entry'})


def entry_index(db,lid,target):
    if target not in ('morpheme','lexeme'):raise ValueError('统计对象无效')
    rows=[]
    for r in long_tasks.steps(db.execute("SELECT id,language_id,headword,json_remove(body,'$.examples','$.media') body FROM dictionary_targets WHERE target_kind=? AND (?='all' OR language_id=?)",(target,lid,lid))):
        body=json.loads(r['body'])
        if target=='morpheme' and body.get('entry_type') not in ('affix','infix','circumfix'):
            body.pop('affix_function',None);body.pop('affix_position',None)
        rows.append({**dict(r),'body':body})
    index=dictionary_search.SearchIndex(db,lid,rows,search_spec={'scope':'entry'})
    index.discover(r['body'] for r in rows)
    index.fields={k:v for k,v in index.fields.items() if k not in ('examples','media') and not k.startswith(('examples.','media.','layer:'))}
    index.fields.update(affix_position='词缀位置',affix_function='构词功能')
    for key,name in [('created_at','创建时间'),('updated_at','修改时间')]:
        if key in index.fields:index.fields[key]=name
    if target=='morpheme':index.fields['headword']='语素形式'
    return index


def options(index):
    catalog=index.catalog()
    catalog['groups']=[dict(id='entry',name='按条目分别统计')]+[dict(id='class:'+k,name=v) for k,v in CLASS_LABELS.items()]+[dict(id=k,name=v) for k,v in index.fields.items()]
    return catalog


def catalog(db,lid,target):return options(entry_index(db,lid,target))


class Selection:
    def __init__(self,db,lid,value,case=True):
        self.case=case
        self.value=value;self.index=entry_index(db,lid,value['target']);self.index.prepare(value['search'])
        groups={g['id']:g['name'] for g in options(self.index)['groups']}
        if value['group_by'] not in groups:raise ValueError('统计分类字段已删除或不属于当前语言，请重新选择')
        self.label=groups[value['group_by']];self.rows={};self.eligible={};self.groups={};self.senses={}
        self.classes={c['id']:c for c in self.index.classes};self.class_labels={c['id']:c['name'] for c in self.index.catalog()['classes']}
        for r in long_tasks.steps(self.index.rows):
            selected_class=self.classes.get(value['search'].get('class_id'))
            if selected_class and selected_class['language_id']!=r['language_id']:continue
            if not self.index.matches(r,value['query']):continue
            self.eligible[r['id']]=r
            self.senses[r['id']]={u['id']:{s['id'] for s in u.get('senses',[])} for u in paradigms.usages(r['body'])}
        self.covered=set();self.seen_entries=set();self.occurrences=0

    def resolve(self,link,language):
        if link.get('component_ref') or link.get('review_reason') or link.get('component_review') or link.get('segmentation_review'):return None
        r=self.eligible.get(link.get('lexeme_id'))
        if not r or r['language_id']!=language:return None
        if link.get('usage_id'):
            senses=self.senses[r['id']].get(link['usage_id'])
            if senses is None or link.get('sense_id') and link['sense_id'] not in senses:return None
        if link.get('form_id') and not any(v['id']==link['form_id'] for v in r['body'].get('variants',[])):return None
        return r

    def grouped(self,r):
        if r['id'] in self.groups:return self.groups[r['id']]
        group=self.value['group_by'];body=r['body'];language=r['language_id']
        if group=='entry':values=[(r['id'],r['headword'],False)]
        elif group.startswith('class:'):
            kind=group.partition(':')[2];matched=set(body.get('semantic_classes',[])) if kind=='semantic' else {m['class_id'] for m in body.get('word_structure',{}).get('memberships',[])} if kind=='morph' else set()
            for c in self.classes.values():
                if c['kind']!=kind or c['language_id']!=language:continue
                if kind=='pos':
                    parent=self.classes.get(c.get('parent_id'),{})
                    if any((u.get('subclass')==c['name'] and u.get('pos')==parent.get('name')) if parent else u.get('pos')==c['name'] for u in body.get('usages',[])):matched.add(c['id'])
                elif kind=='form' and any(categories.FORM_NAMES.get(v.get('kind'),v.get('kind'))==c['name'] for v in body.get('variants',[])):matched.add(c['id'])
                elif kind=='usage_tag' and any(categories.TAG_NAMES.get(t['type'],t['type'])==c['name'] for t in categories.usage_tags(body)):matched.add(c['id'])
                elif kind=='grammar' and c['name'] in self.index.documents[r['id']].get('_grammar_classes',[]):matched.add(c['id'])
            values=[(c['id'],self.class_labels[cid],False) for cid in sorted(matched) if (c:=self.classes.get(cid)) and c['kind']==kind and c['language_id']==language]
        else:values=[(v,v,group in ('entry_type','affix_position','affix_function','variants.kind')) for v in self.index.documents[r['id']].get(group,[]) if v.strip()]
        if not values:values=[('@unclassified','未分类／未填写',True)]
        self.groups[r['id']]=values;return values

    def record(self,candidates,hits,rid,text_id):
        children={(i,r['id']) for i,key,r in candidates if key!='@word'};seen=set()
        for index,unit,r in candidates:
            if unit=='@word' and (index,r['id']) in children:continue
            identity=(index,unit,r['id'])
            if identity in seen:continue
            seen.add(identity);self.occurrences+=1;self.covered.add(index);self.seen_entries.add(r['id'])
            for gid,label,system in self.grouped(r):
                key=json.dumps([r['language_id'],gid],ensure_ascii=False)
                gloss=r['body'].get('gloss','') or next((s.get('short_gloss','') for u in r['body'].get('usages',[]) for s in u.get('senses',[]) if s.get('short_gloss')),'')
                row=self.rows.setdefault(key,dict(key=key,form=label,gloss=gloss if self.value['group_by']=='entry' else '',language_id=r['language_id'],count=0,indices=set(),sentences=set(),texts=set(),forms=set(),entries=set(),system_label=system))
                form=hits[index]['form'];row['count']+=1;row['indices'].add(index);row['sentences'].add(rid);row['entries'].add(r['id']);row['forms'].add(form if self.case else form.casefold())
                if text_id:row['texts'].add(text_id)

    def finish(self):
        rows=[]
        for row in self.rows.values():
            result={k:v for k,v in row.items() if k not in ('indices','sentences','texts','forms','entries')}
            result.update(indices=sorted(row['indices']),words=len(row['indices']),sentences=len(row['sentences']),texts=len(row['texts']),types=len(row['forms']),entries=len(row['entries']))
            rows.append(result)
        return dict(target=self.value['target'],group_by=self.value['group_by'],label=self.label,occurrences=self.occurrences,words=len(self.covered),entries=len(self.seen_entries),eligible_entries=len(self.eligible),rows=rows)
