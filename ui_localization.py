"""Translate authored UI messages at presentation boundaries, never stored data."""
from functools import lru_cache
from http.cookies import SimpleCookie
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent
SUPPORTED={'zh-CN','en'}
ASSET_PATHS={'/i18n.js','/i18n.css','/i18n-settings.js','/i18n-catalog.js'}

def language(headers=None,default='zh-CN'):
    headers=headers or {}
    explicit=headers.get('X-Corporium-UI-Language')
    if isinstance(explicit,str) and explicit in SUPPORTED:return explicit
    cookie=SimpleCookie()
    try:cookie.load(headers.get('Cookie',''))
    except Exception:pass
    value=cookie.get('corporium-ui-language')
    return value.value if value and value.value in SUPPORTED else default if isinstance(default,str) and default in SUPPORTED else 'zh-CN'

@lru_cache(maxsize=1)
def catalog():
    return json.loads((ROOT/'web'/'i18n-messages.json').read_text(encoding='utf-8'))

@lru_cache(maxsize=1)
def patterns():
    result=[]
    for zh,en in catalog().get('backend',catalog()['phrases']).items():
        if '⟦' not in zh:continue
        parts=[];previous=0;seen=set();literal=0
        for m in re.finditer(r'⟦(\d+)⟧',zh):
            fixed=zh[previous:m.start()];parts.append(re.escape(fixed));literal+=len(fixed)
            group='p'+m[1]
            parts.append('(?P='+group+')' if group in seen else '(?P<'+group+r'>[\s\S]*?)')
            seen.add(group);previous=m.end()
        parts.append(re.escape(zh[previous:]));literal+=len(zh)-previous
        if literal>=2:result.append((literal,re.compile(''.join(parts)),en))
    return sorted(result,key=lambda item:-item[0])

@lru_cache(maxsize=512)
def message(value,locale='zh-CN'):
    if locale!='en' or not isinstance(value,str):return value
    if value in catalog()['phrases']:return catalog()['phrases'][value]
    if len(value)>8192:return value
    for _,pattern,en in patterns():
        match=pattern.fullmatch(value)
        if match:return re.sub(r'⟦(\d+)⟧',lambda m:match.groupdict().get('p'+m[1],m[0]),en)
    return value

def fields(row,*names):
    """Copy one display record; names are an explicit presentation contract."""
    if not isinstance(row,dict):return row
    result={**row}
    for name in names:
        if isinstance(row.get(name),str):result[name]=message(row[name],'en')
        elif isinstance(row.get(name),list):result[name]=[message(v,'en') if isinstance(v,str) else v for v in row[name]]
    return result

def annotations(row):
    return fields(row,'warnings')

def homophone_group(group):
    return {**group,'items':[fields(r,'reason','origin') for r in group.get('items',[])],
            **({'classification':fields(group['classification'],'reason')} if group.get('classification') else {})}

