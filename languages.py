"""Language catalogue, additive migration, and language-specific validation."""
import long_tasks
import json
import re
import uuid
import lexicon
import font_catalog
import annotations
import grammar
from corpus import analyze, clean, parse, export_entry

DEFAULT = 'ordos'
FONTS = ('IPAPANNEW', 'Junicode', 'serif', 'sans-serif')


def initialize(db):
    first_catalogue=not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='languages'").fetchone()
    db.execute("CREATE TABLE IF NOT EXISTS languages(id TEXT PRIMARY KEY,name TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{}',revision INTEGER NOT NULL DEFAULT 1)")
    if first_catalogue:
        db.execute('INSERT OR IGNORE INTO languages VALUES(?,?,?,1)',(DEFAULT,'Ordos / 鄂尔多斯',json.dumps({'aliases':'鄂尔多斯蒙古语','ipa_font':'IPAPANNEW','annotation_font':'Junicode'},ensure_ascii=False)))
    for table in ('texts','folders','undo_steps'):
        if 'language_id' not in [r['name'] for r in db.execute('PRAGMA table_info('+table+')')]:
            db.execute("ALTER TABLE "+table+" ADD COLUMN language_id TEXT NOT NULL DEFAULT 'ordos'")
    db.execute('CREATE INDEX IF NOT EXISTS texts_language ON texts(language_id)')
    db.execute('CREATE INDEX IF NOT EXISTS folders_language ON folders(language_id,position)')
    db.execute('CREATE INDEX IF NOT EXISTS entries_text ON entries(text_id,position)')
    db.execute('CREATE INDEX IF NOT EXISTS undo_language ON undo_steps(language_id,id)')
    db.execute('CREATE TABLE IF NOT EXISTS undo_scopes(language_id TEXT PRIMARY KEY,step_limit INTEGER NOT NULL DEFAULT 20,generation INTEGER NOT NULL DEFAULT 0)')
    if first_catalogue:db.execute("INSERT OR IGNORE INTO undo_scopes SELECT 'ordos',step_limit,generation FROM undo_settings WHERE id=1")


def require(db, lid):
    row=db.execute('SELECT * FROM languages WHERE id=?',(lid,)).fetchone()
    if not row: raise ValueError('请选择一个有效的语言')
    return row


def save(db, body):
    previous_glossary={}
    name=body.get('name','').strip()
    if not name: raise ValueError('请填写语言名称')
    data=body.get('metadata',{})
    if not isinstance(data,dict): raise ValueError('语言信息格式不正确')
    grammar.ignored_values(data)
    import grammaticality
    if grammaticality.KEY in data:data[grammaticality.KEY]=grammaticality.clean(data[grammaticality.KEY])
    if 'dictionary_layout' in data:
        import dictionary_layout
        dictionary_layout.validate(data['dictionary_layout'])
    if 'lexeme_quick_edit' in data:
        import quick_edit
        quick_edit.configuration(data)
    if 'homophone_phonology' in data:
        import phonology
        data['homophone_phonology']=phonology.validate_stored(data['homophone_phonology'])
    if 'paradigm_templates' in data:
        import paradigms
        data['paradigm_templates']=paradigms.templates(data['paradigm_templates'])
    for field,default in [('ipa_font','IPAPANNEW'),('annotation_font','Junicode'),('gloss_font','Junicode'),('translation_font','sans-serif')]:
        if not font_catalog.valid_font(data.get(field,default)): raise ValueError('请选择列表中的字体')
    for field in ('ipa_variant','morpheme_variant','gloss_variant','translation_variant'):
        if data.get(field,'regular') not in ('regular','italic','bold','bolditalic'): raise ValueError('请选择有效的字体变体')
    for field in ('ipa_scale','morpheme_scale','gloss_scale','translation_scale'):
        value=data.get(field,1)
        if type(value) not in (int,float) or value not in (.6,.7,.8,.9,1,1.1,1.2,1.3,1.5,2):raise ValueError('请选择有效的行字号比例')
    glossary=data.get('glossary',{})
    boundaries=data.get('phonological_boundaries',{})
    if not isinstance(boundaries,dict) or any(not isinstance(k,str) or not re.fullmatch(r'#+',k) or not isinstance(v,str) or not v.strip() for k,v in boundaries.items()):
        raise ValueError('音系边界请按“# = 边界名称”逐行填写，名称不能为空')
    if not isinstance(glossary,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in glossary.items()):
        raise ValueError('标注缩写表格式不正确')
    for field in ('check_boundaries','check_commands','check_glossary','require_ipa','require_translation'):
        if field in data and not isinstance(data[field],bool): raise ValueError('核查规则必须是开关')
    lid=body.get('id')
    if lid:
        old=require(db,lid)
        previous_glossary=json.loads(old['metadata']).get('glossary',{})
        if old['revision']!=body.get('revision'): raise ValueError('语言信息已更新，请重新打开')
        db.execute('UPDATE languages SET name=?,metadata=?,revision=revision+1 WHERE id=?',(name,json.dumps(data,ensure_ascii=False),lid))
    else:
        lid=str(uuid.uuid4())
        db.execute('INSERT INTO languages VALUES(?,?,?,1)',(lid,name,json.dumps(data,ensure_ascii=False)))
    grammar.sync_legacy(db,lid,previous_glossary,glossary)
    lexicon.categories.initialize_forms(db,lid)
    return {'ok':True,'id':lid}


