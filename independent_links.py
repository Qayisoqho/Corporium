"""Authoritative dictionary relationships for independent examples."""
import json
from collections import defaultdict
from itertools import zip_longest
import independent_annotations as snapshots


TABLES = ('independent_links', 'independent_word_overrides')
KEYS = ('lexeme_id', 'usage_id', 'sense_id', 'form_id')

_LINK_COLUMNS = 'id,example_id,position,lexeme_id,usage_id,sense_id,form_id,word_position,unit_key,payload'
_CACHE_TRIGGER_PREFIXES = (
    'evidence_owner_watch_', 'gloss_search_', 'grammar_usage_', 'home_candidate_',
    'material_search_', 'read_view_', 'save_validation_watch_', 'sentence_scope_',
    'sentence_search_', 'statistics_fact_', 'word_memory_',
)
_LEGACY_FIELDS = """
    e.id||':'||t.key,e.id,t.key,json_extract(t.value,'$.lexeme_id'),
    NULLIF(NULLIF(json_extract(t.value,'$.usage_id'),''),0),NULLIF(NULLIF(json_extract(t.value,'$.sense_id'),''),0),
    NULLIF(NULLIF(json_extract(t.value,'$.form_id'),''),0),
    json_extract(t.value,'$.segmentation_ref.word'),json_extract(t.value,'$.segmentation_ref.key'),
    json_remove(t.value,'$.lexeme_id','$.usage_id','$.sense_id','$.form_id','$.segmentation_review')
"""
_REFERENCE_KEYS = """
    SELECT d.id,'usage',u.value->>'$.id','',''
    FROM dictionary_targets d,json_each(d.body,'$.usages') u WHERE {scope}
    UNION ALL
    SELECT d.id,'sense',s.value->>'$.id',u.value->>'$.id',''
    FROM dictionary_targets d,json_each(d.body,'$.usages') u,json_each(u.value,'$.senses') s WHERE {scope}
    UNION ALL
    SELECT d.id,'form',f.value->>'$.id','',''
    FROM dictionary_targets d,json_each(d.body,'$.variants') f WHERE {scope}
    UNION ALL
    SELECT d.id,'paradigm',m.value->>'$.id',p.value->>'$.usage_id',COALESCE(f.value->>'$.form_id','')
    FROM dictionary_targets d,json_each(d.body,'$.paradigms') p,json_each(p.value,'$.rows') r,
         json_each(r.value,'$.realizations') f,json_each(f.value,'$.meanings') m WHERE {scope}
"""


