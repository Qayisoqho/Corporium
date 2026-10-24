"""Delete one language's owned records, with a checked preview and full snapshot.

Project-wide people/codes and media files are preserved. Incoming live references
block the operation; historical snapshots in other languages remain historical.
"""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import sqlite3
import uuid

import analysis_workspace
import backup_policy
import journal
import languages


# All predicates are application constants. Capture rowids before deleting any
# parents, so no cascade depends on already-deleted rows or SQLite rowid reuse.
TEXTS = 'SELECT id FROM texts WHERE language_id=:lid'
ENTRIES = f'SELECT id FROM entries WHERE text_id IN ({TEXTS})'
EXAMPLES = 'SELECT id FROM dictionary_examples WHERE language_id=:lid'
UNITS = f'''SELECT id FROM corpus_units u WHERE entry_id IN ({ENTRIES}) OR
 (NOT EXISTS(SELECT 1 FROM entries e WHERE e.id=u.entry_id) AND
  u.entry_id IN (SELECT linked.entry_id FROM corpus_units linked JOIN lexical_links l ON l.unit_id=linked.id WHERE l.language_id=:lid) AND
  NOT EXISTS(SELECT 1 FROM corpus_units other JOIN lexical_links l ON l.unit_id=other.id WHERE other.entry_id=u.entry_id AND l.language_id!=:lid))'''
TARGETS = 'SELECT id FROM dictionary_targets WHERE language_id=:lid'
LINKS = f'''SELECT id FROM lexical_links l WHERE unit_id IN ({UNITS}) OR
 (language_id=:lid AND NOT EXISTS(SELECT 1 FROM corpus_units u WHERE u.id=l.unit_id))'''
SESSIONS = 'SELECT id FROM timeline_sessions WHERE language_id=:lid'
INTERVALS = f'SELECT id FROM timeline_intervals WHERE session_id IN ({SESSIONS})'
OWNER = f"(owner_kind='corpus' AND record_id IN ({ENTRIES})) OR (owner_kind='independent' AND record_id IN ({EXAMPLES}))"
SCOPED = ('folders','writing_types','annotation_layers','grammar_tags','category_classes',
          'semantic_classes','dictionary_orders','fieldwork_notes','survey_evidence','survey_nodes',
          'object_media','synonym_links','analysis_runs','analysis_saved','analysis_groups',
          'timeline_media','timeline_sessions','lexemes','morphemes','dictionary_examples','texts')
PREDICATES = {
    'code_time_links':f'interval_id IN ({INTERVALS}) OR span_id IN (SELECT id FROM code_spans WHERE {OWNER})',
    'code_spans':OWNER, 'code_sentence_index':OWNER,
    'gloss_bindings':f"(owner_kind='corpus' AND owner_id IN ({ENTRIES})) OR (owner_kind='independent' AND owner_id IN ({EXAMPLES}))",
    'annotation_cells':OWNER,
    'lexical_reviews':f'id IN ({LINKS})', 'component_links':f'id IN ({LINKS})',
    'morphology_analyses':f'id IN ({LINKS})', 'lexical_links':f'id IN ({LINKS})',
    'unit_segments':f'id IN ({UNITS})', 'corpus_units':f'id IN ({UNITS})',
    'morpheme_components':f'lexeme_id IN ({TARGETS})',
    'morph_class_templates':'id IN (SELECT id FROM category_classes WHERE language_id=:lid)',
    'collaborator_assignments':f"(kind='text' AND record_id IN ({TEXTS})) OR (kind='corpus' AND record_id IN ({ENTRIES})) OR (kind='independent' AND record_id IN ({EXAMPLES}))",
    'timeline_text_orders':f'id IN ({TEXTS})',
    'timeline_intervals':f'id IN ({INTERVALS})', 'timeline_tracks':f'session_id IN ({SESSIONS})',
    'analysis_evidence':'group_id IN (SELECT id FROM analysis_groups WHERE language_id=:lid)',
    'history':f'entry_id IN ({ENTRIES})', 'text_info':f'text_id IN ({TEXTS})',
    'entries':f'id IN ({ENTRIES})', 'gloss_meanings':f'target_id IN ({TARGETS})',
    **{table:'language_id=:lid' for table in SCOPED},
    'languages':'id=:lid',
}
LIVE_TABLES = tuple(dict.fromkeys(journal.TABLES + ('timeline_codes','timeline_speakers','code_sentence_index')))
REFERENCE_ARRAYS = {'features','tags','semantic_classes','language_ids','judges','members'}
JSON_COLUMNS = {'body','metadata','features','people','word_ids','snapshot'}


def references(value, ids, lid, key=''):
    """Inspect typed references, never prose that happens to equal a language ID."""
    if isinstance(value, dict):
        # Only SQL row columns are serialized JSON; elements of e.g. features
        # are ordinary stable IDs, not more serialized JSON documents.
        return any(references(json.loads(v) if not key and k in JSON_COLUMNS and isinstance(v,str) else v,ids,lid,k) for k,v in value.items())
    if isinstance(value, list):
        return any(references(v,ids,lid,key) for v in value)
    if not isinstance(value,str):return False
    if key in ('language_id','language_ids','workspace_language_id'):return value==lid
    if key=='id' or key.endswith('_id') or key.endswith('_ids') or key in REFERENCE_ARRAYS or key in ('a','b'):
        return value in ids or (value.startswith('independent:') and value[12:] in ids)
    return False


