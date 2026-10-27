"""Vertical text interchange. OOXML text only: never evaluate Excel formulas."""
import long_tasks
import base64
import hashlib
import io
import json
import gloss_inheritance
import posixpath
import re
import tempfile
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import annotations
import language_exchange
import languages
import lexicon
from corpus import analyze

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
MAX_ROWS=200000
MAX_COLS=256
MAX_BYTES=14*1024*1024

def colname(n):
    out=''
    while n:
        n,r=divmod(n-1,26);out=chr(65+r)+out
    return out

def read(source):
    """Read sparse worksheet rows without trusting workbook dimension hints."""
    try:
        with zipfile.ZipFile(source) as z:
            if len(z.infolist())>5000 or sum(i.file_size for i in z.infolist())>100*1024*1024:raise ValueError('工作簿解压后过大（最多 100 MB）')
            def xml(name):
                data=z.read(name)
                if b'<!DOCTYPE' in data or b'<!ENTITY' in data:raise ValueError('不支持含 XML 实体声明的工作簿')
                return ET.fromstring(data)
            strings=[''.join(t.text or '' for t in e.iter('{'+NS+'}t')) for e in xml('xl/sharedStrings.xml')] if 'xl/sharedStrings.xml' in z.namelist() else []
            rels={r.get('Id'):r.get('Target') for r in xml('xl/_rels/workbook.xml.rels') if r.get('TargetMode')!='External'}
            sheets=[];total=0
            for s in long_tasks.steps(xml('xl/workbook.xml').findall('{'+NS+'}sheets/{'+NS+'}sheet')):
                target=rels.get(s.get('{'+REL+'}id'),'')
                name=posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
                if not name.startswith('xl/worksheets/'):raise ValueError('仅支持普通 Excel 工作表')
                root=xml(name);rows={};width=0;formula=0
                if root.find('{'+NS+'}mergeCells') is not None:raise ValueError('工作表“'+s.get('name','')+'”含合并单元格，请先取消合并并核对内容')
                for row in long_tasks.steps(root.findall('{'+NS+'}sheetData/{'+NS+'}row')):
                    rn=int(row.get('r','0'))
                    if not 1<=rn<=MAX_ROWS:raise ValueError('工作表最多支持 200000 行')
                    values={}
                    for c in long_tasks.steps(row):
                        address=re.fullmatch(r'([A-Z]+)([0-9]+)',c.get('r',''))
                        if not address:raise ValueError('无效的单元格地址')
                        cn=0
                        for ch in long_tasks.steps(address[1]):cn=cn*26+ord(ch)-64
                        v=c.find('{'+NS+'}v');value=v.text or '' if v is not None else ''
                        typ=c.get('t','')
                        if c.find('{'+NS+'}f') is not None:
                            formula+=1
                            if v is None:raise ValueError('公式没有缓存值，请在 Excel 中计算并保存后重试')
                        if typ=='s':value=strings[int(value)]
                        elif typ=='inlineStr':value=''.join(t.text or '' for t in c.iter('{'+NS+'}t'))
                        elif typ=='e':raise ValueError('工作表含公式错误：'+c.get('r',''))
                        if value:
                            if cn>MAX_COLS:raise ValueError('最多支持 256 个数据列')
                            values[cn]=value;width=max(width,cn);total+=1
                    if values:rows[rn]=values
                if total>1000000:raise ValueError('工作簿最多支持 100 万个非空单元格')
                sheets.append(dict(name=s.get('name',''),rows=rows,width=width,last=max(rows,default=0),formulas=formula))
            return sheets
    except (zipfile.BadZipFile,KeyError,ET.ParseError,IndexError) as e:raise ValueError('无法读取 .xlsx 工作簿，请检查文件格式') from e

def inspect(db,dbpath,b,lid):
    try:raw=base64.b64decode(b.get('data',''),validate=True)
    except ValueError:raise ValueError('上传内容无效')
    if not 0<len(raw)<=MAX_BYTES:raise ValueError('请选择 14 MB 以内的 .xlsx 文件')
    sheets=read(io.BytesIO(raw))
    with tempfile.NamedTemporaryFile(suffix='.xlsx',dir=language_exchange.STAGING.name,delete=False) as f:f.write(raw);path=Path(f.name)
    token=language_exchange.stage(dbpath,path,'excel-import')
    return dict(token=token,layers=annotations.layers(db,lid),sheets=[dict(index=i,name=s['name'],last=s['last'],width=s['width'],formulas=s['formulas'],sample=[[s['rows'].get(r,{}).get(c,'') for c in range(1,s['width']+1)] for r in range(1,min(s['last'],12)+1)]) for i,s in enumerate(sheets)])