def request_scope(db, path, body):
    """Resolve the owner from stored records, never trust a client scope for ownership."""
    if path=='save-language' and not body.get('id'):
        row=db.execute('SELECT id FROM languages WHERE id=?',(body.get('_language',DEFAULT),)).fetchone()
        row=row or db.execute('SELECT id FROM languages ORDER BY name,id LIMIT 1').fetchone()
        return row[0] if row else 'all'
    ids=[]
    if path.startswith('fieldwork-note-') and body.get('id'):
        row=db.execute('SELECT language_id FROM fieldwork_notes WHERE id=?',(body['id'],)).fetchone()
        if row:ids.append(row[0])
    if path=='morpheme-unassign':
        r=db.execute('SELECT m.language_id FROM morpheme_components c JOIN morphemes m ON m.id=c.morpheme_id WHERE c.id=?',(body.get('id'),)).fetchone()
        if r:ids.append(r[0])
    if path.startswith('morpheme-'):
        for key in ('id','target_id','morpheme_id'):
            if body.get(key):
                r=db.execute('SELECT language_id FROM morphemes WHERE id=?',(body[key],)).fetchone()
                if r:ids.append(r[0])
        if body.get('lexeme_id'):
            r=db.execute('SELECT language_id FROM lexemes WHERE id=?',(body['lexeme_id'],)).fetchone()
            if r:ids.append(r[0])
    if path=='word-transfer':
        ids.extend(annotations.owner(db,body[k]['kind'],body[k]['id'])[2] for k in ('source','target') if not body[k].get('new'))
    if path=='collaborator-save':
        import collaborators
        ids.append(collaborators.owner(db,body['kind'],body['id']))
    if path in ('class-save','class-delete') and body.get('id'):
        row=db.execute('SELECT language_id FROM category_classes WHERE id=?',(body['id'],)).fetchone()
        if row:ids.append(row[0])
    if path in ('grammar-save','grammar-delete') and body.get('id'):
        row=db.execute('SELECT language_id FROM grammar_tags WHERE id=?',(body['id'],)).fetchone()
        if row:ids.append(row[0])
    elif path in ('code-save','code-delete','code-link','code-unlink'):
        ids.append(annotations.owner(db,body['kind'],body['record_id'])[2])
    elif path in ('annotation-save','inline-save','grammaticality-save','segmentation-save','segmentation-link','sentence-dictionary-preview','sentence-dictionary-apply','sentence-gloss-preview','sentence-gloss-apply','gloss-source-save'):
        ids.append(annotations.owner(db,body['kind'],body['id'])[2])
    elif path in ('layer-save','layer-delete') and body.get('id'):
        row=db.execute('SELECT language_id FROM annotation_layers WHERE id=?',(body['id'],)).fetchone()
        if row:ids.append(row[0])
    elif path in ('writing-save','writing-delete','example-save','example-delete') and body.get('id'):
        table='writing_types' if path.startswith('writing-') else 'dictionary_examples'
        row=db.execute('SELECT language_id FROM '+table+' WHERE id=?',(body['id'],)).fetchone()
        if row:ids.append(row[0])
    elif path in ('lexeme-save','lexeme-delete','lexeme-to-morpheme','lexeme-to-morpheme-preview') and body.get('id'):
        row=db.execute('SELECT language_id FROM lexemes WHERE id=?',(body['id'],)).fetchone()
        if row: ids.append(row[0])
    elif path=='lexeme-link':
        row=db.execute('SELECT t.language_id FROM corpus_units u JOIN entries e ON e.id=u.entry_id JOIN texts t ON t.id=e.text_id WHERE u.id=?',(body.get('unit_id'),)).fetchone()
        if row: ids.append(row[0])
    elif path=='lexeme-unlink':
        items=body.get('items',[body])
        for item in items if isinstance(items,list) else []:
            row=db.execute('SELECT language_id FROM lexical_links WHERE id=?',(item.get('id') if isinstance(item,dict) else None,)).fetchone()
            if row:ids.append(row[0])
    elif path=='dictionary-examples-unlink':
        row=db.execute('SELECT language_id FROM dictionary_targets WHERE id=?',(body.get('lexeme_id'),)).fetchone()
        if row:ids.append(row[0])
    elif path in ('save','delete-entry','reorder-entry','duplicate-entry'):
        row=db.execute('SELECT t.language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?',(body.get('id'),)).fetchone()
        if row: ids.append(row[0])
    elif path in ('organize-text','save-text-info','delete-text','add','move','copy-entries','merge','split','sentence-create'):
        keys={'sentence-create':['text_id'],'add':['text_id'],'move':['source_id','target_id'],'copy-entries':['source_id','target_id'],'merge':['first_id','second_id'],'split':['source_id']}.get(path,['id'])
        for key in keys:
            row=db.execute('SELECT language_id FROM texts WHERE id=?',(body.get(key),)).fetchone()
            if row: ids.append(row[0])
    elif path in ('save-folder','delete-folder','order-folder') and body.get('id'):
        row=db.execute('SELECT language_id FROM folders WHERE id=?',(body['id'],)).fetchone()
        if row: ids.append(row[0])
    elif path=='save-language' and body.get('id'):
        ids.append(body['id'])
    if len(set(ids))>1: raise ValueError('移动和合并须在同一语言内进行；混合语言请在句子信息中指定')
    lid=ids[0] if ids else body.get('_language',DEFAULT)
    if body.get('_language') not in (None,'all',lid): raise ValueError('语言范围已变化，请重新打开后操作')
    require(db,lid)
    return lid


