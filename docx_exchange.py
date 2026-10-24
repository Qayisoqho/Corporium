"""Standard Word text exchange. Sentence containers, never page geometry, define sentences."""
import base64
import copy
import hashlib
import io
import json
import re
import tempfile
import unicodedata
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as E

import annotations
import gloss_inheritance
import language_exchange
import languages
import lexicon
import long_tasks
from corpus import analyze

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
C='urn:corporium:word-exchange:1'
R='http://schemas.openxmlformats.org/package/2006/relationships'
PREFIX='corporium:'
MAX_BYTES=14*1024*1024
MAX_WORDS=200000
MAX_SENTENCES=20000
MIME='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
E.register_namespace('w',W)

def q(name):return '{'+W+'}'+name
def el(parent,name,**attrs):return E.SubElement(parent,q(name),{q(k):str(v) for k,v in attrs.items()})
def tag(node):
    t=node.find(q('sdtPr')+'/'+q('tag'))
    return t.get(q('val'),'') if t is not None else ''

def text(node):
    """Runs may be arbitrarily split by Word; preserve tabs, line breaks and scripts."""
    def run(r):
        value=''.join(n.text or '' if n.tag==q('t') else '\t' if n.tag==q('tab') else '\n' if n.tag in (q('br'),q('cr')) else '' for n in r if n.tag!=q('rPr'))
        va=r.find(q('rPr')+'/'+q('vertAlign'))
        if va is not None and value:return ('#sub[' if va.get(q('val'))=='subscript' else '#super[' if va.get(q('val'))=='superscript' else '')+value+(']' if va.get(q('val')) in ('subscript','superscript') else '')
        return value
    paras=list(node.iter(q('p')))
    if not paras:return ''.join(run(r) for r in node.iter(q('r')))
    return '\n'.join(''.join(run(r) for r in p.iter(q('r'))) for p in paras)

def _xml(z,name):
    data=z.read(name)
    if b'<!DOCTYPE' in data or b'<!ENTITY' in data:raise ValueError('不支持含 XML 实体声明的 Word 文件')
    return E.fromstring(data)

