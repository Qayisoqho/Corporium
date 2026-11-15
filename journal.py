"""Bounded, transactional undo journal. Temporary triggers capture only touched rows."""
import object_media
import json
import record_sources
import hashlib
import io
from contextvars import ContextVar
from datetime import datetime, timezone
import lexicon
import timeline
import timeline_colors
import collaborators
import grammar_survey
import fieldwork_notes
import code_switching
import gloss_inheritance
import independent_links
import undo_codec

decode_changes=undo_codec.decode

action = ContextVar('action', default=None)
# Only for validation writes inside an always-rolled-back savepoint.
previewing = ContextVar('journal_previewing', default=False)
scope = ContextVar('language_scope', default='ordos')
LABELS = dict(zip(('/api/'+s for s in ('import','new-text','save','add','delete-entry','delete-text','move','merge','save-text-info','save-folder','delete-folder','order-folder')),
                  ('导入文本','新建文本','编辑句子','添加句子','删除句子','删除文本','移动句子','合并文本','修改文本信息','保存文件夹','删除文件夹','调整文件夹顺序')))
LABELS.update({'/api/morpheme-'+a:n for a,n in [('save','保存语素'),('assign','整理组分语素'),('merge','归并语素'),('delete','删除语素'),('unassign','解除组分语素关联')]})
LABELS['/api/object-media-save']='管理图片与录音'
LABELS['/api/dictionary-copy']='复制词典条目'
LABELS['/api/recorder-keep']='关联现场录音'
LABELS['/api/homophone-phonology-save']='编辑同音语素表音系与归类'
LABELS['/api/synonym-save']='编辑义项同义关系'
LABELS['/api/collaborator-save']='编辑材料合作者'
LABELS['/api/save-language'] = '修改语言信息'
LABELS['/api/language-package-import']='导入新语言数据包'
LABELS['/api/import-language'] = '导入语言数据'
LABELS.update({'/api/lexeme-save':'保存词条','/api/lexeme-delete':'删除词条','/api/lexeme-link':'关联词典用例','/api/lexeme-unlink':'解除词典关联'})
LABELS['/api/lexeme-auto-link']='批量关联词典'
LABELS['/api/dictionary-examples-unlink']='解除独立例句词典关联'
LABELS['/api/example-links-save']='保存独立例句词典关联'
LABELS['/api/lexeme-to-morpheme']='词条转为语素'
LABELS['/api/split']='拆分文本'
LABELS['/api/duplicate-entry']='复制句子'
LABELS['/api/reorder-entry']='调整句子顺序'
LABELS.update({'/api/class-save':'保存分类','/api/class-delete':'删除分类'})
LABELS['/api/dictionary-replace-apply']='查找替换词典'
LABELS['/api/dictionary-batch-apply']='批量编辑词条分类与标签'
LABELS.update({'/api/dict-org-'+action:label for action,label in [('class-save','保存语义分类'),('class-delete','删除语义分类'),('assign','词条语义归类'),('order-save','保存词典排序方案'),('order-copy','复制词典排序方案'),('order-delete','删除词典排序方案')]})
LABELS['/api/text-replace-apply']='查找替换文本'
LABELS['/api/punctuation-apply']='识别并拆分标点'
LABELS['/api/word-transfer']='跨句复制或移动词格'
LABELS['/api/inline-save']='编辑例句标注与备注'
LABELS['/api/sentence-create']='新建句子'
LABELS['/api/excel-import']='导入 Excel 文本'
LABELS['/api/docx-import']='导入 Word 文本'
LABELS['/api/organize-text']='移动或排序文本'
LABELS['/api/copy-text']='复制文本'
LABELS['/api/copy-entries']='跨文本复制句子'
LABELS['/api/segmentation-save']='编辑语素组合与中缀分析'
LABELS['/api/segmentation-link']='关联形态分析与词典'
LABELS.update({'/api/grammar-save':'保存语法标签','/api/grammar-delete':'删除语法标签定义'})
LABELS.update({'/api/grammar-register-batch':'批量登记语法标签','/api/grammar-ignore':'忽略标签候选','/api/grammar-unignore':'恢复标签候选检查'})
LABELS.update({'/api/layer-save':'保存标注层','/api/layer-delete':'删除标注层及内容','/api/annotation-save':'编辑附加标注'})
LABELS['/api/layer-order']='调整标注层顺序'
LABELS.update({'/api/writing-save':'保存书写类型','/api/writing-delete':'删除书写类型','/api/example-save':'保存独立例句','/api/example-delete':'删除独立例句'})
LABELS.update({'/api/survey-'+a:label for a,label in {'save':'编辑调查提纲','template':'导入调查模板','delete':'删除调查条目','copy':'复制调查条目','order':'调整调查顺序','move':'移动调查条目','notes':'编辑研究笔记','evidence':'编辑调查例证','unlink':'移除调查例证引用','new-example':'新建调查例句'}.items()})
LABELS.update({'/api/fieldwork-note-'+a:label for a,label in {'create':'新建调查笔记','save':'编辑调查笔记','copy':'复制调查笔记','delete':'删除调查笔记','reorder':'调整调查笔记顺序'}.items()})
import example_groups
TABLES = ('texts','entries','folders','text_info','languages') + lexicon.TABLES + timeline.TABLES + collaborators.TABLES + grammar_survey.TABLES + fieldwork_notes.TABLES + object_media.TABLES + code_switching.TABLES + gloss_inheritance.TABLES + example_groups.TABLES
LABELS.update({'/api/example-group-save':'编辑独立例句组','/api/example-group-delete':'解散独立例句组'})
LABELS.update({'/api/code-'+a:label for a,label in {'save':'编辑正文语码标记','delete':'移除正文语码标记','link':'关联语码时间片段','unlink':'解除语码时间关联'}.items()})
LABELS.update({'/api/timeline-'+key:label for key,label in {'speaker-save':'保存合作者','speaker-delete':'删除合作者','code-save':'保存语言标记','code-delete':'删除语言标记','delete-track':'删除空轨道'}.items()})
LABELS.update({'/api/timeline-'+key:label for key,label in {'create':'新建时间轴','duplicate':'复制时间轴','delete':'删除时间轴','rename':'重命名时间轴','reorder':'调整时间轴顺序','text-order':'设置按时间轴自动排序','replace':'更换媒体并调整对齐','track':'保存时间轴轨道','interval':'编辑对齐区间','delete-interval':'删除对齐区间','split':'拆分时间区间','merge':'合并时间区间'}.items()})