def annotate(entry, default, catalogue):
    lid=entry.get('language_id') or default
    lang=catalogue.get(lid,catalogue[default])
    data=json.loads(lang['metadata'])
    analyze(entry)
    if not data.get('check_boundaries',True): entry['warnings']=[w for w in entry['warnings'] if '边界' not in w]
    if not data.get('check_commands',True): entry['warnings']=[w for w in entry['warnings'] if 'Typst' not in w]
    if data.get('require_ipa') and not entry['ipa'].strip(): entry['warnings'].append('尚未填写 IPA')
    if data.get('require_translation') and not entry['translation'].strip(): entry['warnings'].append('尚未填写自由翻译')
    for field in ('ipa_variant','morpheme_variant'):
        if data.get(field,'regular') not in ('regular','italic','bold','bolditalic'): raise ValueError('请选择有效的字体变体')
    glossary=data.get('glossary',{})
    if data.get('check_glossary'):
        for n,w in enumerate(entry['words'],1):
            if w.get('unit_type') in ('phonological_boundary','punctuation'): continue
            unknown=grammar.unknown_for_warning(w['gloss'],lid,lang['metadata'])
            if unknown: entry['warnings'].append(f'第 {n} 词：疑似语法标签尚未登记（请确认） '+', '.join(unknown))
    entry.update(language_id=entry.get('language_id') or '',effective_language_id=lid,language_name=lang['name'],text_language_id=default,
                 language_fonts={'ipa':data.get('ipa_font','IPAPANNEW'),'annotation':data.get('annotation_font','Junicode')})
    return entry