def plan(db,dbpath,b,lid):
    sheets=read(language_exchange.staged(dbpath,b.get('token'),'excel-import'))
    defs=annotations.layers(db,lid);known={d['id']:d for d in defs};plans=[];seen=set()
    configs=b.get('sheets',[])
    if not isinstance(configs,list) or not configs:raise ValueError('请选择至少一个工作表')
    for cfg in long_tasks.steps(configs):
        index=cfg.get('index')
        if type(index)!=int or not 0<=index<len(sheets) or index in seen:raise ValueError('工作表选择无效或重复')
        seen.add(index);sheet=sheets[index];title=str(cfg.get('title','')).strip()
        if not title:raise ValueError('请填写每个工作表的文本标题')
        start=cfg.get('start',2)
        if type(start)!=int or not 1<=start<=MAX_ROWS:raise ValueError('起始行无效')
        mappings=cfg.get('mappings',[]);targets=set();columns=set()
        for m in long_tasks.steps(mappings):
            c=m.get('column');t=m.get('target')
            if type(c)!=int or not 1<=c<=sheet['width'] or c in columns:raise ValueError('列映射无效或重复')
            if t not in ('form','gloss','ipa','translation','notes','reduplication') and t not in known:raise ValueError('标注层已删除或不属于当前语言，请重新匹配')
            if t in targets:raise ValueError('同一标注行只能匹配一个 Excel 列')
            if not isinstance(m.get('separator',' '),str) or len(m.get('separator',' '))>100:raise ValueError('连接符过长')
            targets.add(t);columns.add(c)
        if not {'form','gloss'}<=targets:raise ValueError('请成对指定语素列和标注列；单个格子允许为空')
        # Optional ID column preserves completely empty sentences and blank slots on roundtrip.
        idcol=cfg.get('sentence_column') or None
        if idcol is not None and (type(idcol)!=int or not 1<=idcol<=sheet['width']):raise ValueError('句号列无效')
        slotcol=cfg.get('slot_column') or None
        if slotcol is not None and (type(slotcol)!=int or not 1<=slotcol<=sheet['width']):raise ValueError('词格序号列无效')
        groups=[];group=[];lastid=None;partial=0;empty_slots=0
        for rn in long_tasks.steps(range(start,sheet['last']+1)):
            row=sheet['rows'].get(rn,{})
            sid=row.get(idcol,'') if idcol else ''
            populated=any(row.get(c,'').strip() for c in columns)
            if not populated and not sid:
                if group:groups.append(group);group=[]
                lastid=None;continue
            if idcol and sid and lastid is not None and sid!=lastid and group:groups.append(group);group=[]
            if sid:lastid=sid
            group.append((rn,row))
        if group:groups.append(group)
        sentences=[]
        for group in long_tasks.steps(groups):
            body=dict(function='pass',ipa='',translation='',notes='',words=[],raw='',line=None,edited=True);cells=[]
            for wi,(rn,row) in long_tasks.steps(enumerate(group)):
                values={m['target']:row.get(m['column'],'') for m in mappings}
                form=values['form'];gloss=values['gloss']
                if slotcol and row.get(slotcol)=='0':
                    if form or gloss or any(values.get(t) for t,d in known.items() if d.get('anchor','word')=='word'):raise ValueError('空句标记行含词级数据，请核对词格序号列')
                    continue
                partial+=int(bool(form.strip())!=bool(gloss.strip()));empty_slots+=int(not form.strip() and not gloss.strip())
                wi=len(body['words'])
                body['words'].append(dict(form=form,gloss=gloss,form_kind='string',gloss_kind='string'))
                for m in long_tasks.steps(mappings):
                    t=m['target'];v=values[t]
                    if t in known and known[t].get('anchor','word')=='word' and v:cells.append(dict(word=wi,layer_id=t,value=v))
            for m in long_tasks.steps(mappings):
                t=m['target']
                if t in ('form','gloss') or t in known and known[t].get('anchor','word')=='word':continue
                value=m.get('separator',' ').join(row.get(m['column'],'') for _,row in group if row.get(m['column'],'')!='')
                if t in known:
                    if value:cells.append(dict(word=None,layer_id=t,value=value))
                else:body[t]=value
            if body.get('reduplication'):
                import reduplication
                content=reduplication.PREFIX+body.pop('reduplication')+'\n'
                reduplication.import_prefix(content,len(content),body)
                reduplication.fork(body)
            sentences.append(dict(body=body,cells=cells,first_row=group[0][0]))
        plans.append(dict(index=index,title=title,sentences=sentences,partial=partial,empty_slots=empty_slots))
    signature=hashlib.sha256(json.dumps([lid,defs,plans],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return plans,signature

def preview(db,dbpath,b,lid):
    plans,signature=plan(db,dbpath,b,lid)
    return dict(signature=signature,texts=[dict(title=p['title'],sentences=len(p['sentences']),slots=sum(len(s['body']['words']) for s in p['sentences']),partial=p['partial'],empty_slots=p['empty_slots'],examples=p['sentences'][:3]) for p in plans])

def apply(db,dbpath,b,lid):
    plans,signature=plan(db,dbpath,b,lid)
    if signature!=b.get('signature'):raise ValueError('预览或标注层设置已变化，请重新预览')
    ids=[];count=0
    for p in long_tasks.steps(plans):
        tid=str(uuid.uuid4());ids.append(tid)
        db.execute('INSERT INTO texts(id,title,source,original,digest,errors,language_id) VALUES(?,?,?,?,?,?,?)',(tid,p['title'],str(b.get('filename','Excel')),'',str(uuid.uuid4()),'[]',lid))
        for position,s in long_tasks.steps(enumerate(p['sentences'],1)):
            rid=str(uuid.uuid4());body=analyze(s['body'])
            db.execute('INSERT INTO entries(id,text_id,position,body) VALUES(?,?,?,?)',(rid,tid,position,json.dumps(body,ensure_ascii=False)))
            lexicon.sync_entry(db,rid);units=annotations.units(db,'corpus',rid,body)
            for c in long_tasks.steps(s['cells']):
                uid=annotations.SENTENCE if c['word'] is None else units[c['word']]['id']
                db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,1)',(str(uuid.uuid4()),'corpus',rid,uid,c['layer_id'],c['value']))
            count+=1
    return dict(ok=True,ids=ids,count=count)

def workbook(sheets):
    """Minimal interoperable OOXML writer for literal corpus text, including = prefixes."""
    out=io.BytesIO();names=set();actual=[]
    def pack(tag,attrs=None):return ET.Element(tag,attrs or {})
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        types=pack('Types',{'xmlns':'http://schemas.openxmlformats.org/package/2006/content-types'})
        for ext,ct in [('rels','application/vnd.openxmlformats-package.relationships+xml'),('xml','application/xml')]:ET.SubElement(types,'Default',Extension=ext,ContentType=ct)
        wb=pack('workbook',{'xmlns':NS,'xmlns:r':REL});ss=ET.SubElement(wb,'sheets');rels=pack('Relationships',{'xmlns':'http://schemas.openxmlformats.org/package/2006/relationships'})
        def write(name,root):z.writestr(name,ET.tostring(root,encoding='utf-8',xml_declaration=True))
        ET.SubElement(types,'Override',PartName='/xl/workbook.xml',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml')
        for i,(title,rows) in enumerate(sheets,1):
            base=re.sub(r'[\\/*?:\[\]]','_',title).strip("'")[:31] or '文本';name=base;n=1
            while name.casefold() in names:n+=1;tail=' ('+str(n)+')';name=base[:31-len(tail)]+tail
            names.add(name.casefold());actual.append(name)
            ET.SubElement(ss,'sheet',name=name,sheetId=str(i),attrib={'r:id':'rId'+str(i)})
            ET.SubElement(rels,'Relationship',Id='rId'+str(i),Type=REL+'/worksheet',Target='worksheets/sheet'+str(i)+'.xml')
            ET.SubElement(types,'Override',PartName='/xl/worksheets/sheet'+str(i)+'.xml',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml')
            root=pack('worksheet',{'xmlns':NS});views=ET.SubElement(root,'sheetViews');view=ET.SubElement(views,'sheetView',workbookViewId='0');ET.SubElement(view,'pane',ySplit='1',topLeftCell='A2',activePane='bottomLeft',state='frozen')
            cols=ET.SubElement(root,'cols')
            for c in range(1,len(rows[0])+1):ET.SubElement(cols,'col',min=str(c),max=str(c),width='12' if c==1 else '28',customWidth='1')
            data=ET.SubElement(root,'sheetData')
            for rn,values in enumerate(rows,1):
                row=ET.SubElement(data,'row',r=str(rn))
                for cn,value in enumerate(values,1):
                    if value=='':continue
                    value=str(value)
                    if len(value)>32767:raise ValueError('文本超过 Excel 单元格 32767 字符上限，请改用完整备份或 Typst 导出')
                    if re.search('[\x00-\x08\x0b\x0c\x0e-\x1f]',value):raise ValueError('文本含 Excel 不支持的控制字符')
                    cell=ET.SubElement(row,'c',r=colname(cn)+str(rn),t='inlineStr');inline=ET.SubElement(cell,'is');ET.SubElement(inline,'t',{'xml:space':'preserve'}).text=value
            write('xl/worksheets/sheet'+str(i)+'.xml',root)
        write('xl/workbook.xml',wb);write('xl/_rels/workbook.xml.rels',rels);write('[Content_Types].xml',types)
        rootrels=pack('Relationships',{'xmlns':'http://schemas.openxmlformats.org/package/2006/relationships'});ET.SubElement(rootrels,'Relationship',Id='rId1',Type=REL+'/officeDocument',Target='xl/workbook.xml');write('_rels/.rels',rootrels)
    return out.getvalue()

def export(db,b,lid):
    ids=b.get('ids',[])
    if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids):raise ValueError('请选择当前语言的文本')
    defs=annotations.layers(db,lid);sheets=[]
    for tid in ids:
        text=db.execute('SELECT * FROM texts WHERE id=? AND language_id=?',(tid,lid)).fetchone()
        if not text:raise ValueError('文本不存在或不属于当前语言')
        has_redup=db.execute("SELECT 1 FROM entries WHERE text_id=? AND json_array_length(body,'$.reduplications')>0 LIMIT 1",(tid,)).fetchone() is not None
        rows=[['SentenceID','WordIndex','Morph','Gloss','IPA','Translation','Notes']+[d['name'] for d in defs]+(['Reduplication'] if has_redup else [])]
        for number,r in enumerate(gloss_inheritance.iter_rows(db,db.execute('SELECT id,body FROM entries WHERE text_id=? ORDER BY position,id',(tid,)),'corpus'),1):
            body=gloss_inheritance.load(db,'corpus',r['id'],r['body'])
            if body.get('language_id') and body['language_id']!=lid:raise ValueError('文本含其他语言的句子，请先按语言拆分文本后导出')
            units=annotations.units(db,'corpus',r['id'],body);cells={(c['unit_id'],c['layer_id']):c['value'] for c in db.execute("SELECT * FROM annotation_cells WHERE owner_kind='corpus' AND record_id=?",(r['id'],))}
            for i,w in enumerate(body['words'] or [dict(form='',gloss='')]):
                uid=units[i]['id'] if i<len(units) else ''
                rows.append([str(number),str(i+1) if body['words'] else '0',w['form'],w['gloss']]+[body.get(k,'') if i==0 else '' for k in ('ipa','translation','notes')]+[cells.get((uid,d['id']),'') if d.get('anchor','word')=='word' else cells.get((annotations.SENTENCE,d['id']),'') if i==0 else '' for d in defs])
                if has_redup:
                    import reduplication
                    rows[-1].append(json.dumps(reduplication.portable(body),ensure_ascii=False) if i==0 and body.get('reduplications') else '')
            rows.append([])
        if len(rows)>MAX_ROWS:raise ValueError('单文本超过 200000 行，请拆分文本后导出')
        sheets.append((text['title'],rows))
    if b.get('separate'):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            for i,(title,rows) in enumerate(sheets,1):z.writestr(str(i)+'-'+re.sub(r'[\\/:*?"<>|]','_',title)[:100]+'.xlsx',workbook([(title,rows)]))
        raw=out.getvalue();name='语料文本.zip'
    else:raw=workbook(sheets);name='语料文本.xlsx'
    return dict(name=name,data=base64.b64encode(raw).decode(),texts=len(sheets))

def dispatch(db,dbpath,action,b,lid):
    languages.require(db,lid)
    if action=='inspect':return inspect(db,dbpath,b,lid)
    if action=='preview':return preview(db,dbpath,b,lid)
    if action=='import':return apply(db,dbpath,b,lid)
    if action=='export':
        result=export(db,b,lid)
        with tempfile.NamedTemporaryFile(suffix=Path(result['name']).suffix,dir=language_exchange.STAGING.name,delete=False) as f:
            f.write(base64.b64decode(result['data']));path=Path(f.name)
        result['token']=language_exchange.stage(dbpath,path,'excel-export')
        return result
    raise ValueError('未知 Excel 操作')