def read(source):
    """Read the documented template, refusing ambiguous or unsupported content."""
    try:
        with zipfile.ZipFile(source) as z:
            members=z.infolist()
            if len(members)>5000 or sum(x.file_size for x in members)>100*1024*1024:raise ValueError('Word 文件解压后过大（最多 100 MB）')
            if len(set(z.namelist()))!=len(members):raise ValueError('Word 文件含重复部件')
            root=_xml(z,'word/document.xml');body=root.find(q('body'))
            if body is None:raise ValueError('Word 文件没有正文')
            styles={}
            if 'word/styles.xml' in z.namelist():
                for style in _xml(z,'word/styles.xml').findall(q('style')):
                    name=style.find(q('name'))
                    if name is not None:styles[style.get(q('styleId'))]=name.get(q('val'),'')
            if root.find('.//'+q('ins')) is not None or root.find('.//'+q('del')) is not None:raise ValueError('文件含未处理的修订，请先在 Word 中接受或拒绝修订后再导入')
            # A picture, text box or nested table cannot quietly disappear on import.
            unsupported=('drawing','pict','object','altChunk','footnoteReference','endnoteReference')
            if any(root.find('.//'+q(k)) is not None for k in unsupported):raise ValueError('标准导入暂不读取图片、文本框、对象或脚注，请将语料放入例句字段与词格表')
            defs=[]
            metadata_found=False
            # Word renames custom parts and built-in style IDs when saving.
            for name in z.namelist():
                if not re.fullmatch(r'customXml/[^/]+\.xml',name):continue
                meta=_xml(z,name)
                if meta.tag!='{'+C+'}exchange':continue
                if metadata_found or meta.get('version')!='1':raise ValueError('Word 交换格式版本不受支持或定义重复')
                metadata_found=True;defs=[dict(key=d.get('key',''),name=d.get('name',''),anchor=d.get('anchor','word')) for d in meta.findall('{'+C+'}layer')]
            if len(defs)>100 or len({d['key'] for d in defs})!=len(defs) or any(not d['key'] or not d['name'] or d['anchor'] not in ('word','ipa','translation') for d in defs):raise ValueError('Word 附加标注层定义无效')
            known={d['key']:d for d in defs};sentences=[];title='导入文本';total=0
            for block in long_tasks.steps(body):
                if block.tag==q('sectPr'):continue
                if block.tag==q('p'):
                    style=block.find(q('pPr')+'/'+q('pStyle'));style=style.get(q('val')) if style is not None else ''
                    if styles.get(style,style).casefold()=='title':title=text(block) or title
                    elif text(block).strip() and style!='CorporiumHelp':raise ValueError('发现例句范围之外的文字，请使用标准模板，或将内容放入对应例句范围')
                    continue
                if block.tag!=q('sdt') or tag(block)!=PREFIX+'sentence:v1':raise ValueError('缺少标准例句范围；请使用 Corporium 导出的 DOCX 或标准模板')
                content=block.find(q('sdtContent'))
                if content is None:raise ValueError('例句范围内容为空')
                fields={};parts=[];word_layers={};sentence_layers={}
                for child in long_tasks.steps(content):
                    if child.tag==q('p'):
                        style=child.find(q('pPr')+'/'+q('pStyle'));style=style.get(q('val')) if style is not None else ''
                        if style=='CorporiumNumber':continue
                        controls=[s for s in child.iter(q('sdt')) if tag(s).startswith(PREFIX+'field:') or tag(s).startswith(PREFIX+'layer:')]
                        if not controls:
                            if text(child).strip():raise ValueError('例句内有未指定含义的段落，请填入 IPA、翻译、备注或附加标注字段')
                            continue
                        if len(controls)!=1:raise ValueError('每个句级字段请单独放在一个段落中')
                        outside=''.join(text(n) for n in child if n.tag not in (q('sdt'),q('pPr'))).strip()
                        marker=tag(controls[0]);field=marker.split(':',2)[2]
                        label=({'ipa':'IPA：','translation':'翻译：','notes':'备注：','original':'原文：'}.get(field) if marker.startswith(PREFIX+'field:') else known.get(field,{}).get('name','')+'：')
                        if outside and outside!=label:raise ValueError('发现字段之外的额外文字，请将内容放入对应的字段内，避免遗漏')
                        for control in controls:
                            key=tag(control).split(':',2)[2];value=text(control.find(q('sdtContent')))
                            target=sentence_layers if tag(control).startswith(PREFIX+'layer:') else fields
                            if key in target:raise ValueError('同一句重复出现字段：'+key)
                            if target is fields and key not in ('ipa','translation','notes','original'):raise ValueError('例句字段不受支持：'+key)
                            if target is sentence_layers and (key not in known or known[key]['anchor']=='word'):raise ValueError('句级标注层定义已丢失')
                            target[key]=value
                    elif child.tag==q('tbl'):
                        rows={};width=None
                        if child.findall('.//'+q('tbl')):raise ValueError('词格表不支持嵌套表格')
                        for row in child.findall(q('tr')):
                            cells=row.findall(q('tc'))
                            if not cells:raise ValueError('词格表含空行')
                            if any(c.find(q('tcPr')+'/'+q('vMerge')) is not None or (c.find(q('tcPr')+'/'+q('gridSpan')) is not None and c.find(q('tcPr')+'/'+q('gridSpan')).get(q('val'))!='1') for c in cells):raise ValueError('词格表含合并单元格，请先取消合并并核对对齐')
                            label=text(cells[0]).strip();labels={'语素':'form','词形':'form','标注':'gloss'}
                            marker=next((tag(s).split(':',2)[2] for s in cells[0].iter(q('sdt')) if tag(s).startswith(PREFIX+'layer:')),None)
                            key=marker or labels.get(label)
                            if key is None:raise ValueError('无法识别词格表行：'+label)
                            if key not in ('form','gloss') and (key not in known or known[key]['anchor']!='word'):raise ValueError('词级标注层定义已丢失')
                            if key in rows:raise ValueError('同一段词格表含重复行：'+label)
                            values=[text(c) for c in cells[1:]]
                            if width is None:width=len(values)
                            if width!=len(values):raise ValueError('词格表上下行的单元格数不一致')
                            rows[key]=values
                        if 'form' not in rows or 'gloss' not in rows:raise ValueError('每段词格表都必须同时有语素行和标注行，单格允许留空')
                        start=sum(len(p) for p in parts);part=[dict(form=f,gloss=g) for f,g in zip(rows.pop('form'),rows.pop('gloss'))];parts.append(part)
                        for key,values in rows.items():word_layers.setdefault(key,{}).update({start+i:v for i,v in enumerate(values) if v})
                    else:raise ValueError('例句范围内含不支持的结构，请使用普通段落与词格表')
                words=[w for p in parts for w in p];total+=len(words)
                if len(sentences)>=MAX_SENTENCES or total>MAX_WORDS or len(words)>5000:raise ValueError('文件或单句过大，请拆分文件；单句最多 5000 词格')
                sentences.append(dict(fields=fields,words=words,word_layers=word_layers,sentence_layers=sentence_layers,parts=[len(p) for p in parts]))
            if not sentences:raise ValueError('未找到标准例句，请使用 Corporium 的 DOCX 模板')
            return dict(title=title,sentences=sentences,layers=defs)
    except (zipfile.BadZipFile,KeyError,E.ParseError,TypeError,AttributeError,UnicodeError) as error:raise ValueError('无法读取标准 .docx 文件，请检查文件内容与格式') from error