def import_bundle(db, bundle, lid, media_files=None,fresh_references=False):
    """Copy one language's exported data with fresh record IDs in one transaction."""
    require(db,lid)
    if bundle.get('format')!='corpus-language-v1': raise ValueError('请选择单语言数据导出的 JSON 文件')
    source_id=bundle['language']['id']
    # Keep a target language's established phonology. Empty targets inherit the
    # exported inventory and classifications, whose keys are readings, not IDs.
    source_meta=bundle['language'].get('metadata','{}')
    source_meta=json.loads(source_meta) if isinstance(source_meta,str) else source_meta
    target_meta=json.loads(require(db,lid)['metadata'])
    layouts={}
    if source_meta.get('dictionary_layout') and (fresh_references or not target_meta.get('dictionary_layout')):layouts[lid]=source_meta['dictionary_layout']
    if source_meta.get('homophone_phonology') and not target_meta.get('homophone_phonology'):
        import phonology
        incoming=source_meta['homophone_phonology']
        target_meta['homophone_phonology']=phonology.validate_stored(incoming)
        db.execute('UPDATE languages SET metadata=?,revision=revision+1 WHERE id=?',(json.dumps(target_meta,ensure_ascii=False),lid))
    mapping={source_id:lid}
    import grammaticality
    grammaticality.merge_catalog(db,lid,source_meta)
    for ref in long_tasks.steps(bundle.get('referenced_languages',[])):
        existing=None if fresh_references else db.execute('SELECT id FROM languages WHERE id=?',(ref['id'],)).fetchone()
        if existing: mapping[ref['id']]=existing[0]
        else:
            refmeta=json.loads(ref['metadata'])
            if 'grammar_tags' in bundle:refmeta['glossary']={}
            name=ref['name'];n=1
            while fresh_references and any(r[0].strip().casefold()==name.strip().casefold() for r in db.execute('SELECT name FROM languages')):
                n+=1;name=ref['name']+'（引用 '+str(n)+'）'
            mapping[ref['id']]=save(db,{'name':name,'metadata':refmeta})['id']
            if refmeta.get('dictionary_layout'):layouts[mapping[ref['id']]]=refmeta['dictionary_layout']
    folder_map={}
    for folder in long_tasks.steps(bundle.get('folders',[])):
        fid=str(uuid.uuid4());folder_map[folder['id']]=fid
        data=json.loads(folder['metadata'])
        if not isinstance(data,dict): raise ValueError('文件夹信息格式不正确')
        position=db.execute('SELECT COALESCE(MAX(position),0)+1 FROM folders WHERE language_id=?',(lid,)).fetchone()[0]
        db.execute('INSERT INTO folders(id,name,position,metadata,language_id) VALUES(?,?,?,?,?)',(fid,folder['name'],position,json.dumps(data,ensure_ascii=False),lid))
    first=None;count=0;entry_map={};text_map={}
    for text in long_tasks.steps(bundle.get('texts',[])):
        tid=str(uuid.uuid4());first=first or tid;text_map[text['id']]=tid
        db.execute('INSERT INTO texts(id,title,source,original,digest,errors,language_id) VALUES(?,?,?,?,NULL,?,?)',(tid,text['title'],text.get('source',''),text.get('original',''),text.get('errors','[]'),lid))
        info=text.get('info') or {}
        m=json.loads(info.get('metadata','{}'))
        if not isinstance(m,dict): raise ValueError('文本信息格式不正确')
        db.execute('INSERT INTO text_info VALUES(?,?,?,1)',(tid,folder_map.get(info.get('folder_id')),json.dumps(m,ensure_ascii=False)))
        for position,record in long_tasks.steps(enumerate(text.get('entries',[]),1)):
            entry=json.loads(record['body'])
            parsed,errors=parse(export_entry(entry))
            if errors or len(parsed)!=1: raise ValueError('导入文件含无效句子')
            if entry.get('language_id'):
                if entry['language_id'] not in mapping: raise ValueError('导入文件缺少句子引用的语言信息')
                entry['language_id']=mapping[entry['language_id']]
            eid=str(uuid.uuid4());entry_map[record['id']]=eid
            grammaticality.strip_corpus(entry)
            if entry.get('reduplications'):
                import reduplication
                analyze(entry);reduplication.check_relations(entry);reduplication.fork(entry)
            db.execute('INSERT INTO entries(id,text_id,position,body) VALUES(?,?,?,?)',(eid,tid,position,json.dumps(analyze(entry),ensure_ascii=False)))
            count+=1
    imported=lexicon.import_bundle(db,bundle,mapping,entry_map,lid,layouts)
    import quick_edit
    quick_edit.import_settings(db,bundle,lid,imported['writing_types'])
    import timeline
    alignment_map={**entry_map,**{'independent:'+k:'independent:'+v for k,v in imported['examples'].items()}}
    imported['texts']=text_map
    people=timeline.import_bundle(db,bundle,lid,alignment_map,imported['writing_types'],mapping,media_files,imported)
    import collaborators
    collaborators.import_links(db,bundle,{'text':text_map,'corpus':entry_map,'independent':imported['examples']},people)
    collaborators.initialize(db)
    import grammar_survey
    grammar_survey.import_bundle(db,bundle,lid,entry_map,imported['examples'],imported['writing_types'],people)
    import fieldwork_notes
    fieldwork_notes.import_bundle(db,bundle,lid,imported['writing_types'])
    import code_switching
    code_switching.import_bundle(db,bundle,lid,entry_map,imported['examples'],imported['units'],imported['independent_units'],imported['timeline_maps'])
    return {'ok':True,'id':first,'count':count}
