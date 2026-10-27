"""Bounded, transactional undo journal. Temporary triggers capture only touched rows."""
import object_media
import json
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


def watch(db):
    changes = {}
    for table in TABLES:
        cols = [r['name'] for r in db.execute('PRAGMA table_info('+table+')')]
        def capture(kind, rid, *values, table=table, cols=cols):
            if previewing.get():return 0
            key = (table, rid)
            row = dict(zip(cols, values))
            row['rowid'] = rid
            if key not in changes:
                changes[key] = [None if kind == 'insert' else row, None]
            changes[key][1] = None if kind == 'delete' else row
            return 0
        db.create_function('audit_'+table, -1, capture)
        # UPDATE needs both the initial and final row, including repeated updates.
        for event, kind, ref in [('INSERT','insert','new'),('DELETE','delete','old'),('UPDATE','before','old')]:
            args = ','.join(ref+'.'+c for c in cols)
            tail = ''
            if event == 'UPDATE':
                tail = "SELECT audit_%s('after',new.rowid,%s);" % (table, ','.join('new.'+c for c in cols))
            db.execute("CREATE TEMP TRIGGER audit_%s_%s AFTER %s ON %s BEGIN SELECT audit_%s('%s',%s.rowid,%s); %s END" % (table,event,event,table,table,kind,ref,args,tail))
    return changes


def trim(db):
    lid=scope.get()
    limit = state(db)['step_limit']
    db.execute('DELETE FROM undo_steps WHERE language_id=? AND id NOT IN (SELECT id FROM undo_steps WHERE language_id=? ORDER BY id DESC LIMIT ?)',(lid,lid,limit))
    db.execute('DELETE FROM history WHERE entry_id IN (SELECT e.id FROM entries e JOIN texts t ON t.id=e.text_id WHERE t.language_id=?) AND id NOT IN (SELECT h.id FROM history h JOIN entries e ON e.id=h.entry_id JOIN texts t ON t.id=e.text_id WHERE t.language_id=? ORDER BY h.id DESC LIMIT ?)',(lid,lid,limit))


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


def record(db, changes, label):
    # A newly created language is a stable container; its later edits are undoable.
    new_languages={b['id'] for (t,_),(a,b) in changes.items() if t=='languages' and a is None and b}
    delta = [{'table':t,'before':a,'after':b} for (t,_),(a,b) in changes.items() if a != b and not (t=='languages' and a is None) and not (t=='category_classes' and a is None and b and b['language_id'] in new_languages)]
    if not delta:
        return
    # Current transactions capture the synchronized units and segments too.
    # Older journals lack this proof and keep conservative reconciliation.
    synced=lexicon.synced_entries.get() or {}
    for change in delta:
        if change['table']=='entries':
            before,after=change['before'],change['after'];eid=(after or before)['id']
            if eid in synced and synced[eid]==(after['body'] if after else None):change['units_complete']=True
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


def apply(db, path, body):
    db.execute('BEGIN IMMEDIATE')
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
        # Delete touched records first so unique keys can be restored safely.
        revisions = {};gloss_preimages={}
        track_colors = {}
        session_positions = {}
        # Project-wide records may have been edited from a different language's history.
        for c in changes:
            if c['table'] not in timeline.hierarchy.CATALOGS:continue
            expected=c['before' if redo else 'after']
            current_row=db.execute('SELECT * FROM '+c['table']+' WHERE id=?',((c['before'] or c['after'])['id'],)).fetchone()
            clean=lambda r:{k:v for k,v in dict(r).items() if k not in ('rowid','revision')} if r else None
            if clean(current_row)!=clean(expected):raise ValueError('项目共用信息已在其他操作中更新，不能覆盖；请在管理中检查')
        for c in changes:
            if c['table']=='history': continue
            row = c['before'] or c['after']
            table = c['table']
            key='text_id' if table=='text_info' else 'id'
            old = db.execute('SELECT * FROM '+table+' WHERE '+key+'=?',(row[key],)).fetchone()
            gloss_preimages[(table,row[key])]=dict(old) if old else None
            if table=='timeline_tracks' and old:track_colors[row[key]]=old['color']
            if table=='timeline_sessions' and old:session_positions[row[key]]=old['position']
            revisions[(table,row['rowid'])] = old['revision'] if old and 'revision' in old.keys() else 0
            db.execute('DELETE FROM '+table+' WHERE '+key+'=?',(row[key],))
        for c in changes:
            if c['table']=='history': continue
            row = c['after' if redo else 'before']
            if row is None: continue
            table = c['table']
            import storage_optimization
            row = storage_optimization.compatible_row(table,row)
            if table=='timeline_tracks' and 'color' not in row:
                row['color']=None if row.get('parent_id') else track_colors.get(row['id']) or timeline_colors.fallback(row['id'])
            if table=='timeline_sessions' and 'position' not in row:
                row['position']=session_positions.get(row['id'],-row['rowid'])
            if 'revision' in row and table != 'history':
                # A wall-clock revision prevents ABA conflicts after delete/restore too.
                row['revision'] = max(row['revision'],revisions[(table,row['rowid'])],int(datetime.now(timezone.utc).timestamp()*1000000))+1
            # Another language can have reused this SQLite rowid after a deletion.
            if db.execute('SELECT 1 FROM '+table+' WHERE rowid=?',(row['rowid'],)).fetchone():
                row.pop('rowid')
            cols = list(row)
            db.execute('INSERT INTO '+table+' ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',[row[k] for k in cols])
        db.execute('UPDATE undo_steps SET applied=? WHERE id=?',(int(redo),step['id']))
        # Older history predates stable units; reconcile it conservatively too.
        for c in changes:
            if c['table']=='entries':
                if c.get('units_complete'):continue
                before,after=c['before'],c['after']
                if before and after and (before['body']==after['body'] or json.loads(before['body'])['words']==json.loads(after['body'])['words']):continue
                lexicon.sync_entry(db,(before or after)['id'])
        gloss_inheritance.after_legacy_undo(db,changes,gloss_preimages,redo)
        import grammaticality
        grammaticality.validate(db,{(c['table'],i):(c['before'],c['after']) if redo else (c['after'],c['before']) for i,c in enumerate(changes)})
        # Validate the applied direction: undoing an addition is a deletion and
        # must not enter the additive-definition shortcut.
        lexicon.validate_changes(db,{(c['table'],i):(c['before'],c['after']) if redo else (c['after'],c['before']) for i,c in enumerate(changes)})
        timeline.hierarchy.validate(db)
        grammar_survey.validate(db)
        example_groups.validate(db)
        fieldwork_notes.validate(db)
        code_switching.after_undo(db,changes)
        object_media.validate(db)
    db.execute('UPDATE undo_scopes SET generation=generation+1 WHERE language_id=?',(scope.get(),))
    trim(db)
    import analysis_workspace
    analysis_workspace.invalidate(db)
    return state(db)

LABELS['/api/morpheme-sync-writings']='同步语素书写形式'
LABELS.update({'/api/grammaticality-type-save':'设置合法性类型','/api/grammaticality-type-delete':'删除合法性类型','/api/grammaticality-save':'修改例句合法性'})

LABELS['/api/quick-edit-settings']='词条快捷编辑设置'

LABELS['/api/survey-evidence-groups']='引用独立例句组'
