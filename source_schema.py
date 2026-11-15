"""Switch established projects to the relational source schema atomically."""
import json

import dictionary_rows
import record_sources
import sentence_rows


MODES = ('legacy', 'dual', 'single', 'drop')


def _prepare(db, table):
    kind = record_sources.KINDS[table]
    sentence = table in sentence_rows.TABLES.values()
    last = None
    while True:
        where, args = ('', ()) if last is None else ('WHERE rowid>?', (last,))
        records = db.execute(f'SELECT rowid,id,body FROM {table} {where} ORDER BY rowid LIMIT 200', args).fetchall()
        if not records:
            return
        last = records[-1]['rowid']
        ids = [row['id'] for row in records]
        if sentence:
            prepared = sentence_rows.read(db, kind, ids)
        else:
            prepared = dictionary_rows.raw_bodies(db, kind, ids)
        for row in records:
            owner = row['id']
            old = json.loads(row['body']) if row['body'] is not None else None
            if table == 'dictionary_examples' and isinstance(old, dict):
                if 'targets' in old:
                    raise ValueError('独立例句关联尚未完成迁移')
            if not isinstance(old, dict) or owner not in prepared or not same_value(old, prepared[owner]):
                raise ValueError(f'正文迁移校验失败（{table} {owner}）。项目保留原有正文。')


def same_value(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_value(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_value(a, b) for a, b in zip(left, right))
    return left == right


def validate_relations(db):
    for table,kind in record_sources.KINDS.items():
        if table in sentence_rows.TABLES.values():
            sql=f'''SELECT 1 FROM {table} e WHERE NOT EXISTS(SELECT 1 FROM sentence_text_rows s
                WHERE s.kind=? AND s.owner_id=e.id) LIMIT 1'''
        else:
            sql=f'''SELECT 1 FROM {table} e WHERE NOT EXISTS(SELECT 1 FROM dictionary_value_rows s
                WHERE s.target_kind=? AND s.target_id=e.id AND s.node=0 AND s.parent IS NULL AND s.value_type='object') LIMIT 1'''
        if db.execute(sql,(kind,)).fetchone():
            raise ValueError(f'正文关系行不完整（{table}）')
    if db.execute('SELECT 1 FROM record_source_writes LIMIT 1').fetchone():
        raise ValueError('项目正文含未完成的写入')
    if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
        raise ValueError('项目数据库的关联完整性检查未通过')


def _install_relational_objects(db):
    import dictionary_read
    import dictionary_own_index
    import dictionary_relations
    import dictionary_targets
    import gloss_search_index
    import grammar_usage
    import home_candidates
    import independent_links
    import material_search_index
    import object_media
    import read_views
    import sentence_scope_index
    import sentence_search_index
    import statistics_facts
    import word_analysis_memory

    db.execute('DROP VIEW IF EXISTS dictionary_targets')
    record_sources.drop_views(db)
    for table in record_sources.KINDS:
        for suffix in ('insert', 'update'):
            db.execute(f'DROP TRIGGER IF EXISTS sentence_rows_{table}_{suffix}')
            db.execute(f'DROP TRIGGER IF EXISTS dictionary_rows_{table}_{suffix}')
    independent_links.drop_triggers(db)
    db.execute('DROP INDEX IF EXISTS lexemes_list_language')
    db.execute('DROP INDEX IF EXISTS lexemes_list_all')
    dictionary_targets.initialize(db)
    sentence_rows.initialize(db)
    db.execute('''INSERT INTO corpus_sentence_keys
        SELECT e.id,e.text_id,e.position,NULLIF(s.language_id,'') FROM entries e
        JOIN sentence_text_rows s ON s.kind='corpus' AND s.owner_id=e.id WHERE 1
        ON CONFLICT(id) DO UPDATE SET text_id=excluded.text_id,position=excluded.position,
        language_id=excluded.language_id
        WHERE text_id IS NOT excluded.text_id OR position IS NOT excluded.position
        OR language_id IS NOT excluded.language_id''')
    dictionary_rows.initialize(db)
    object_media.install_validation(db)
    independent_links.initialize(db)
    dictionary_relations.initialize(db)
    dictionary_read.initialize(db)
    sentence_search_index.install_source_triggers(db)
    gloss_search_index.initialize(db)
    grammar_usage.initialize_direct(db)
    grammar_usage.install_owner_triggers(db)
    word_analysis_memory.install_owner_triggers(db)
    home_candidates.initialize(db)
    material_search_index.initialize(db)
    dictionary_own_index.initialize(db)
    read_views.initialize(db)
    sentence_scope_index.initialize(db)
    statistics_facts.initialize(db)


def migrate(db, target):
    import save_validation

    current = record_sources.mode(db)
    if current == target:
        return
    if MODES.index(current) > MODES.index(target):
        raise ValueError('项目正文已采用较新的存储格式')
    db.execute('BEGIN IMMEDIATE')
    try:
        trusted = save_validation.snapshot(db) is not None
        if current == 'legacy':
            for table in record_sources.KINDS:
                _prepare(db, table)
            db.execute('ALTER TABLE lexemes ADD COLUMN homonym_number')
            db.execute("UPDATE lexemes SET homonym_number=json_extract(body,'$.homonym_number') "
                       "WHERE json_type(body,'$.homonym_number') NOT IN ('null','array','object')")
            db.execute('CREATE TABLE record_source_schema(id INTEGER PRIMARY KEY CHECK(id=1),mode TEXT NOT NULL)')
            db.execute('INSERT INTO record_source_schema VALUES(1,?)', (target,))
            db.source_mode = target
            _install_relational_objects(db)
        else:
            db.execute('UPDATE record_source_schema SET mode=? WHERE id=1', (target,))
            db.source_mode = target
        if target == 'drop':
            save_validation.drop_triggers(db)
            for table in record_sources.KINDS:
                db.execute(f'ALTER TABLE {table} DROP COLUMN body')
            validate_relations(db)
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('正文迁移后的数据库完整性检查未通过')
        save_validation.initialize(db)
        if trusted:
            db.execute('UPDATE save_validation_state SET checked_epoch=epoch WHERE id=1')
        db.commit()
    except BaseException:
        db.rollback()
        db.source_mode = current
        raise