LABELS.update({'/api/dict-org-layout-save':'调整分类显示层级','/api/dict-org-layout-move':'调整分类显示顺序'})

LABELS.update({'/api/sentence-dictionary-apply':'从例句收入词典并关联','/api/sentence-gloss-apply':'补全当前句空白标注'})
LABELS['/api/gloss-source-save']='修改本句标注来源'


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS undo_steps(id INTEGER PRIMARY KEY AUTOINCREMENT,label TEXT,created TEXT,changes TEXT,applied INTEGER);
    CREATE TABLE IF NOT EXISTS undo_settings(id INTEGER PRIMARY KEY,step_limit INTEGER,generation INTEGER);
    INSERT OR IGNORE INTO undo_settings VALUES(1,20,0);''')


def watch(db, changes=None, *, tables=TABLES):
    if changes is None:changes={}
    relational = record_sources.native(db)
    related = any(table in independent_links.TABLES for table in tables) and independent_links.snapshots.enabled(db)
    if related and isinstance(db,record_sources.Connection) and 'independent_links' in tables:
        db.audits_independent_links=True
    for table in tables:
        native = table in record_sources.TABLES and relational
        snapshot = table in independent_links.TABLES and related
        cols = record_sources.META[table] if native else [r['name'] for r in db.execute('PRAGMA table_info('+table+')')]
        def capture(kind, rid, *values, table=table, cols=cols, snapshot=snapshot):
            if previewing.get():return 0
            key = (table, rid)
            row = dict(zip(cols, values))
            if table in record_sources.TABLES:
                row['body'] = record_sources.image(db,table,row['id'],kind,row.get('body'))
            row['rowid'] = rid
            if snapshot:
                if table=='independent_links':
                    pending=getattr(db,'independent_appending',None) if kind=='insert' else None
                    if pending is not None:
                        for col in independent_links.snapshots.REF_COLUMNS:row.pop(col)
                        if row['id'] in pending:row['segmentation_ref']=pending[row['id']]
                    else:row=independent_links.image(db,row)
                else:row=independent_links.override_images(db,[row])[0]
            if key not in changes:
                changes[key] = [None if kind == 'insert' else row, None]
            changes[key][1] = None if kind == 'delete' else row
            return 0
        db.create_function('audit_'+table, -1, capture)
        batched_revisions = native and table=='dictionary_examples' and isinstance(db,record_sources.Connection)
        if batched_revisions:
            db.example_revision_journal=changes
            db.create_function('audit_example_revision_batch',0,lambda: int(getattr(db,'capturing_example_revisions',False)))
        # UPDATE needs both the initial and final row, including repeated updates.
        events = [('INSERT','insert','new'),('DELETE','delete','old'),('UPDATE','before','old')]
        if snapshot:events.append(('UPDATE','after','new'))
        for event, kind, ref in events:
            args = ','.join(ref+'.'+c for c in cols)
            tail = ''
            if event == 'UPDATE' and not snapshot:
                tail = "SELECT audit_%s('after',new.rowid,%s);" % (table, ','.join('new.'+c for c in cols))
            before = (native or snapshot) and event=='DELETE' or snapshot and kind=='before'
            timing = 'BEFORE' if before else 'AFTER'
            when = ' WHEN NOT audit_example_revision_batch()' if batched_revisions and event=='UPDATE' else ''
            db.execute(f"CREATE TEMP TRIGGER audit_{table}_{kind} {timing} {event} ON {table}{when} BEGIN "
                       f"SELECT audit_{table}('{kind}',{ref}.rowid,{args}); {tail} END")
    return changes


def trim(db):
    lid=scope.get()
    row=db.execute('SELECT step_limit FROM undo_scopes WHERE language_id=?',(lid,)).fetchone()
    limit=row[0] if row else 20
    db.execute('DELETE FROM undo_steps WHERE id IN (SELECT id FROM undo_steps WHERE language_id=? ORDER BY id DESC LIMIT -1 OFFSET ?)',(lid,limit))
    # Start at the small history table. The corpus can contain many more
    # sentences than the number with any retained edit history.
    db.execute('''DELETE FROM history WHERE id IN (SELECT h.id FROM history h
        CROSS JOIN entries e ON e.id=h.entry_id CROSS JOIN texts t ON t.id=e.text_id
        WHERE t.language_id=? ORDER BY h.id DESC LIMIT -1 OFFSET ?)''',(lid,limit))


def encode_changes(delta):
    """Keep the existing JSON format without a second giant Unicode string."""
    import long_tasks
    out=io.BytesIO();out.write(b'[')
    for i,change in enumerate(delta):
        if i%64==0:long_tasks.checkpoint(None,'正在整理撤销记录…')
        if i:out.write(b', ')
        out.write(json.dumps(change,ensure_ascii=False).encode('utf-8'))
    out.write(b']')
    return out.getvalue()


def portable_step(row):
    """Keep the established JSON backup's row-image format readable by older builds."""
    result=dict(row)
    try:
        changes=decode_changes(result['changes'])
    except ValueError:
        return result
    converted=False
    for change in changes:
        if change['table'] in independent_links.TABLES:
            for side in ('before','after'):
                image=change.get(side)
                if image:
                    portable=independent_links.portable_image(change['table'],image)
                    if image!=portable:
                        change[side]=portable
                        converted=True
            continue
        if change['table'] not in record_sources.TABLES:
            continue
        for side in ('before','after'):
            image=change.get(side)
            if image and isinstance(image.get('body'),dict):
                image['body']=json.dumps(image['body'],ensure_ascii=False)
                converted=True
    if converted:result['changes']=undo_codec.encode(changes)
    return result


def record(db, changes, label):
    # A newly created language is a stable container; its later edits are undoable.
    new_languages={b['id'] for (t,_),(a,b) in changes.items() if t=='languages' and a is None and b}
    delta = [{'table':t,'before':a,'after':b} for (t,_),(a,b) in changes.items() if a != b and not (t=='languages' and a is None) and not (t=='category_classes' and a is None and b and b['language_id'] in new_languages)]
    if not delta:
        return
    # These row images already include the binding changes made by the save.
    # Older journals may need inheritance rebuilt after restoring the rows.
    inheritance_sources=record_sources.TABLES|{'lexical_links',*independent_links.TABLES,*gloss_inheritance.TABLES}
    if any(change['table'] in inheritance_sources for change in delta):
        delta[0]['inheritance_complete']=True
    # Current transactions capture the synchronized units and segments too.
    # Older journals lack this proof and keep conservative reconciliation.
    synced=lexicon.synced_entries.get() or {}
    for change in delta:
        if change['table']=='dictionary_examples' and independent_links.revision_only(change['before'],change['after']):
            change['revision_only']=True
            for side in ('before','after'):
                change[side]={k:v for k,v in change[side].items() if k!='body'}
        if change['table']=='entries':
            before,after=change['before'],change['after'];eid=(after or before)['id']
            if eid in synced and record_sources.same_body(synced[eid],after['body'] if after else None):
                change['units_complete']=True
    if label == '移动句子':
        count = sum(c['table']=='entries' and c['before'] is not None and c['after'] is not None and c['before']['text_id']!=c['after']['text_id'] for c in delta)
        label = f'移动 {count} 条句子'
    lid=scope.get()
    db.execute('INSERT OR IGNORE INTO undo_scopes(language_id) VALUES(?)',(lid,))
    had_redo=db.execute('SELECT 1 FROM undo_steps WHERE language_id=? AND applied=0 LIMIT 1',(lid,)).fetchone()
    db.execute('DELETE FROM undo_steps WHERE applied=0 AND language_id=?',(lid,))
    now=datetime.now(timezone.utc);merged=False
    if label=='编辑调查笔记' and not had_redo and len(delta)==1 and delta[0]['table']=='fieldwork_notes':
        previous=db.execute('SELECT * FROM undo_steps WHERE language_id=? ORDER BY id DESC LIMIT 1',(lid,)).fetchone()
        if previous and previous['label']==label and (now-datetime.fromisoformat(previous['created'])).total_seconds()<=60:
            old=decode_changes(previous['changes'])
            if len(old)==1 and old[0]['table']=='fieldwork_notes' and old[0]['after']==delta[0]['before']:
                old[0]['after']=delta[0]['after']
                db.execute('UPDATE undo_steps SET changes=?,created=? WHERE id=?',(undo_codec.encode(old),now.isoformat(),previous['id']));merged=True
    if not merged:
        db.execute('INSERT INTO undo_steps(label,created,changes,applied,language_id) VALUES(?,?,?,1,?)',(label,now.isoformat(),undo_codec.encode(delta),lid))
    db.execute('UPDATE undo_scopes SET generation=generation+1 WHERE language_id=?',(lid,))
    trim(db)


def workspace_revision(db):
    """Small change token, including other language scopes and newly added languages.

    Generations remain monotonic when history is trimmed or note edits are merged.
    No corpus/dictionary bodies need to be scanned to check a returning window.
    """
    rows = [tuple(r) for r in db.execute('SELECT language_id,generation FROM undo_scopes ORDER BY language_id')]
    languages = [tuple(r) for r in db.execute('SELECT id,revision FROM languages ORDER BY id')]
    return hashlib.sha256(json.dumps([rows, languages], ensure_ascii=False).encode()).hexdigest()


def state(db, lid=None):
    lid=scope.get() if lid is None else lid
    row=db.execute('SELECT * FROM undo_scopes WHERE language_id=?',(lid,)).fetchone()
    settings = dict(row) if row else {'language_id':lid,'step_limit':20,'generation':0}
    steps = [dict(r) for r in db.execute('SELECT id,label,created,applied FROM undo_steps WHERE language_id=? ORDER BY id DESC',(lid,))]
    return {**settings,'steps':steps,'undo':next((s for s in steps if s['applied']),None),'redo':next((s for s in reversed(steps) if not s['applied']),None)}


def restore_sentence_display(db,changes,redo,observed):
    """Replay display-only edits in place when the full journal source agrees."""
    import sentence_rows
    if record_sources.mode(db) not in ('single','drop') or not any(c.get('inheritance_complete') for c in changes):
        return False
    sources = {}
    expected_key,target_key = ('before','after') if redo else ('after','before')
    for change in changes:
        table = change['table']
        if table=='history':
            continue
        if (table not in sentence_rows.TABLES.values() or change.get('revision_only')
                or not gloss_inheritance.same_annotation_source(change['before'],change['after'])):
            return False
        expected,target = change[expected_key],change[target_key]
        if not isinstance(expected['body'],dict) or not isinstance(target['body'],dict):
            return False
        sources.setdefault(table,{})[expected['id']] = (expected,target)
    if not sources:
        return False

    batches = []
    now = int(datetime.now(timezone.utc).timestamp()*1000000)
    for table,images in sources.items():
        keys = sorted(images)
        kind = record_sources.KINDS[table]
        fields = ','.join(record_sources.META[table])
        for start in range(0,len(keys),200):
            batch = keys[start:start+200]
            marks = ','.join('?' for _ in batch)
            metadata = {r['id']:dict(r) for r in db.execute(f'SELECT rowid,{fields} FROM {table} WHERE id IN ({marks})',batch)}
            bodies = sentence_rows.read(db,kind,batch)
            entries = []
            for key in batch:
                expected,target = images[key]
                row = metadata.get(key)
                if (row is None or any(value!=expected[name] for name,value in row.items() if name!='revision')
                        or bodies.get(key)!=expected['body']):
                    return False
                entries.append((key,bodies[key],target['body'],max(now,target['revision'])))
            batches.append((kind,entries))
    if observed is not None:
        import save_validation
        watch(db,observed,tables=sources if save_validation.trusted(db) else TABLES)
    for kind,entries in batches:
        sentence_rows.write_display_batch(db,kind,entries)
    return True


def isolated_dictionary_edit(db,changes,redo):
    """Check the original dictionary row before scoping a metadata replay."""
    import save_validation
    if len(changes)!=1 or not save_validation.trusted(db):return None
    change=changes[0];table=change['table']
    if table!='lexemes' or not change.get('inheritance_complete'):return None
    before,after=change['before'],change['after']
    if not (save_validation.text_only([(table,before,after)]) or
            save_validation.sense_text_only([(table,before,after)])):return None
    expected=before if redo else after
    fields=','.join(record_sources.META[table])
    row=db.execute(f'SELECT rowid,{fields} FROM {table} WHERE id=?',(expected['id'],)).fetchone()
    if row is None or any(row[key]!=expected[key] for key in row.keys() if key!='revision'):return None
    body=record_sources.read(db,table,expected['id'])
    if not record_sources.same_body(body,expected['body']):return None
    return body


def undo_appended_links(db,changes,observed):
    """Undo native association-only additions in physical row order.

    The row images may be older than the current revision, but every value that
    defines the link must still agree. Mixed and older histories keep the general
    replay, including the inheritance reconciliation it performs.
    """
    import long_tasks
    import save_validation
    from collections import defaultdict

    if not (record_sources.native(db) and save_validation.trusted(db) and
            changes and changes[0].get('inheritance_complete')):return False
    tables=('gloss_bindings','morphology_analyses','independent_links','lexical_links')
    inserted=defaultdict(dict);bindings={};revisions={}
    for change in changes:
        table,before,after=(change[k] for k in ('table','before','after'))
        if (table=='dictionary_examples' and change.get('revision_only') and
                before and after and before['id']==after['id'] and before['language_id']==after['language_id']):
            revisions[after['id']]=1
        elif table in tables and before is None and after:
            inserted[table][after['id']]=after
        elif table=='gloss_bindings' and before and after and all(
                before[k]==after.get(k) for k in before if k not in
                ('revision','source_hash','source_binding_revision','source_meaning_revision')):
            bindings[after['id']]=(before,after)
        else:return False
    if not (inserted['independent_links'] or inserted['lexical_links']):return False
    # Cascading children are part of the same checked relationship. Outside
    # edits invalidate the validation proof via their persistent triggers.
    if sum(map(len,inserted.values()))>=10000:db.execute('PRAGMA cache_size=-196608')

    # Select once per table and compare before deleting anything. Index locality
    # matters on large projects, especially for UUID-keyed association rows.
    actual={}
    typed_links=independent_links.snapshots.enabled(db)
    for table in tables:
        expected=inserted[table]
        if table=='gloss_bindings':expected={**expected,**{bid:after for bid,(_,after) in bindings.items()}}
        if not expected:continue
        rows=[]
        keys=sorted(expected)
        cursor=db.cursor()
        if table=='independent_links':
            cursor.row_factory=None
            columns='rowid,'+independent_links._LINK_COLUMNS
            if typed_links:columns+=','+','.join(independent_links.snapshots.REF_COLUMNS)
        else:
            columns='rowid,*'
        for start in range(0,len(keys),800):
            batch=keys[start:start+800]
            long_tasks.checkpoint()
            rows.extend(cursor.execute(f'SELECT {columns} FROM {table} WHERE id IN ('+','.join('?' for _ in batch)+')',batch))
        if table=='independent_links':
            if not independent_links.verify_appended(db,rows,expected,related=typed_links):
                return False
            actual[table]=sorted(rows,key=lambda row:row[0])
            continue
        if len(rows)!=len(expected) or any(
                any(value!=expected[row['id']].get(key) for key,value in dict(row).items()
                    if key not in ('rowid','revision')) for row in rows):
            return False
        actual[table]=sorted((row for row in rows if table!='gloss_bindings' or row['id'] not in bindings),
                             key=lambda row:row['rowid'])

    # A lexical link can have later analysis or review rows that are outside
    # the original operation. Only remove links whose dependents are covered.
    lexical=inserted['lexical_links'].keys()
    for table in ('component_links','lexical_reviews','morphology_analyses'):
        ids=lexical-inserted[table].keys() if table=='morphology_analyses' else lexical
        if ids and next(lexicon.scoped_rows(db,'SELECT 1 FROM '+table,[('id',ids)],' LIMIT 1'),None):
            return False

    from read_views import association_batch
    minimum=int(datetime.now(timezone.utc).timestamp()*1000000)
    with association_batch(db):
        if bindings:
            if observed is not None:watch(db,observed,tables=('gloss_bindings',))
            # Replay touched binding stamps in place. Their owner, word, mode
            # and inherited meaning were verified above and keep their identity.
            db.executemany('''UPDATE gloss_bindings SET source_hash=?,source_binding_revision=?,
              source_meaning_revision=?,revision=max(revision,?,?)+1 WHERE id=?''',
                ((before['source_hash'],before['source_binding_revision'],before['source_meaning_revision'],
                  before['revision'],minimum,bid) for bid,(before,_) in bindings.items()))
        if revisions:
            if observed is not None:
                if isinstance(db,record_sources.Connection):db.example_revision_journal=observed
                else:watch(db,observed,tables=('dictionary_examples',))
            record_sources.bump_example_revisions(db,revisions,minimum=minimum)
        for table,rows in actual.items():
            if table=='independent_links' and typed_links:
                independent_links.snapshots.delete_references(db,rows)
            for start in long_tasks.steps(range(0,len(rows),800)):
                batch=rows[start:start+800]
                db.execute(f'DELETE FROM {table} WHERE rowid IN ('+','.join('?' for _ in batch)+')',[r[0] for r in batch])
            if observed is not None:
                if table=='independent_links':
                    observed.update(((table,r[0]),(inserted[table][r[1]],None)) for r in rows)
                else:
                    observed.update(((table,r['rowid']),(dict(r),None)) for r in rows)
    return True


def apply(db, path, body, observed=None):
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    current = state(db)
    db.execute('INSERT OR IGNORE INTO undo_scopes(language_id) VALUES(?)',(scope.get(),))
    if body.get('generation') != current['generation']:
        raise ValueError('操作记录已更新，请刷新后重试')
    if path == '/api/undo-limit':
        limit = body.get('limit')
        if limit not in (10,20,30,40): raise ValueError('请选择 10、20、30 或 40 步')
        # Keep a contiguous chain around the current state when reducing the limit.
        keep = [s['id'] for s in current['steps'] if s['applied']][:limit]
        keep += [s['id'] for s in reversed(current['steps']) if not s['applied']][:limit-len(keep)]
        for s in current['steps']:
            if s['id'] not in keep: db.execute('DELETE FROM undo_steps WHERE id=?',(s['id'],))
        db.execute('UPDATE undo_scopes SET step_limit=? WHERE language_id=?',(limit,scope.get()))
    else:
        redo = path == '/api/redo'
        step = current['redo' if redo else 'undo']
        if not step: raise ValueError('没有可以重做的操作' if redo else '没有可以撤销的操作')
        changes = decode_changes(db.execute('SELECT changes FROM undo_steps WHERE id=?',(step['id'],)).fetchone()[0])
        binding_history=any(c.get('inheritance_complete') or c['table'] in gloss_inheritance.TABLES for c in changes)
        import save_validation
        display_only = restore_sentence_display(db,changes,redo,observed)
        dictionary_before=isolated_dictionary_edit(db,changes,redo)
        appended_only=not redo and step['label']==LABELS['/api/lexeme-auto-link'] and undo_appended_links(db,changes,observed)
        from annotations import INDEPENDENT_INLINE_TABLES
        sentence_edit=(step['label']==LABELS['/api/inline-save'] and save_validation.trusted(db) and changes and
                       changes[0].get('inheritance_complete') and all(c['table'] in INDEPENDENT_INLINE_TABLES and
                       (c['table']!='dictionary_examples' or (c['before'] and c['after'] and
                        all(c['before'][key]==c['after'][key] for key in ('id','language_id','rowid')))) for c in changes))
        if observed is not None and not (display_only or appended_only):
            watched=INDEPENDENT_INLINE_TABLES if sentence_edit else TABLES
            watch(db,observed,tables=('lexemes',) if dictionary_before is not None else watched)
        isolated=save_validation.trusted(db) and (display_only or appended_only or dictionary_before is not None)
        replay = () if display_only or appended_only else changes
        # Delete touched records first so unique keys can be restored safely.
        revisions = {};gloss_preimages={}
        track_colors = {}
        session_positions = {}
        stable_rows=set()
        corpus_replays=[]
        def update_source(change,old):
            table=change['table']
            before,after=change['before'],change['after']
            if table not in record_sources.TABLES or old is None or not before or not after:
                return False
            keys=('id','rowid','language_id','form','number') if table=='morphemes' else ('id','rowid')
            return all(before[k]==after[k] for k in keys)
        sentence_preimages={}
        if record_sources.native(db):
            for table in ('entries','dictionary_examples'):
                keys=sorted((c['before'] or c['after'])['id'] for c in replay
                            if c['table']==table and not c.get('revision_only'))
                for start in range(0,len(keys),200):
                    sentence_preimages[table]=sentence_preimages.get(table,{})
                    sentence_preimages[table].update(record_sources.read_many(db,table,keys[start:start+200]))
        # Project-wide records may have been edited from a different language's history.
        for c in replay:
            if c['table'] not in timeline.hierarchy.CATALOGS:continue
            expected=c['before' if redo else 'after']
            current_row=db.execute('SELECT * FROM '+c['table']+' WHERE id=?',((c['before'] or c['after'])['id'],)).fetchone()
            clean=lambda r:{k:v for k,v in dict(r).items() if k not in ('rowid','revision')} if r else None
            if clean(current_row)!=clean(expected):raise ValueError('项目共用信息已在其他操作中更新，不能覆盖；请在管理中检查')
        revision_ids={(c['before'] or c['after'])['id']:1 for c in replay if c.get('revision_only')}
        if revision_ids:
            if record_sources.native(db):
                record_sources.bump_example_revisions(db,revision_ids,minimum=int(datetime.now(timezone.utc).timestamp()*1000000))
            else:
                for rid in revision_ids:
                    updated=db.execute('UPDATE dictionary_examples SET revision=max(revision,?)+1 WHERE id=?',
                        (int(datetime.now(timezone.utc).timestamp()*1000000),rid))
                    if not updated.rowcount:raise ValueError('例句已不存在')
        for c in replay:
            if c['table']=='history' or c.get('revision_only'):continue
            row = (c['before'] if redo else c['after']) or c['before'] or c['after']
            table = c['table']
            key='text_id' if table=='text_info' else 'id'
            fields=','.join(k for k in row if k not in ('rowid','body')) if table in record_sources.TABLES else '*'
            old = db.execute('SELECT rowid,'+fields+' FROM '+table+' WHERE '+key+'=?',(row[key],)).fetchone()
            gloss_preimages[(table,row[key])]=dict(old) if old else None
            if old is not None and table=='independent_links':
                gloss_preimages[(table,row[key])]=independent_links.image(db,old)
            if old is not None and table in record_sources.TABLES:
                if table in sentence_preimages:
                    source=sentence_preimages[table].get(row[key])
                elif dictionary_before is not None:
                    source=dictionary_before
                elif binding_history and table in ('lexemes','morphemes') and update_source(c,old):
                    source=None
                else:
                    source=record_sources.read(db,table,row[key])
                gloss_preimages[(table,row[key])]['body']=source
            if table=='timeline_tracks' and old:track_colors[row[key]]=old['color']
            if table=='timeline_sessions' and old:session_positions[row[key]]=old['position']
            revisions[(table,row['rowid'])] = old['revision'] if old and 'revision' in old.keys() else 0
            if (table in ('corpus_units','unit_segments','gloss_bindings') and old and c['before'] and c['after']
                    and c['before']['id']==c['after']['id']==row['id']
                    and c['before']['rowid']==c['after']['rowid']==old['rowid']):
                stable_rows.add((table,row['id']))
            elif not update_source(c,old):
                db.execute('DELETE FROM '+table+' WHERE '+key+'=?',(row[key],))
        for c in replay:
            if c['table']=='history' or c.get('revision_only'): continue
            row = c['after' if redo else 'before']
            if row is None: continue
            table = c['table']
            import storage_optimization
            row = storage_optimization.compatible_row(table,row)
            if table in independent_links.TABLES:
                independent_links.restore_row(db,table,row)
                continue
            if table=='timeline_tracks' and 'color' not in row:
                row['color']=None if row.get('parent_id') else track_colors.get(row['id']) or timeline_colors.fallback(row['id'])
            if table=='timeline_sessions' and 'position' not in row:
                row['position']=session_positions.get(row['id'],-row['rowid'])
            if 'revision' in row and table != 'history':
                # A wall-clock revision prevents ABA conflicts after delete/restore too.
                row['revision'] = max(row['revision'],revisions[(table,row['rowid'])],int(datetime.now(timezone.utc).timestamp()*1000000))+1
            if table in record_sources.TABLES:
                inplace=update_source(c,gloss_preimages.get((table,row['id'])))
                columns={k:v for k,v in row.items() if k not in ('id','body','rowid')}
                if not inplace and not db.execute('SELECT 1 FROM '+table+' WHERE rowid=?',(row['rowid'],)).fetchone():
                    columns['rowid']=row['rowid']
                source=record_sources.body(row,mutable=False)
                prior=gloss_preimages[(table,row['id'])]
                if (inplace and table=='entries' and c.get('units_complete') and
                        record_sources.mode(db) in ('single','drop') and prior['body'] is not None and
                        all(prior[name]==row[name] for name in ('text_id','position'))):
                    corpus_replays.append((row['id'],prior['body'],source,row['revision']-1))
                    continue
                record_sources.write(db,table,row['id'],source,columns=columns,insert=not inplace,
                                     previous=prior.get('body') if inplace else None)
                continue
            if (table,row.get('id')) in stable_rows:
                columns=[key for key in row if key not in ('id','rowid')]
                db.execute('UPDATE '+table+' SET '+','.join(key+'=?' for key in columns)+' WHERE id=?',
                           [*(row[key] for key in columns),row['id']])
                continue
            # Another language can have reused this SQLite rowid after a deletion.
            if db.execute('SELECT 1 FROM '+table+' WHERE rowid=?',(row['rowid'],)).fetchone():
                row.pop('rowid')
            cols = list(row)
            db.execute('INSERT INTO '+table+' ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',[row[k] for k in cols])
        if corpus_replays:
            import sentence_rows
            for start in range(0,len(corpus_replays),200):
                sentence_rows.write_corpus_batch(db,corpus_replays[start:start+200])
        db.execute('UPDATE undo_steps SET applied=? WHERE id=?',(int(redo),step['id']))
        # Older history predates stable units; reconcile it conservatively too.
        for c in replay:
            if c['table']=='entries':
                if c.get('units_complete'):continue
                before,after=c['before'],c['after']
                if before and after and (record_sources.same_body(before['body'],after['body']) or
                    record_sources.body(before,mutable=False)['words']==record_sources.body(after,mutable=False)['words']):continue
                lexicon.sync_entry(db,(before or after)['id'])
        if not (display_only or appended_only):
            gloss_inheritance.after_legacy_undo(db,changes,gloss_preimages,redo)
        import grammaticality
        applied=observed if observed is not None else {(c['table'],i):(c['before'],c['after']) if redo else (c['after'],c['before']) for i,c in enumerate(changes)}
        if not appended_only:
            grammaticality.validate(db,applied)
            # The general replay can introduce new definitions or references.
            with save_validation.final_check(db):lexicon.validate_changes(db,applied)
        if sentence_edit:
            if observed is None or any(c['table'] in ('code_spans','code_time_links') for c in changes):
                code_switching.after_undo(db,changes)
            else:
                code_switching.refresh_changed_sentences(db,applied)
        elif not isolated and not all(c.get('revision_only') or c['table'] in independent_links.TABLES or
                   (c['table']=='gloss_bindings' and (c['after'] or c['before'])['owner_kind']=='independent')
                   for c in changes):
            timeline.hierarchy.validate(db)
            grammar_survey.validate(db)
            example_groups.validate(db)
            fieldwork_notes.validate(db)
            code_switching.after_undo(db,changes)
            if not object_media.validation_available(db):object_media.validate(db)
        if (not appended_only and any(t in object_media.SOURCES for t, _ in applied)
                and object_media.validation_available(db)):
            object_media.validate_pending(db,full=not save_validation.trusted(db))
    db.execute('UPDATE undo_scopes SET generation=generation+1 WHERE language_id=?',(scope.get(),))
    trim(db)
    import analysis_workspace
    analysis_workspace.invalidate(db)
    return state(db)

LABELS['/api/morpheme-sync-writings']='同步语素书写形式'
LABELS.update({'/api/grammaticality-type-save':'设置合法性类型','/api/grammaticality-type-delete':'删除合法性类型','/api/grammaticality-save':'修改例句合法性'})

LABELS['/api/quick-edit-settings']='词条快捷编辑设置'

LABELS['/api/survey-evidence-groups']='引用独立例句组'

LABELS['/api/class-order']='调整分类顺序'
LABELS['/api/dict-org-class-order']='调整语义分类顺序'