def present(value,path,locale):
    """Only fields whose contracts identify them as system messages are touched."""
    if locale!='en' or not isinstance(value,dict):return value
    result=value
    if isinstance(value.get('error'),str):result={**value,'error':message(value['error'],locale)}
    if path=='/desktop-status':result=fields(result,'startup_error')
    if path=='/api/recorder-pending':result={**result,'items':[fields(item,'error') for item in result.get('items',[])]}
    if path=='/api/task-status':
        result={**result}
        for key in ['message','error']:
            if isinstance(result.get(key),str):result[key]=message(result[key],locale)
        route={'grammar-audit':'grammar-audit','auto-match':'lexeme-auto-preview','homophones':'homophones','timeline':'timeline'}.get(result.get('kind'))
        if result.get('kind')=='operation':route=result.get('operation')
        if route and isinstance(result.get('result'),dict):result['result']=present(result['result'],'/api/'+route,locale)
    if path=='/api/grammar-audit':
        result={**result,'items':[fields(item,'message') for item in result.get('items',[])]}
    if path in {'/api/entries','/api/example-library'}:
        result={**result,'items':[{**annotations(item),**({'body':annotations(item['body'])} if isinstance(item.get('body'),dict) else {})} for item in result.get('items',[])]}
    if path in {'/api/entry','/api/independent-example'}:result=annotations(result)
    if path in {'/api/timeline','/api/timeline-detail'} and isinstance(result.get('media'),dict):result={**result,'media':fields(result['media'],'unavailable')}
    if path=='/api/lexeme-examples':result={**result,'items':[fields(item,'review_reason') for item in result.get('items',[])]}
    if path=='/api/unit-dictionary' and isinstance(result.get('link'),dict):result={**result,'link':fields(result['link'],'review_reason')}
    if path=='/api/homophones':
        result={**result,'groups':[homophone_group(g) for g in result.get('groups',[])],
                'review':[fields(r,'reason','origin') for r in result.get('review',[])],
                'pending':[homophone_group(g) for g in result.get('pending',[])]}
        if 'blocks' in result:
            result['blocks']=[{**b,'rows':[{**r,'cells':[{**c,'groups':[homophone_group(g) for g in c.get('groups',[])]} for c in r.get('cells',[])]} for r in b.get('rows',[])]} for b in result['blocks']]
    if path in {'/api/punctuation-preview','/api/dictionary-replace-preview','/api/dictionary-replace-apply','/api/text-replace-preview'}:
        result=fields(result,'message')
        for name in ['blocked','conflicts']:
            if isinstance(result.get(name),list):result={**result,name:[fields(r,'reason') for r in result[name]]}
    if path=='/api/sentence-gloss-preview':
        result={**result,'rows':[{**r,'candidates':[fields(c,'reason') for c in r.get('candidates',[])]} for r in result.get('rows',[])],
                'skipped':[fields(r,'reason') for r in result.get('skipped',[])]}
    if path=='/api/sentence-dictionary-preview' and isinstance(result.get('old'),dict):result={**result,'old':fields(result['old'],'review_reason')}
    if path=='/api/lexeme-auto-preview':
        result={**result}
        for name in ['matches','suggestions','ambiguous']:
            if isinstance(result.get(name),list):result[name]=[{**fields(r,'match_reason'),**({'candidates':[fields(c,'match_reason') for c in r['candidates']]} if 'candidates' in r else {})} for r in result[name]]
        if isinstance(result.get('multipart_warnings'),list):result['multipart_warnings']=[fields(r,'message','reason') for r in result['multipart_warnings']]
    if path in {'/api/timeline-replacement-preview','/api/timeline-replace-preview'}:result=fields(result,'warnings')
    if path=='/api/undo-state':
        def step(item):
            return {**item,'label':message(item['label'],locale)} if isinstance(item,dict) and isinstance(item.get('label'),str) else item
        result={**result,'undo':step(result.get('undo')),'redo':step(result.get('redo')),'steps':[step(item) for item in result.get('steps',[])]}
    if path=='/licenses/catalog':
        result={**result,'about':{**result.get('about',{})},'items':[{**item,'title':message(item['title'],locale)} for item in result.get('items',[])]}
        if isinstance(result['about'].get('description'),str):result['about']['description']=message(result['about']['description'],locale)
    if path in {'/api/dictionary-search-options','/api/morpheme-search-options','/api/vocabulary-options'} and isinstance(result.get('fields'),list):
        from dictionary_search import LABELS
        known=set(LABELS)|{'affix_function','affix_position','created_at','updated_at'}
        def field(item):
            ident=item.get('id','');name=item.get('name','')
            if not isinstance(ident,str) or not isinstance(name,str):return item
            if ident=='all':return {**item,'name':message('全部内容',locale)}
            if ':' in ident:
                prefix,sep,tail=name.partition(' › ')
                return {**item,'name':message(prefix,locale)+sep+tail} if sep else item
            if all(part in known for part in ident.split('.')):
                return {**item,'name':' › '.join(message(part,locale) for part in name.split(' › '))}
            return item
        result={**result,'fields':[field(item) for item in result['fields']]}
        if path=='/api/vocabulary-options':
            result={**result,'groups':[{**item,'name':message(item['name'],locale)} if item['id']=='entry' or item['id'].startswith('class:') else field(item) for item in result['groups']]}
    return result

def bootstrap_html(source,desktop_language=None):
    """Load localization before any application script; keep UI state off the DB."""
    if '<body' not in source:return source
    attrs=' data-ui-ready="false"'
    if desktop_language in SUPPORTED:attrs+=' data-desktop="true" data-ui-language="'+desktop_language+'"'
    source=re.sub(r'<html\b',lambda m:m[0]+attrs,source,count=1)
    assets='<link rel="stylesheet" href="/i18n.css"><script src="/i18n-catalog.js"></script><script src="/i18n.js"></script>'
    # Encoding is declared before scripts; all scripts are local and synchronous.
    source=source.replace('</head>',assets+'</head>',1)
    first=re.search(r'<script\b[^>]*\bsrc=',source[source.index('<body'):],re.I)
    call='<script>CorporiumI18n.localizeStatic(document.body)</script>'
    if first:
        offset=source.index('<body')+first.start();source=source[:offset]+call+source[offset:]
    else:source=source.replace('</body>',call+'</body>')
    source=source.replace('</body>','<script src="/i18n-settings.js"></script></body>')
    return source