def needed(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name='independent_links'").fetchone() is None


def has_word_source(db):
    return db.execute("SELECT 1 FROM pragma_table_info('independent_words') WHERE name='source'").fetchone() is not None


def _create_words(db,table):
    db.execute(f'''CREATE TABLE {table}(
        example_id TEXT NOT NULL,position INTEGER NOT NULL,word_id TEXT,
        PRIMARY KEY(example_id,position)
    ) WITHOUT ROWID''')


def initialize(db):
    if not needed(db):
        _install_triggers(db)
        return
    db.execute('SAVEPOINT independent_link_migration')
    try:
        db.execute('''CREATE TABLE independent_links(
            id TEXT PRIMARY KEY, example_id TEXT NOT NULL, position INTEGER NOT NULL,
            lexeme_id TEXT NOT NULL, usage_id TEXT, sense_id TEXT, form_id TEXT,
            word_position INTEGER, unit_key TEXT, payload TEXT NOT NULL,
            FOREIGN KEY(example_id) REFERENCES dictionary_examples(id) DEFERRABLE INITIALLY DEFERRED
        )''')
        db.execute('CREATE UNIQUE INDEX independent_link_order ON independent_links(example_id,position)')
        db.execute('CREATE INDEX independent_link_target ON independent_links(lexeme_id,example_id,form_id)')
        db.execute('CREATE INDEX independent_link_form ON independent_links(lexeme_id,form_id,example_id)')
        db.execute('CREATE INDEX independent_link_word ON independent_links(example_id,word_position)')
        _create_words(db,'independent_words')
        db.execute('''CREATE TABLE independent_word_overrides(
            id TEXT PRIMARY KEY,example_id TEXT NOT NULL,position INTEGER NOT NULL,
            source TEXT NOT NULL,word TEXT NOT NULL
        )''')
        db.execute('CREATE UNIQUE INDEX independent_word_override_order ON independent_word_overrides(example_id,position)')
        db.execute('''CREATE TABLE independent_dictionary_keys(
            target_id TEXT NOT NULL,kind TEXT NOT NULL,key TEXT NOT NULL,usage_id TEXT NOT NULL,form_id TEXT NOT NULL,
            PRIMARY KEY(target_id,kind,key,usage_id,form_id)
        ) WITHOUT ROWID''')
        db.execute('INSERT INTO independent_links('+_LINK_COLUMNS+') SELECT '+_LEGACY_FIELDS+'''
            FROM dictionary_examples e,json_each(e.body,'$.targets') t WHERE json_type(e.body,'$.targets')='array' ''')
        _strip_legacy_targets(db)
        db.execute('''INSERT INTO independent_words(example_id,position,word_id) SELECT e.id,w.key,w.value->>'$.annotation_id'
            FROM dictionary_examples e,json_each(e.body,'$.words') w''')
        db.execute('INSERT OR IGNORE INTO independent_dictionary_keys '+_REFERENCE_KEYS.format(scope='1'))
        _migrate_history(db)
        _install_triggers(db)
    except BaseException:
        db.execute('ROLLBACK TO independent_link_migration')
        raise
    finally:
        db.execute('RELEASE independent_link_migration')


def _strip_legacy_targets(db):
    # The cached source facts and evidence are unchanged by this layout migration.
    # Restore the existing cache triggers inside the same migration savepoint.
    triggers = [(name, sql) for name, sql in db.execute("""SELECT name,sql FROM sqlite_master
        WHERE type='trigger' AND tbl_name='dictionary_examples'""") if name.startswith(_CACHE_TRIGGER_PREFIXES)]
    for name, _ in triggers:
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
    db.execute("UPDATE dictionary_examples SET body=json_remove(body,'$.targets') WHERE json_type(body,'$.targets') IS NOT NULL")
    for _, sql in triggers:
        db.execute(sql)


def _migrate_history(db):
    """Split old association-only undo steps when their source is identical."""
    import journal
    import undo_codec

    labels = [journal.LABELS['/api/'+action] for action in
              ('segmentation-link', 'dictionary-examples-unlink', 'lexeme-unlink')]
    for row in db.execute('SELECT id,changes FROM undo_steps WHERE label IN (?,?,?)', labels):
        try:
            changes = undo_codec.decode(row[1])
        except ValueError:
            continue  # Leave a previously unreadable historical step intact.
        links = []
        for change in changes:
            if change['table'] != 'dictionary_examples':
                continue
            before, after = change['before'], change['after']
            if not before or not after or not before.get('body') or not after.get('body'):
                continue
            if any(before.get(key) != after.get(key) for key in ('id', 'language_id', 'rowid')):
                continue
            try:
                left, right = json.loads(before['body']), json.loads(after['body'])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(left, dict) or not isinstance(right, dict):
                continue
            old, new = left.pop('targets', []), right.pop('targets', [])
            if left != right or old == new or not isinstance(old, list) or not isinstance(new, list):
                continue
            if any(not isinstance(value, dict) or not value.get('lexeme_id') for value in (*old, *new)):
                continue
            rid = before['id']
            def image(position, target):
                if target is None:
                    return None
                return dict(zip(_LINK_COLUMNS.split(','), (f'{rid}:{position}', rid, position, *_values(target))), rowid=None)
            for position, (a, b) in enumerate(zip_longest(old, new)):
                a, b = image(position, a), image(position, b)
                if a != b:
                    links.append(dict(table='independent_links', before=a, after=b))
            change['revision_only'] = True
            change['legacy_links'] = True
            before.pop('body')
            after.pop('body')
        if links:
            db.execute('UPDATE undo_steps SET changes=? WHERE id=?', (undo_codec.encode([*changes, *links]), row[0]))


def _install_triggers(db):
    import record_sources
    record_sources.initialize(db)
    if record_sources.native(db):
        for table, other in (('lexemes','morphemes'), ('morphemes','lexemes')):
            record_sources.trigger(db, f'independent_keys_{table}_delete', f'''AFTER DELETE ON {table} BEGIN
                DELETE FROM independent_dictionary_keys WHERE target_id=OLD.id
                AND NOT EXISTS(SELECT 1 FROM {other} WHERE id=OLD.id);
                END''')
        _install_example_delete(db)
        if snapshots.enabled(db):
            snapshots.install_cleanup(db)
        return
    for table in ('lexemes', 'morphemes'):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            trigger = f'independent_keys_{table}_{event.lower()}'
            when = ''
            if event!='DELETE':
                when = ' WHEN NOT '+record_sources.is_native(table,'NEW.id')
                if event=='UPDATE':
                    when += ' AND (OLD.body IS NOT NEW.body OR OLD.id IS NOT NEW.id)'
            remove = 'DELETE FROM independent_dictionary_keys WHERE target_id=OLD.id;' if event != 'INSERT' else ''
            # Converting a word keeps its dictionary ID while moving the row to
            # the morpheme table. Deleting the old row must retain the new keys.
            scope = {'INSERT':'d.id=NEW.id','UPDATE':'d.id IN (OLD.id,NEW.id)','DELETE':'d.id=OLD.id'}[event]
            project = 'INSERT OR IGNORE INTO independent_dictionary_keys '+_REFERENCE_KEYS.format(scope=scope)+';'
            sql = f'CREATE TRIGGER {trigger} AFTER {event} ON {table}{when} BEGIN {remove}{project} END'
            prior = db.execute('SELECT sql FROM sqlite_master WHERE type=\'trigger\' AND name=?',(trigger,)).fetchone()
            if prior and prior[0] == sql:
                continue
            if prior:
                db.execute('DROP TRIGGER '+trigger)
            db.execute(sql)
    for event in ('INSERT', 'UPDATE OF body'):
        suffix = event.split()[0].lower()
        # Only source edits rebuild word cells. A link revision never invokes this.
        when = ' WHEN NOT '+record_sources.is_native('dictionary_examples','NEW.id')
        if suffix=='update':
            when += " AND (OLD.body->'$.words') IS NOT (NEW.body->'$.words')"
        name = f'independent_words_{suffix}'
        sql = f'''CREATE TRIGGER {name} AFTER {event} ON dictionary_examples{when}
            BEGIN
              DELETE FROM independent_words WHERE example_id=NEW.id;
              INSERT INTO independent_words(example_id,position,word_id) SELECT NEW.id,w.key,w.value->>'$.annotation_id'
                FROM json_each(NEW.body,'$.words') w;
              DELETE FROM independent_word_overrides WHERE example_id=NEW.id AND NOT EXISTS(
                SELECT 1 FROM json_each(NEW.body,'$.words') w
                WHERE w.key=independent_word_overrides.position AND w.value=json(independent_word_overrides.source));
            END'''
        prior = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()
        if not prior or prior[0]!=sql:
            db.execute(f'DROP TRIGGER IF EXISTS {name}')
            db.execute(sql)
        # Historical undo row images and older importers can still contain targets.
        # Extract them on input so the source column has just one representation.
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS independent_legacy_links_{suffix} AFTER {event} ON dictionary_examples
            WHEN json_type(NEW.body,'$.targets')='array'
            BEGIN
              DELETE FROM independent_links WHERE example_id=NEW.id AND position>=json_array_length(NEW.body,'$.targets');
              INSERT INTO independent_links({_LINK_COLUMNS}) SELECT {_LEGACY_FIELDS}
                FROM (SELECT NEW.id id,NEW.body body) e,json_each(e.body,'$.targets') t WHERE 1
              ON CONFLICT(id) DO UPDATE SET lexeme_id=excluded.lexeme_id,usage_id=excluded.usage_id,
                sense_id=excluded.sense_id,form_id=excluded.form_id,word_position=excluded.word_position,
                unit_key=excluded.unit_key,payload=excluded.payload;
              UPDATE dictionary_examples SET body=json_remove(NEW.body,'$.targets') WHERE id=NEW.id;
            END''')
    _install_example_delete(db)


def _install_example_delete(db):
    db.execute('''CREATE TRIGGER IF NOT EXISTS independent_delete AFTER DELETE ON dictionary_examples
        BEGIN
          DELETE FROM independent_links WHERE example_id=OLD.id;
          DELETE FROM independent_words WHERE example_id=OLD.id;
          DELETE FROM independent_word_overrides WHERE example_id=OLD.id;
        END''')


def drop_triggers(db):
    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'independent_*'"):
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')


def _validate_word_source(db):
    """Verify the old copy against the authoritative word at each stable slot."""
    import record_sources
    import sentence_rows
    from source_schema import same_value

    def mismatch(example,position):
        return ValueError(f'独立例句词格迁移校验失败（{example}，第 {position+1} 格）。项目保留旧副本。')

    if not record_sources.native(db):
        # Lazy relational rows can be absent in old projects. Their sentence
        # documents are still authoritative until the separate source cutover.
        missing=db.execute('''SELECT e.id,w.key FROM dictionary_examples e,json_each(e.body,'$.words') w
            LEFT JOIN independent_words i ON i.example_id=e.id AND i.position=w.key
            WHERE i.example_id IS NULL LIMIT 1''').fetchone()
        if missing:raise mismatch(*missing)
        for row in db.execute('''SELECT i.example_id,i.position,i.word_id,i.source,
                e.body->('$.words['||i.position||']') original
                FROM independent_words i LEFT JOIN dictionary_examples e ON e.id=i.example_id'''):
            try:
                original=json.loads(row['original'])
                if (original.get('annotation_id')==row['word_id'] and
                        (row['original']==row['source'] or same_value(original,json.loads(row['source'])))):
                    continue
            except (AttributeError,ValueError,TypeError):
                pass
            raise mismatch(row['example_id'],row['position'])
        return

    missing=db.execute('''SELECT s.owner_id,s.position FROM sentence_word_rows s LEFT JOIN independent_words i
        ON i.example_id=s.owner_id AND i.position=s.position
        WHERE s.kind='independent' AND i.example_id IS NULL LIMIT 1''').fetchone()
    if missing:raise mismatch(*missing)
    # Fast SQL for equivalent encodings, typed comparison for different key order.
    rows=db.execute('''SELECT i.example_id,i.position,i.word_id,i.source,s.form,s.gloss,s.extra
        FROM independent_words i LEFT JOIN sentence_word_rows s
        ON s.kind='independent' AND s.owner_id=i.example_id AND s.position=i.position
        WHERE CASE WHEN s.owner_id IS NULL OR NOT json_valid(i.source) OR NOT json_valid(s.extra) THEN 1
            ELSE json_type(i.source)<>'object' OR json_type(s.extra)<>'object'
              OR i.word_id IS NOT (s.extra->>'$.annotation_id')
              OR json_type(i.source,'$.form') IS NOT CASE WHEN s.form IS NULL THEN 'null' ELSE typeof(s.form) END
              OR json_type(i.source,'$.gloss') IS NOT CASE WHEN s.gloss IS NULL THEN 'null' ELSE typeof(s.gloss) END
              OR i.source->>'$.form' IS NOT s.form OR i.source->>'$.gloss' IS NOT s.gloss
              OR json_remove(i.source,'$.form','$.gloss') IS NOT json(s.extra) END''')
    for row in rows:
        if row['extra'] is not None:
            try:
                source_word=sentence_rows.decode_word(row)
                old_word=json.loads(row['source'])
                if row['word_id']==source_word.get('annotation_id') and same_value(source_word,old_word):
                    continue
            except (AttributeError,ValueError,TypeError):
                pass
        raise mismatch(row['example_id'],row['position'])


def migrate_word_source(db):
    """Retire the verified word copy atomically, including schema dependencies."""
    import save_validation

    if not has_word_source(db):return False
    if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
    db.execute('SAVEPOINT independent_word_migration')
    try:
        prior=save_validation.snapshot(db)
        _validate_word_source(db)
        # Repack only this table. A column-only ALTER can leave most of the
        # old payload pages allocated to a sparsely filled identity table.
        _create_words(db,'independent_words_new')
        db.execute('''INSERT INTO independent_words_new
            SELECT example_id,position,word_id FROM independent_words ORDER BY example_id,position''')
        drop_triggers(db)
        db.execute('DROP TABLE independent_words')
        db.execute('ALTER TABLE independent_words_new RENAME TO independent_words')
        if db.execute("PRAGMA quick_check('independent_words')").fetchone()[0]!='ok':
            raise ValueError('独立例句词格迁移后的完整性检查未通过')
        if db.execute("PRAGMA foreign_key_check('independent_links')").fetchone():
            raise ValueError('独立例句关联的完整性检查未通过')
        _install_triggers(db)
        save_validation.initialize(db,prior)
    except BaseException:
        db.execute('ROLLBACK TO independent_word_migration')
        raise
    finally:
        db.execute('RELEASE independent_word_migration')
    return True


def targets(db, rid):
    return [target(row) for row in images(db, rows(db, rid))]


def rows(db, rid):
    return db.execute('SELECT * FROM independent_links WHERE example_id=? ORDER BY position', (rid,)).fetchall()


def target(row):
    result = json.loads(row['payload']) if row['payload'] != '{}' else {}
    if 'segmentation_ref' in row.keys():
        result['segmentation_ref'] = row['segmentation_ref']
    result.update((key, row[key]) for key in KEYS)
    return result


def images(db, rows):
    """Capture the relationship and its ordered fragments as one logical row."""
    if not rows or 'ref_snapshot' not in rows[0].keys():
        return rows
    refs = snapshots.read_references(db, rows)
    result = []
    for row in rows:
        image = {key: row[key] for key in row.keys() if key not in snapshots.REF_COLUMNS}
        if row['ref_snapshot'] is not None or row['ref_form'] is not None:
            image['segmentation_ref'] = snapshots.reference(row, refs)
        result.append(image)
    return result


def verify_appended(db, rows, expected, *, related):
    """Compare typed link keys in bulk before replaying an association step."""
    if len(rows)!=len(expected):
        return False
    cache={}
    snapshots_to_read=[]
    expected_values={}
    for row in rows:
        _,key,example,position,lexeme,usage,sense,form,word,unit,payload,*fields=row
        prior=expected[key]
        if (example,position,lexeme,usage,sense,form,word,unit)!=(prior['example_id'],prior['position'],
                prior['lexeme_id'],prior.get('usage_id'),prior.get('sense_id'),prior.get('form_id'),
                prior.get('word_position'),prior.get('unit_key')):
            return False
        if related:
            if 'segmentation_ref' in prior:
                prior_payload=prior['payload']
                values=prior
            else:
                values=target(prior)
                prior_payload=_payload(values,relational=True)
            ref=values.get('segmentation_ref')
            if isinstance(ref,dict) and (ref.get('word'),ref.get('key'))!=(word,unit):
                return False
            if isinstance(ref,dict) and ref.keys()==snapshots.WHOLE_REF_FIELDS and type(ref['word']) is int and ref['fragments']==[] and all(
                    isinstance(ref[field],str) for field in snapshots.REF_FIELDS):
                reference=[ref['form'],ref['gloss'],ref['unit_form'],ref['unit_gloss'],None,None]
            else:
                reference=list(snapshots.reference_fields(values,cache)[0])
            if fields!=reference:
                return False
            if stamp:=fields[-1]:
                snapshots_to_read.append({'id':key,'ref_snapshot':stamp})
                expected_values[key]=ref['fragments'] if stamp.startswith('f') else ref
        else:
            prior_payload=prior['payload'] if 'segmentation_ref' not in prior else portable_image(TABLES[0],prior)['payload']
        if payload!=prior_payload:
            return False
    if snapshots_to_read and snapshots.read_references(db,snapshots_to_read)!=expected_values:
        raise ValueError('关联的分段快照已变化，请刷新后重试')
    return True


def image(db, row):
    if 'ref_snapshot' not in row.keys():
        return row
    ref = snapshots.read_reference(db, row)
    result = {key: row[key] for key in row.keys() if key not in snapshots.REF_COLUMNS}
    if row['ref_snapshot'] is not None or row['ref_form'] is not None:
        result['segmentation_ref'] = ref
    return result


def override_images(db, rows):
    if not rows or 'snapshot' not in rows[0].keys():
        return rows
    words = snapshots.read_overrides(db, rows)
    return [dict({key: row[key] for key in row.keys() if key in ('id', 'example_id', 'position', 'rowid')},
                 source=words[row['id']][0], word=words[row['id']][1]) for row in rows]


def word_value(value):
    return json.loads(value) if isinstance(value, str) else value


def overrides(db, ids, positions=None):
    if not ids or positions == []:
        return []
    marks = ','.join('?' for _ in ids)
    scope, params = f'example_id IN ({marks})', list(ids)
    if positions is not None:
        scope += ' AND position IN ('+','.join('?' for _ in positions)+')'
        params.extend(positions)
    return override_images(db, db.execute('SELECT * FROM independent_word_overrides WHERE '+scope, params).fetchall())


def portable_rows(db, table, rows):
    for row in (images(db, rows) if table == TABLES[0] else override_images(db, rows)):
        yield portable_image(table, row)


def portable_image(table, row):
    row = dict(row)
    if table == TABLES[0] and 'segmentation_ref' in row:
        payload = json.loads(row['payload'])
        payload['segmentation_ref'] = row.pop('segmentation_ref')
        row['payload'] = snapshots.encoded(payload)
    if table == TABLES[1]:
        for key in ('source', 'word'):
            if not isinstance(row[key], str):
                # Existing binding hashes include the order of nested keys.
                row[key] = json.dumps(row[key],ensure_ascii=False,separators=(',',':'))
    return row


def restore_row(db, table, row):
    """Replay both the old portable images and new typed snapshots."""
    names = (*_LINK_COLUMNS.split(','),'segmentation_ref') if table==TABLES[0] else ('id','example_id','position','source','word')
    row = {key:row[key] for key in ('rowid',*names) if key in row}
    required=set(_LINK_COLUMNS.split(',')) if table==TABLES[0] else {'id','example_id','position','source','word'}
    if not required<=row.keys():
        raise ValueError('独立例句快照的备份记录不完整')
    if not snapshots.enabled(db):
        row = portable_image(table, row)
    elif table == TABLES[0]:
        value = target(row)
        fields, ref = snapshots.reference_fields(value)
        snapshots.store_references(db, [(row['id'], fields[-1], ref)])
        row['payload'] = _payload(value, relational=True)
        row.update(zip(snapshots.REF_COLUMNS, fields))
        row.pop('segmentation_ref', None)
    else:
        fields = snapshots.override_fields(db, row['id'], row.pop('source'), word_value(row.pop('word')))
        row.update(zip(('snapshot', *snapshots.WORD_FIELDS, 'word_fields'), fields))
    if 'rowid' in row and db.execute('SELECT 1 FROM '+table+' WHERE rowid=?', (row['rowid'],)).fetchone():
        row.pop('rowid')
    db.execute('INSERT INTO '+table+' ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')', tuple(row.values()))


def source_body(db, rid, body, *, include_targets=True):
    if 'targets' in body:
        return body
    if include_targets:
        body['targets'] = targets(db, rid)
    for row in overrides(db, [rid]):
        if row['position'] < len(body.get('words', ())):
            body['words'][row['position']] = word_value(row['word'])
    return body


def source_bodies(db,bodies):
    """Attach relations and overrides to a bounded batch from one snapshot."""
    active={rid:body for rid,body in bodies.items() if 'targets' not in body}
    if not active:
        return
    marks=','.join('?' for _ in active)
    for body in active.values():
        body['targets']=[]
    for row in images(db, db.execute('SELECT * FROM independent_links WHERE example_id IN ('+marks+
                          ') ORDER BY example_id,position',list(active)).fetchall()):
        active[row['example_id']]['targets'].append(target(row))
    for row in overrides(db, list(active)):
        words=active[row['example_id']]['words']
        if row['position']<len(words):
            words[row['position']]=word_value(row['word'])


def before_body(db, rid, body, changes):
    if 'targets' not in body:
        current = {row['id']: row for row in images(db, rows(db, rid))}
        for (table, _), (before, after) in changes.items():
            if table != 'independent_links' or (after or before)['example_id'] != rid:
                continue
            if after:
                current.pop(after['id'], None)
            if before:
                current[before['id']] = before
        body['targets'] = [target(row) for row in sorted(current.values(), key=lambda row: row['position'])]
    previous = {row['position']:row['word'] for row in overrides(db, [rid])}
    for (table, _), (before, after) in changes.items():
        if table != 'independent_word_overrides' or (after or before)['example_id'] != rid:
            continue
        if after:
            previous.pop(after['position'], None)
        if before:
            previous[before['position']] = before['word']
    for position, word in previous.items():
        if position < len(body.get('words', ())):
            body['words'][position] = word_value(word)
    return body


def _payload(value, *, relational=False):
    excluded = (*KEYS, 'segmentation_review', 'segmentation_ref') if relational else (*KEYS, 'segmentation_review')
    payload = {k: v for k, v in value.items() if k not in excluded}
    return snapshots.encoded(payload) if payload else '{}'


def _values(value, *, relational=False):
    ref = value.get('segmentation_ref') or {}
    if not isinstance(ref, dict):ref={}
    return (value['lexeme_id'], *(value.get(k) or None for k in KEYS[1:]),
            ref.get('word'), ref.get('key'), _payload(value, relational=relational))


def _statements(columns):
    values = '('+','.join('?' for _ in columns)+')'
    insert = 'INSERT INTO independent_links('+','.join(columns)+') VALUES '
    fields = columns[3:]
    updates = ','.join(f'{key}=excluded.{key}' for key in fields)
    old = ','.join(fields)
    new = ','.join('excluded.'+key for key in fields)
    return insert, values, f'{insert}{values} ON CONFLICT(id) DO UPDATE SET {updates} WHERE ({old}) IS NOT ({new})'


_LEGACY_WRITE = _statements(_LINK_COLUMNS.split(','))
_NATIVE_WRITE = _statements((*_LINK_COLUMNS.split(','), *snapshots.REF_COLUMNS))


def put(db, rid, position, value):
    put_many(db, [(rid, position, value)])


def put_many(db, values, *, append=False):
    if not values:
        return
    relational = snapshots.enabled(db)
    cache={} if append else None
    pending = None
    if relational and append and getattr(db,'audits_independent_links',False):
        # The fragment batch is already in memory. Its insert triggers can
        # capture complete images without querying each just-written child.
        pending={}
        db.independent_appending=pending
    try:
        _put_batches(db,values,_NATIVE_WRITE if relational else _LEGACY_WRITE,relational,append,cache,pending)
    finally:
        if pending is not None:del db.independent_appending


def _put_batches(db,values,statements,relational,append,cache,pending):
    insert, placeholders, upsert = statements
    for start in range(0,len(values),400):
        batch, refs = [], []
        if pending is not None:pending.clear()
        for rid, position, value in values[start:start+400]:
            key = f'{rid}:{position}'
            row = (key, rid, position, *_values(value, relational=relational))
            if relational:
                fields, ref = snapshots.reference_fields(value,cache)
                if fields[-1]:
                    refs.append((key, fields[-1], ref))
                row += fields
                if pending is not None and 'segmentation_ref' in value:
                    pending[key]=value['segmentation_ref']
            batch.append(row)
        if relational:
            if refs and not append:
                keys = [key for key, _, _ in refs]
                current = dict(db.execute('SELECT id,ref_snapshot FROM independent_links WHERE id IN ('+
                                          ','.join('?' for _ in keys)+')', keys))
                refs = [ref for ref in refs if ref[1] != current.get(ref[0])]
            snapshots.store_references(db, refs)
        if append:
            db.execute(insert+','.join([placeholders]*len(batch)), [field for row in batch for field in row])
        else:
            db.executemany(upsert, batch)


def write_body(db, rid, body, *, language=None, bump=True):
    """Save source edits and their reordered or detached relationships together."""
    import sentence_rows
    new = language is not None and not db.execute('SELECT 1 FROM dictionary_examples WHERE id=?',(rid,)).fetchone()
    source = sentence_rows.write(db,'independent',rid,body,insert=new,
                                 columns={'language_id':language} if new else None,
                                 bump=bump,only_changed=language is None)
    if 'targets' in body:
        write_targets(db,rid,body['targets'])
    return source


def write_targets(db, rid, values):
    db.execute('DELETE FROM independent_links WHERE example_id=? AND position>=?',(rid,len(values)))
    put_many(db, [(rid,position,value) for position,value in enumerate(values)])


def identity(db, xid):
    return db.execute('''SELECT id,language_id,headword,revision FROM lexemes WHERE id=?
        UNION ALL SELECT id,language_id,form,revision FROM morphemes WHERE id=? LIMIT 1''', (xid,xid)).fetchone()


def refresh_keys(db,kind,owner,body):
    usages=body.get('usages')
    if usages is None and kind=='morpheme':
        usages=[dict(id='@morpheme',senses=[{'id':'@main'},*(body.get('senses') or [])])]
    wanted=set()
    for usage in usages or []:
        uid=usage.get('id')
        if uid is None:
            continue
        wanted.add(('usage',uid,'',''))
        wanted.update(('sense',sense['id'],uid,'') for sense in usage.get('senses') or [] if sense.get('id') is not None)
    wanted.update(('form',form['id'],'','') for form in body.get('variants') or [] if form.get('id') is not None)
    for paradigm in body.get('paradigms') or []:
        uid=paradigm.get('usage_id')
        if uid is None:
            continue
        for row in paradigm.get('rows') or []:
            for form in row.get('realizations') or []:
                wanted.update(('paradigm',meaning['id'],uid,form.get('form_id') or '')
                              for meaning in form.get('meanings') or [] if meaning.get('id') is not None)
    current={tuple(row) for row in db.execute(
        'SELECT kind,key,usage_id,form_id FROM independent_dictionary_keys WHERE target_id=?',(owner,))}
    db.executemany('DELETE FROM independent_dictionary_keys WHERE target_id=? AND kind=? AND key=? AND usage_id=? AND form_id=?',
                   ((owner,*row) for row in current-wanted))
    db.executemany('INSERT INTO independent_dictionary_keys VALUES(?,?,?,?,?)',
                   ((owner,*row) for row in wanted-current))


def validate_selection(db, xid, usage, sense, form):
    def has(kind, key, uid=''):
        return db.execute('SELECT 1 FROM independent_dictionary_keys WHERE target_id=? AND kind=? AND key=? AND usage_id=?',
                          (xid, kind, key, uid)).fetchone()
    if not usage and sense:
        raise ValueError('请先选择词类用法')
    if usage and not has('usage', usage):
        raise ValueError('关联的词类用法已不存在，请先调整语料关联')
    if sense and not (has('sense', sense, usage) or has('paradigm', sense, usage)):
        raise ValueError('关联的义项已不存在，请先调整语料关联')
    if form and not has('form', form):
        raise ValueError('关联的形式已不存在，请先调整用例关联再删除形式')
    if sense and db.execute('''SELECT 1 FROM independent_dictionary_keys
        WHERE target_id=? AND kind='paradigm' AND key=? AND (usage_id<>? OR form_id<>?) LIMIT 1''',
        (xid, sense, usage, form or '')).fetchone():
        raise ValueError('变形意义必须关联对应的词类用法与具体形式')


def validate(db, *, links=None, targets=None, examples=None):
    """Validate a changed set, or all distinct reference identities."""
    import lexicon
    import morphology
    if links is not None and targets is None and examples is None:
        return validate_links(db,links)
    sql = """SELECT DISTINCT e.language_id,l.lexeme_id,l.usage_id,l.sense_id,l.form_id,
        json_extract(l.payload,'$.features') features
        FROM independent_links l LEFT JOIN dictionary_examples e ON e.id=l.example_id"""
    scope = [(column, values) for column, values in
             (('l.id', links), ('l.lexeme_id', targets), ('l.example_id', examples)) if values is not None]
    refs = lexicon.scoped_rows(db, sql, scope) if scope else db.execute(sql)
    checked = set()
    for row in refs:
        key = tuple(row)
        if key in checked:
            continue
        checked.add(key)
        lid, xid, usage, sense, form, features = key
        entry = identity(db, xid)
        if not entry or entry['language_id'] != lid:
            raise ValueError('独立例句引用的词条已不存在或语言不一致')
        try:
            validate_selection(db, xid, usage, sense, form)
        except ValueError as error:
            raise ValueError('独立例句仍引用词条「'+entry['headword']+'」中要移除的义项、用法或形式，请先解除或调整关联。') from error
        if features:
            morphology.check_features(db, lid, json.loads(features))


def validate_links(db,ids):
    """Check a batch of changed link identities through the typed dictionary keys."""
    import long_tasks
    import morphology

    ids=sorted(ids)
    features=set()
    for start in long_tasks.steps(range(0,len(ids),600)):
        batch=ids[start:start+600]
        cursor=db.execute('''SELECT e.language_id,x.headword,COALESCE(x.language_id,m.language_id) target_language,
          m.form,l.payload->'$.features' features,
          (l.usage_id IS NOT NULL AND l.usage_id<>'' OR l.sense_id IS NULL OR l.sense_id='')
          AND (l.usage_id IS NULL OR l.usage_id='' OR EXISTS(SELECT 1 FROM independent_dictionary_keys k
               WHERE k.target_id=l.lexeme_id AND k.kind='usage' AND k.key=l.usage_id AND k.usage_id=''))
          AND (l.sense_id IS NULL OR l.sense_id='' OR EXISTS(SELECT 1 FROM independent_dictionary_keys k
               WHERE k.target_id=l.lexeme_id AND k.kind IN ('sense','paradigm') AND k.key=l.sense_id AND k.usage_id=l.usage_id))
          AND (l.form_id IS NULL OR l.form_id='' OR EXISTS(SELECT 1 FROM independent_dictionary_keys k
               WHERE k.target_id=l.lexeme_id AND k.kind='form' AND k.key=l.form_id AND k.usage_id=''))
          AND (l.sense_id IS NULL OR l.sense_id='' OR NOT EXISTS(SELECT 1 FROM independent_dictionary_keys k
               WHERE k.target_id=l.lexeme_id AND k.kind='paradigm' AND k.key=l.sense_id
                 AND (k.usage_id<>l.usage_id OR k.form_id<>COALESCE(l.form_id,'')))) valid
          FROM independent_links l LEFT JOIN dictionary_examples e ON e.id=l.example_id
          LEFT JOIN lexemes x ON x.id=l.lexeme_id LEFT JOIN morphemes m ON x.id IS NULL AND m.id=l.lexeme_id
          WHERE l.id IN ('''+','.join('?' for _ in batch)+')',batch)
        for lid,headword,target_language,form,value,valid in cursor:
            if not target_language or target_language!=lid:
                raise ValueError('独立例句引用的词条已不存在或语言不一致')
            if not valid:
                raise ValueError('独立例句仍引用词条「'+(headword if headword is not None else form)+'」中要移除的义项、用法或形式，请先解除或调整关联。')
            if value not in (None,'[]','null','false','0','""'):features.add((lid,value))
    for lid,value in features:
        parsed=json.loads(value)
        if parsed:morphology.check_features(db,lid,parsed)


def revision_only(before, after):
    from record_sources import same_body
    return bool(before and after and before['id']==after['id'] and
                before.get('language_id')==after.get('language_id') and
                same_body(before.get('body'),after.get('body')))


def replace(db, rid, position, value):
    """Append or rebind a relationship, including live gloss for the affected cell."""
    if position is None:
        position = db.execute('SELECT COALESCE(max(position),-1)+1 FROM independent_links WHERE example_id=?', (rid,)).fetchone()[0]
    _change(db, rid, {position: value})


def remove(db, rid, positions):
    if positions:
        _change(db, rid, dict.fromkeys(positions))


def _change(db, rid, changes):
    words = {row['word_position'] for row in db.execute(
        'SELECT position,word_position FROM independent_links WHERE example_id=?', (rid,)) if row['position'] in changes}
    for position, value in changes.items():
        if value is None:
            db.execute('DELETE FROM independent_links WHERE example_id=? AND position=?', (rid, position))
        else:
            put(db, rid, position, value)
            words.add((value.get('segmentation_ref') or {}).get('word'))
    if words - {None}:
        from gloss_inheritance import reconcile_independent_words
        reconcile_independent_words(db, rid, words - {None})
    db.execute('UPDATE dictionary_examples SET revision=revision+1 WHERE id=?', (rid,))


def save_selection(db, request, lid):
    """Save the association section of the standalone example editor."""
    import morphology
    rid = request.get('id')
    owner = db.execute('SELECT language_id,revision FROM dictionary_examples WHERE id=?', (rid,)).fetchone()
    if not owner or owner['language_id'] != lid or owner['revision'] != request.get('revision'):
        raise ValueError('例句关联已变化，请刷新后重试')
    incoming = request.get('targets')
    if not isinstance(incoming, list) or any(not isinstance(value, dict) for value in incoming):
        raise ValueError('词条例证关联格式无效')
    existing = images(db, rows(db, rid))
    next_position = existing[-1]['position'] + 1 if existing else 0
    kept = set()
    changes = {}
    seen = set()
    for item in incoming:
        index = item.get('index')
        previous = {}
        if index is not None:
            if type(index) is not int or not 0 <= index < len(existing) or index in kept:
                raise ValueError('例句关联已变化，请刷新后重试')
            kept.add(index)
            row = existing[index]
            position, previous = row['position'], target(row)
        else:
            position = next_position
            next_position += 1
        xid = item.get('lexeme_id')
        entry = identity(db, xid)
        if not entry or entry['language_id'] != lid:
            raise ValueError('例句只能关联同语言词条')
        usage, sense, form = (item.get(key) or None for key in KEYS[1:])
        validate_selection(db, xid, usage, sense, form)
        features = morphology.check_features(db, lid, item.get('features', []))
        value = {**previous, 'lexeme_id': xid, 'usage_id': usage, 'sense_id': sense, 'form_id': form, 'features': features}
        ref = value.get('segmentation_ref')
        key = (xid, usage, sense, form, json.dumps(ref, sort_keys=True))
        if key in seen:
            raise ValueError('例句引用重复')
        seen.add(key)
        if previous.get('lexeme_id') != xid:
            value.pop('component_ref', None)
        if any(previous.get(key) != value[key] for key in KEYS[:3]):
            value.pop('gloss_binding_id', None)
            value.pop('gloss_mode', None)
        if previous != value:
            changes[position] = value
    for i, row in enumerate(existing):
        if i not in kept:
            changes[row['position']] = None
    if changes:
        _change(db, rid, changes)
    return dict(id=rid, language_id=lid, revision=owner['revision']+bool(changes))


def word(db, rid, position):
    """Return (source snapshot if available, effective word) for one slot."""
    import record_sources
    import sentence_rows

    if not record_sources.native(db):
        row=db.execute('''SELECT e.body->? original,o.word,o.source FROM dictionary_examples e
            LEFT JOIN independent_word_overrides o ON o.example_id=e.id AND o.position=? WHERE e.id=?''',
            (f'$.words[{position}]',position,rid)).fetchone()
        if row and row['original'] is not None:
            if row['word'] is not None:return row['source'],json.loads(row['word'])
            return row['original'],json.loads(row['original'])
        return None,None
    typed=snapshots.enabled(db)
    frozen=snapshots.has_frozen_sql(db) if typed else '0'
    override_fields='o.snapshot,o.form override_form,o.gloss override_gloss,o.annotation_id,o.unit_id,o.word_fields' if typed else 'o.source,o.word'
    row=db.execute(f'''SELECT w.form,w.gloss,w.extra,o.id override_id,{override_fields},{frozen} has_frozen
        FROM sentence_word_rows w
        LEFT JOIN independent_word_overrides o ON o.example_id=w.owner_id AND o.position=w.position
        WHERE w.kind='independent' AND w.owner_id=? AND w.position=?''',(rid,position)).fetchone()
    if row:
        if row['override_id']:
            if not typed:return row['source'],json.loads(row['word'])
            item=dict(id=row['override_id'],snapshot=row['snapshot'],word_fields=row['word_fields'],
                      form=row['override_form'],gloss=row['override_gloss'],annotation_id=row['annotation_id'],unit_id=row['unit_id'])
            return snapshots.read_overrides(db,[item])[item['id']]
        value=sentence_rows.decode_word(row)
        if row['has_frozen']:
            value['gloss_frozen']=snapshots.frozen_for_owners(db,[rid],position=position)[rid,position]
        return None,value
    return None,None


def freeze_word(db, rid, position, source, word):
    oid=f'{rid}:{position}'
    if snapshots.enabled(db):
        fields=snapshots.override_fields(db,oid,source,word)
        columns=('snapshot', *snapshots.WORD_FIELDS, 'word_fields')
        db.execute('INSERT INTO independent_word_overrides(id,example_id,position,'+','.join(columns)+''')
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '''+
            ','.join(f'{key}=excluded.{key}' for key in columns)+' WHERE snapshot IS NOT excluded.snapshot',
            (oid,rid,position,*fields))
        return
    db.execute('''INSERT INTO independent_word_overrides VALUES(?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET source=excluded.source,word=excluded.word''',
        (oid,rid,position,source if isinstance(source,str) else snapshots.encoded(source),
         json.dumps(word,ensure_ascii=False,separators=(',',':'))))


def grouped_positions(db, xid, lid, form='all', *, ids=None):
    sql = '''SELECT l.example_id,l.position FROM independent_links l
        JOIN dictionary_examples e ON e.id=l.example_id WHERE l.lexeme_id=? AND e.language_id=?'''
    args = [xid, lid]
    if form == 'unassigned':
        sql += ' AND l.form_id IS NULL'
    elif form != 'all':
        sql += ' AND l.form_id=?'
        args.append(form)
    if ids is not None:
        if not ids:
            return {}
        sql += ' AND l.example_id IN ('+','.join('?' for _ in ids)+')'
        args.extend(ids)
    result = defaultdict(list)
    for row in db.execute(sql, args):
        result[row['example_id']].append(row['position'])
    return result