def _stage(dbpath,data,kind,suffix):
    with tempfile.NamedTemporaryFile(suffix=suffix,dir=language_exchange.STAGING.name,delete=False) as f:f.write(data);path=Path(f.name)
    return language_exchange.stage(dbpath,path,kind)

def inspect(db,dbpath,b,lid):
    try:raw=base64.b64decode(b.get('data',''),validate=True)
    except (ValueError,TypeError):raise ValueError('上传内容无效')
    if not 0<len(raw)<=MAX_BYTES:raise ValueError('请选择 14 MB 以内的标准 .docx 文件；旧 .doc 请先另存为 .docx')
    data=read(io.BytesIO(raw));data['digest']=hashlib.sha256(raw).hexdigest();data['filename']=str(b.get('filename','Word.docx'))[:240]
    token=_stage(dbpath,json.dumps(data,ensure_ascii=False).encode(),'docx-import','.json');groups=[];offset=0
    for s in data['sentences']:
        end=offset+max(1,len(s['words']));groups.append(dict(start=offset,end=end));offset=end
    return dict(token=token,title=data['title'],groups=groups,atoms=offset,sentences=len(groups),slots=sum(len(s['words']) for s in data['sentences']),segments=sum(len(s['parts']) for s in data['sentences']),source_layers=data['layers'],layers=annotations.layers(db,lid))