def plan(db,lid):
    lang=languages.require(db,lid)
    db.execute('CREATE TEMP TABLE IF NOT EXISTS language_delete_rows(table_name TEXT,rid INTEGER,PRIMARY KEY(table_name,rid)) WITHOUT ROWID')
    db.execute('DELETE FROM language_delete_rows')
    digest=hashlib.sha256();ids=set();counts={}
    for table,predicate in PREDICATES.items():
        db.execute(f'INSERT INTO language_delete_rows SELECT :table,rowid FROM {table} WHERE {predicate}',{'lid':lid,'table':table})
        count=0
        for row in db.execute(f'SELECT rowid AS _rowid,* FROM {table} WHERE rowid IN (SELECT rid FROM language_delete_rows WHERE table_name=?) ORDER BY rowid',(table,)):
            digest.update(table.encode());digest.update(json.dumps(tuple(row),ensure_ascii=False).encode())
            if 'id' in row.keys() and isinstance(row['id'],str) and table!='languages':ids.add(row['id'])
            count+=1
        counts[table]=count
    # Keep concurrency proof small for history, but include changes to its scope.
    digest.update(journal.workspace_revision(db).encode())
    return lang,ids,counts,digest.hexdigest()


def blockers(db,ids,lid):
    found=[]
    names={r['id']:r['name'] for r in db.execute('SELECT id,name FROM languages')}
    for table in LIVE_TABLES:
        for row in db.execute(f'SELECT * FROM {table} WHERE rowid NOT IN (SELECT rid FROM language_delete_rows WHERE table_name=?)',(table,)):
            data=dict(row)
            for col in JSON_COLUMNS & data.keys():
                data[col]=json.loads(data[col])
            if references(data,ids,lid):
                owner={'timeline_speakers':'合作者','timeline_codes':'语言标记'}.get(table) or names.get(data.get('language_id'),'其他语言的材料')
                title=data.get('name') or data.get('title') or data.get('headword') or data.get('form')
                label=owner+('「'+str(title)+'」' if title else '')
                if label not in found:found.append(label)
                if len(found)>=5:return found
    return found


def preview(db,body):
    lid=body.get('id');lang,ids,counts,token=plan(db,lid)
    if body.get('_language') not in (None,lid):raise ValueError('语言范围已变化，请重新打开')
    if body.get('revision')!=lang['revision']:raise ValueError('语言信息已更新，请重新打开')
    return dict(id=lid,name=lang['name'],revision=lang['revision'],token=token,counts=counts,blockers=blockers(db,ids,lid))


def remove(db,path,body):
    if body.get('confirmed') is not True:raise ValueError('请双击确认删除语言')
    # Caller owns BEGIN IMMEDIATE; preview, backup and deletion share its write lock.
    current=preview(db,body)
    if not body.get('token') or body['token']!=current['token']:raise ValueError('语言资料已变化，请关闭确认窗口后重新双击删除')
    if current['blockers']:raise ValueError('仍有其他材料引用本语言，请先调整引用：'+'、'.join(current['blockers']))
    ids={r[0] for table in PREDICATES if table not in ('languages','history','text_info') for r in db.execute(f'SELECT id FROM {table} WHERE rowid IN (SELECT rid FROM language_delete_rows WHERE table_name=?)',(table,))}
    # A separate reader sees the exact committed pre-delete state under our
    # reserved writer lock. Backing up this writer connection would self-block.
    path=Path(path).resolve();name='before-language-delete-'+uuid.uuid4().hex+'.sqlite3'
    def copy(target):
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
    backup_policy.write(path.parent/'backups',name,copy,defer_prune=True)
    for table in PREDICATES:
        db.execute(f'DELETE FROM {table} WHERE rowid IN (SELECT rid FROM language_delete_rows WHERE table_name=?)',(table,))
    # Other scopes can contain historical references to this language. Remove
    # only dependent steps, so undo cannot resurrect dangling references later.
    touched=set()
    for step in list(db.execute('SELECT id,language_id,changes FROM undo_steps')):
        if step['language_id']==current['id'] or any(references(row,ids,current['id']) for c in journal.decode_changes(step['changes']) for row in (c.get('before'),c.get('after')) if row):
            db.execute('DELETE FROM undo_steps WHERE id=?',(step['id'],));touched.add(step['language_id'])
    for lid in touched:db.execute('UPDATE undo_scopes SET generation=generation+1 WHERE language_id=?',(lid,))
    db.execute('DELETE FROM undo_scopes WHERE language_id=?',(current['id'],))
    analysis_workspace.invalidate(db)
    if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('关联检查未通过，删除已取消')
    remaining=[r[0] for r in db.execute('SELECT id FROM languages ORDER BY name,id')]
    return dict(ok=True,id=current['id'],name=current['name'],backup=name,next_language=remaining[0] if remaining else 'all')