def plan(db,dbpath,b,lid):
    data=json.loads(language_exchange.staged(dbpath,b.get('token'),'docx-import').read_text(encoding='utf-8'))
    title=b.get('title');groups=b.get('groups');defs=annotations.layers(db,lid);known={d['id']:d for d in defs}
    if not isinstance(title,str) or not title.strip() or len(title)>500:raise ValueError('请填写 500 字以内的文本标题')
    if not isinstance(groups,list) or not groups or len(groups)>MAX_SENTENCES:raise ValueError('分句方案无效或句数过多')
    mappings=b.get('layer_map',{});source={d['key']:d for d in data['layers']}
    if not isinstance(mappings,dict) or set(mappings)!=set(source):raise ValueError('请确认所有附加标注层的对应关系；不需要的层请选择“不导入”')
    used=set()
    for key,target in mappings.items():
        if target is None:continue
        if not isinstance(target,str) or target not in known or known[target]['anchor']!=source[key]['anchor'] or target in used:raise ValueError('附加标注层映射无效、重复或不属于当前语言')
        used.add(target)
    atoms=[]
    for si,s in enumerate(data['sentences']):
        atoms.extend((si,i) for i in range(len(s['words']))) if s['words'] else atoms.append((si,None))
    offset=0;plans=[]
    for g in long_tasks.steps(groups):
        if not isinstance(g,dict) or type(g.get('start')) is not int or type(g.get('end')) is not int or g['start']!=offset or not offset<g['end']<=len(atoms):raise ValueError('分句方案有重复、遗漏或顺序错误，请重新预览')
        selected=atoms[offset:g['end']];offset=g['end'];fields={k:[] for k in ('ipa','translation','notes','original')};body=dict(function='pass',words=[],raw='',line=None,edited=True);cells=[];sentence_cells={};source_numbers=[]
        breaks=[]
        for atom_position,(si,wi) in enumerate(selected,g['start']):
            s=data['sentences'][si]
            if not source_numbers or source_numbers[-1]!=si+1:source_numbers.append(si+1)
            if wi is None or wi==0:
                for k in fields:
                    if s['fields'].get(k):fields[k].append(s['fields'][k])
                for key,value in s['sentence_layers'].items():
                    if mappings[key] and value:sentence_cells.setdefault(mappings[key],[]).append(value)
            if wi is not None:
                position=len(body['words']);body['words'].append(copy.deepcopy(s['words'][wi]))
                breaks.append(atom_position+1)
                for key,values in s['word_layers'].items():
                    value=values.get(str(wi),values.get(wi,''))
                    if mappings[key] and value:cells.append(dict(word=position,layer_id=mappings[key],value=value))
        if len(body['words'])>5000:raise ValueError('合并后的单句超过 5000 词格，请保留分句')
        for k,values in fields.items():
            value=g.get(k,'\n'.join(values))
            if not isinstance(value,str) or len(value)>200000:raise ValueError('句子字段内容无效或过长')
            body[k]=value
        cells.extend(dict(word=None,layer_id=key,value='\n'.join(values)) for key,values in sentence_cells.items())
        # Preview needs literal aligned cells, not every sentence's full analysis.
        # Analysis runs once during the atomic import instead of on every page.
        plans.append(dict(body=body,cells=cells,start=g['start'],end=g['end'],breaks=breaks,sources=source_numbers,split=selected[0][1] not in (None,0)))
    if offset!=len(atoms):raise ValueError('分句方案遗漏文件末尾内容，请重新预览')
    signature=hashlib.sha256(json.dumps([lid,data['digest'],title,groups,mappings,defs],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return plans,signature,data

def preview(db,dbpath,b,lid):
    plans,signature,data=plan(db,dbpath,b,lid)
    page=b.get('page',1)
    if type(page) is not int or page<1:raise ValueError('预览页码无效')
    pages=max(1,(len(plans)+19)//20);page=min(page,pages)
    return dict(signature=signature,total=len(plans),slots=sum(len(p['body']['words']) for p in plans),page=page,pages=pages,items=[dict(index=i,**p) for i,p in enumerate(plans[(page-1)*20:page*20],(page-1)*20)])

def apply(db,dbpath,b,lid):
    plans,signature,data=plan(db,dbpath,b,lid)
    if signature!=b.get('signature'):raise ValueError('分句、字段或标注层已变化，请重新预览后导入')
    tid=str(uuid.uuid4());db.execute('INSERT INTO texts(id,title,source,original,digest,errors,language_id) VALUES(?,?,?,?,?,?,?)',(tid,b['title'].strip(),data['filename'],'',str(uuid.uuid4()),'[]',lid))
    for position,s in long_tasks.steps(enumerate(plans,1)):
        rid=str(uuid.uuid4());body=analyze(s['body']);db.execute('INSERT INTO entries(id,text_id,position,body) VALUES(?,?,?,?)',(rid,tid,position,json.dumps(body,ensure_ascii=False)))
        lexicon.sync_entry(db,rid);units=annotations.units(db,'corpus',rid,body)
        for c in s['cells']:
            uid=annotations.SENTENCE if c['word'] is None else units[c['word']]['id']
            db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,1)',(str(uuid.uuid4()),'corpus',rid,uid,c['layer_id'],c['value']))
    return dict(ok=True,ids=[tid],count=len(plans))

def _control(parent,marker):
    aliases={'sentence:v1':'例句范围（可含多段词格表）','field:ipa':'IPA','field:translation':'自由翻译','field:notes':'备注','field:original':'原文'}
    node=el(parent,'sdt');props=el(node,'sdtPr');el(props,'tag',val=PREFIX+marker);el(props,'alias',val=aliases.get(marker,'附加标注'))
    return el(node,'sdtContent')

def _runs(parent,value,font='Junicode',size=22,style='normal',script=None):
    font={'sans-serif':'Segoe UI','serif':'Junicode'}.get(font,font)
    if re.search('[\x00-\x08\x0b\x0c\x0e-\x1f]',value):raise ValueError('文本含 Word 不支持的控制字符')
    for chunk in re.split(r'(#(?:sub|sup|super)\[[^\[\]]*\])',value):
        m=re.fullmatch(r'#(sub|sup|super)\[([^\[\]]*)\]',chunk)
        if m:_runs(parent,m[2],font,size,style,'subscript' if m[1]=='sub' else 'superscript');continue
        r=el(parent,'r');p=el(r,'rPr');el(p,'rFonts',ascii=font,hAnsi=font,eastAsia='SimSun');el(p,'sz',val=size);el(p,'szCs',val=size)
        if style in ('bold','bolditalic'):el(p,'b')
        if style in ('italic','bolditalic'):el(p,'i')
        if style=='small-caps':el(p,'smallCaps')
        if script:el(p,'vertAlign',val=script)
        for part in re.split('(\n|\t)',chunk):
            if part=='\n':el(r,'br')
            elif part=='\t':el(r,'tab')
            else:el(r,'t',**{}).text=part;r[-1].set('{http://www.w3.org/XML/1998/namespace}space','preserve')

def _p(parent,value='',style=None,keep=False,**fmt):
    p=el(parent,'p');props=el(p,'pPr');el(props,'spacing',after=60)
    if style:el(props,'pStyle',val=style)
    if keep:el(props,'keepNext')
    _runs(p,value,**fmt);return p

def _field(parent,key,value,label,**fmt):
    p=_p(parent);_runs(p,label,size=20);content=_control(p,'field:'+key);_runs(content,value,**fmt)

def _width(value):return sum(2 if unicodedata.east_asian_width(c) in ('W','F') else 0 if unicodedata.combining(c) else 1 for c in re.sub(r'#(?:sub|sup|super)\[([^]]*)\]',r'\1',value))

def document(title,sentences,layers=(),metadata=None,words_per_table=0):
    """Generate a normal DOCX with editable sentence controls and multiple short tables."""
    meta=metadata or {};doc=E.Element(q('document'));body=el(doc,'body');_p(body,title,style='Title',size=32)
    _p(body,'每个例句范围可含多段词格表；请在对应字段内编辑。重新导入会创建新文本。',style='CorporiumHelp',size=18)
    word_defs=[d for d in layers if d.get('anchor','word')=='word'];sentence_defs=[d for d in layers if d.get('anchor','word')!='word']
    for number,s in long_tasks.steps(enumerate(sentences,1)):
        content=_control(body,'sentence:v1');_p(content,'（'+str(number)+'）',style='CorporiumNumber',keep=True)
        b=s['body'];cells=s.get('cells',{});_field(content,'ipa',b.get('ipa',''),'IPA：',font=meta.get('ipa_font') or 'IPAPANNEW',size=round(22*float(meta.get('ipa_scale',1))),style=meta.get('ipa_variant','normal'))
        if b.get('original'):_field(content,'original',b['original'],'原文：')
        widths=[round(min(8500,max(840,220+150*max(_width(w['form'])*meta.get('morpheme_scale',1),_width(w['gloss'])*meta.get('gloss_scale',1),*[_width(cells.get((i,d['id']),''))*d.get('size',100)/100 for d in word_defs])))) for i,w in enumerate(b['words'])]
        chunks=[];current=[];used=600
        for i,width in enumerate(widths):
            if current and (used+width>10080 or words_per_table and len(current)>=words_per_table):chunks.append(current);current=[];used=600
            current.append(i);used+=width
        if current:chunks.append(current)
        for chunk in chunks:
            table=el(content,'tbl');props=el(table,'tblPr');el(props,'tblW',w=600+sum(widths[i] for i in chunk),type='dxa');el(props,'tblLayout',type='fixed')
            borders=el(props,'tblBorders')
            for edge in ('top','left','bottom','right','insideH','insideV'):el(borders,edge,val='single',sz=4,color='D9D9D9')
            margins=el(props,'tblCellMar')
            for edge in ('top','bottom'):el(margins,edge,w=35,type='dxa')
            for edge in ('left','right'):el(margins,edge,w=60,type='dxa')
            grid=el(table,'tblGrid')
            for width in [600]+[widths[i] for i in chunk]:el(grid,'gridCol',w=width)
            rows=[('语素','form',None),('标注','gloss',None)]+[(d['name'],None,d) for d in word_defs]
            for ri,(label,key,d) in enumerate(rows):
                row=el(table,'tr');el(el(row,'trPr'),'cantSplit');tc=el(row,'tc');el(el(tc,'tcPr'),'tcW',w=600,type='dxa');p=_p(tc,keep=ri<len(rows)-1,size=18)
                if d:_runs(_control(p,'layer:'+d['id']),label,size=18)
                else:_runs(p,label,size=18)
                for i in chunk:
                    tc=el(row,'tc');pr=el(tc,'tcPr');el(pr,'tcW',w=widths[i],type='dxa');el(pr,'vAlign',val='center')
                    _p(tc,cells.get((i,d['id']),'') if d else b['words'][i][key],keep=ri<len(rows)-1,font=d.get('font','Junicode') if d else (meta.get('annotation_font') if key=='form' else meta.get('gloss_font')) or 'Junicode',style=d.get('style','normal') if d else meta.get('morpheme_variant' if key=='form' else 'gloss_variant','italic' if key=='form' else 'normal'),size=round(22*(d.get('size',100) if d else 100*meta.get('morpheme_scale' if key=='form' else 'gloss_scale',1))/100))
            _p(content,'',size=4)
        _field(content,'translation',b.get('translation',''),'翻译：',font=meta.get('translation_font') or 'Junicode',size=round(22*float(meta.get('translation_scale',1))),style=meta.get('translation_variant','normal'))
        _field(content,'notes',b.get('notes',''),'备注：',size=20)
        for d in sentence_defs:
            p=_p(content);_runs(p,d['name']+'：',size=20);_runs(_control(p,'layer:'+d['id']),cells.get((None,d['id']),''),font=d.get('font','Junicode'),style=d.get('style','normal'),size=round(22*d.get('size',100)/100))
    sect=el(body,'sectPr');el(sect,'pgSz',w=12240,h=15840);el(sect,'pgMar',top=1080,right=1080,bottom=1080,left=1080,header=360,footer=360,gutter=0)
    styles=E.Element(q('styles'))
    for name,size in [('Normal',22),('Title',32),('CorporiumNumber',22),('CorporiumHelp',18)]:
        st=el(styles,'style',type='paragraph',styleId=name);el(st,'name',val=name);rp=el(st,'rPr');el(rp,'rFonts',ascii='Junicode',hAnsi='Junicode',eastAsia='SimSun');el(rp,'color',val='000000');el(rp,'sz',val=size)
    types=E.Element('Types',xmlns='http://schemas.openxmlformats.org/package/2006/content-types')
    for ext,ct in [('rels','application/vnd.openxmlformats-package.relationships+xml'),('xml','application/xml')]:E.SubElement(types,'Default',Extension=ext,ContentType=ct)
    for path,ct in [('/word/document.xml',MIME+'.main+xml'),('/word/styles.xml','application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml')]:E.SubElement(types,'Override',PartName=path,ContentType=ct)
    # Main document's content type differs from the file MIME type.
    types.find("Override[@PartName='/word/document.xml']").set('ContentType','application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml')
    rels=E.Element('Relationships',xmlns=R);E.SubElement(rels,'Relationship',Id='rId1',Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument',Target='word/document.xml')
    docrels=E.Element('Relationships',xmlns=R)
    for i,(kind,target) in enumerate([('styles','styles.xml'),('customXml','../customXml/corporium.xml')],1):E.SubElement(docrels,'Relationship',Id='rId'+str(i),Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/'+kind,Target=target)
    description=E.Element('{'+C+'}exchange',version='1')
    for d in layers:E.SubElement(description,'{'+C+'}layer',key=d['id'],name=d['name'],anchor=d.get('anchor','word'))
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,node in [('[Content_Types].xml',types),('_rels/.rels',rels),('word/document.xml',doc),('word/styles.xml',styles),('word/_rels/document.xml.rels',docrels),('customXml/corporium.xml',description)]:z.writestr(name,E.tostring(node,encoding='utf-8',xml_declaration=True))
    return out.getvalue()

def export(db,b,lid):
    tid=b.get('id');row=db.execute('SELECT * FROM texts WHERE id=? AND language_id=?',(tid,lid)).fetchone()
    if not row:raise ValueError('请选择当前语言的一个文本')
    limit=b.get('words_per_table',0)
    if type(limit) is not int or not 0<=limit<=30:raise ValueError('每段词格上限无效')
    defs=annotations.layers(db,lid);meta=json.loads(db.execute('SELECT metadata FROM languages WHERE id=?',(lid,)).fetchone()[0]);sentences=[]
    positions={};cells_by_entry={}
    for u in db.execute("SELECT u.entry_id,u.id,u.position FROM corpus_units u JOIN entries e ON e.id=u.entry_id WHERE e.text_id=? AND u.kind='word' AND u.active=1",(tid,)):positions.setdefault(u['entry_id'],{})[u['id']]=u['position']
    for c in db.execute("SELECT c.* FROM annotation_cells c JOIN entries e ON e.id=c.record_id WHERE e.text_id=? AND c.owner_kind='corpus'",(tid,)):
        slots=positions.get(c['record_id'],{})
        if c['unit_id']==annotations.SENTENCE:position=None
        elif c['unit_id'] in slots:position=slots[c['unit_id']]
        else:continue
        cells_by_entry.setdefault(c['record_id'],{})[position,c['layer_id']]=c['value']
    for r in gloss_inheritance.iter_rows(db,db.execute('SELECT id,body FROM entries WHERE text_id=? ORDER BY position,id',(tid,)),'corpus',lightweight=True):
        body=gloss_inheritance.load(db,'corpus',r['id'],r['body'],metadata=False,lightweight=True)
        if body.get('language_id') and body['language_id']!=lid:raise ValueError('文本含其他语言的句子，请先按语言拆分后导出')
        cells=cells_by_entry.get(r['id'],{})
        literal={k:body.get(k,'') for k in ('ipa','translation','notes','original')};literal['words']=[dict(form=w['form'],gloss=w['gloss']) for w in body['words']]
        sentences.append(dict(body=literal,cells=cells))
    if not sentences:raise ValueError('文本没有句子；如需空白文档，请在 Word 导入窗口下载模板')
    raw=document(row['title'],sentences,defs,meta,limit)
    if len(raw)>MAX_BYTES:raise ValueError('导出的 DOCX 超过 14 MB，请先拆分文本后分别导出')
    return dict(name=re.sub(r'[\\/:*?"<>|]','_',row['title'])[:120]+'.docx',data=base64.b64encode(raw).decode(),token=_stage(b['_dbpath'],raw,'docx-export','.docx'),sentences=len(sentences))

def dispatch(db,dbpath,action,b,lid):
    languages.require(db,lid)
    if action=='inspect':return inspect(db,dbpath,b,lid)
    if action=='preview':return preview(db,dbpath,b,lid)
    if action=='import':return apply(db,dbpath,b,lid)
    if action=='export':return export(db,{**b,'_dbpath':dbpath},lid)
    if action=='template':
        raw=document('新文本',[dict(body=dict(ipa='',translation='',notes='',words=[dict(form='',gloss='') for _ in range(6)]))])
        return dict(name='Corporium 标准文本模板.docx',data=base64.b64encode(raw).decode(),token=_stage(dbpath,raw,'docx-export','.docx'))
    raise ValueError('未知 Word 操作')
