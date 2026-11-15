"""Bounded dictionary reads and disposable literal headword keys.

Source identities, bodies and existing search semantics remain authoritative.
Only predicates on the primary form are handled here; richer fields retain the
complete dictionary matcher. Dirty keys follow source writes, including undo.
"""
import json

import long_tasks
import material_search_index
import record_sources
from search_keys import Values

SOURCES = (('lexemes', 'lexeme', 'headword'), ('morphemes', 'morpheme', 'form'))
TABLES = ('dictionary_form_search', 'dictionary_form_dirty')


def drop(db):
    for table, _, _ in SOURCES:
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            db.execute(f'DROP TRIGGER IF EXISTS dictionary_form_{table}_{event}')
    for table in TABLES:
        db.execute('DROP TABLE IF EXISTS ' + table)


def initialize(db):
    Values.initialize(db)
    number = 'homonym_number' if record_sources.native(db) else "json_extract(body,'$.homonym_number')"
    record_sources.schema_sql(db, f'''
      CREATE INDEX IF NOT EXISTS lexemes_list_language ON lexemes(language_id,headword COLLATE NOCASE,{number});
      CREATE INDEX IF NOT EXISTS lexemes_list_all ON lexemes(headword COLLATE NOCASE,{number});
      CREATE INDEX IF NOT EXISTS morphemes_list_language ON morphemes(language_id,form COLLATE NOCASE,number,id);
      CREATE INDEX IF NOT EXISTS morphemes_list_all ON morphemes(form COLLATE NOCASE,number,id);
      CREATE TABLE IF NOT EXISTS dictionary_form_search(kind TEXT,record_id TEXT,language_id TEXT,value_id INTEGER,
        PRIMARY KEY(kind,record_id)) WITHOUT ROWID;
      CREATE INDEX IF NOT EXISTS dictionary_form_values ON dictionary_form_search(value_id,kind,language_id,record_id);
      CREATE TABLE IF NOT EXISTS dictionary_form_dirty(kind TEXT,record_id TEXT,PRIMARY KEY(kind,record_id)) WITHOUT ROWID;
    ''')
    for table, kind, field in SOURCES:
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            db.execute(f'DROP TRIGGER IF EXISTS dictionary_form_{table}_{event}')
            refs = ('OLD', 'NEW') if event == 'UPDATE' else ('OLD',) if event == 'DELETE' else ('NEW',)
            when = f' WHEN OLD.id IS NOT NEW.id OR OLD.language_id IS NOT NEW.language_id OR OLD.{field} IS NOT NEW.{field}' if event == 'UPDATE' else ''
            statements = ''.join(f"INSERT INTO dictionary_form_dirty SELECT '{kind}',{ref}.id WHERE NOT EXISTS(SELECT 1 FROM dictionary_form_dirty WHERE kind='{kind}' AND record_id={ref}.id);" for ref in refs)
            db.execute(f'CREATE TRIGGER dictionary_form_{table}_{event} AFTER {event} ON {table}{when} BEGIN {statements} END')
        db.execute(f'''INSERT OR IGNORE INTO dictionary_form_dirty SELECT ?,s.id FROM {table} s
          WHERE NOT EXISTS(SELECT 1 FROM dictionary_form_search p WHERE p.kind=? AND p.record_id=s.id)''', (kind, kind))


def prepare(db, lid, kinds):
    values = Values(db)
    released = set()
    for table, kind, field in SOURCES:
        if kind not in kinds:
            continue
        sql = f'''SELECT d.record_id,s.language_id,s.{field} value,p.value_id FROM dictionary_form_dirty d
          LEFT JOIN {table} s ON s.id=d.record_id
          LEFT JOIN dictionary_form_search p ON p.kind=d.kind AND p.record_id=d.record_id WHERE d.kind=?'''
        args = [kind]
        if lid != 'all':
            sql += ' AND (s.language_id=? OR p.language_id=? OR s.id IS NULL)'
            args += [lid, lid]
        for row in long_tasks.steps(db.execute(sql, args).fetchall()):
            if row['value_id'] is not None:
                released.add(row['value_id'])
            db.execute('DELETE FROM dictionary_form_search WHERE kind=? AND record_id=?', (kind, row['record_id']))
            if row['language_id'] is not None:
                vid = values.intern(row['value'])
                db.execute('INSERT INTO dictionary_form_search VALUES(?,?,?,?)', (kind, row['record_id'], row['language_id'], vid))
            db.execute('DELETE FROM dictionary_form_dirty WHERE kind=? AND record_id=?', (kind, row['record_id']))
    values.release(released)
    return values


def predicate(db, lid, spec, query='', *, field='headword', kinds=('lexeme',)):
    """Return a validated narrow predicate, or None for the full matcher.

    Unsupported or invalid specs always fall through to the original validator.
    An empty entry-only picker needs neither documents nor a prepared key index.
    """
    spec = spec or {}
    if (spec.get('scope', 'all') not in ('all', 'entry') or
            spec.get('field', 'all') not in ('all', field) or
            spec.get('combine', 'all') not in ('all', 'any') or
            type(spec.get('case', False)) is not bool or spec.get('class_id', '') != ''):
        return None
    conditions = spec.get('conditions', [])
    if not isinstance(conditions, list) or len(conditions) > 50:
        return None
    for c in conditions:
        if (not isinstance(c, dict) or c.get('field') != field or
                c.get('op', 'contains') not in ('contains', 'exact', 'prefix', 'suffix', 'empty', 'present', 'not_contains') or
                not isinstance(c.get('value', ''), str) or
                c.get('op', 'contains') not in ('empty', 'present') and not c.get('value', '').strip()):
            return None
    if query.strip() and spec.get('field', 'all') != field:
        return None
    if not query.strip() and not conditions:
        return '', []
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='dictionary_form_search'").fetchone():
        return None
    try:
        with material_search_index.preparing(db):
            values = prepare(db, lid, kinds)
    except material_search_index.Unavailable:
        return None
    literal = None
    if query.strip() and not conditions:
        literal = ('contains', query.strip())
    elif not query.strip() and len(conditions) == 1:
        c = conditions[0]
        if c.get('op', 'contains') in ('contains', 'exact', 'prefix', 'suffix'):
            literal = (c.get('op', 'contains'), c.get('value', ''))
    if literal:
        # Start from the value index, then its postings. With only two target
        # kinds, an unanalysed SQLite planner otherwise prefers a kind-wide scan.
        query_sql, query_args = values.query(literal[1], spec.get('case', False), literal[0])
        sql = 'SELECT p.kind,p.record_id FROM (' + query_sql + ') v CROSS JOIN dictionary_form_search p ON p.value_id=v.id WHERE p.kind IN (' + ','.join('?' for _ in kinds) + ')'
        args = query_args + list(kinds)
        if lid != 'all':
            sql += ' AND p.language_id=?'
            args.append(lid)
        return sql, args
    args = list(kinds)
    sql = 'SELECT kind,record_id FROM dictionary_form_search WHERE kind IN (' + ','.join('?' for _ in kinds) + ')'
    if lid != 'all':
        sql += ' AND language_id=?'
        args.append(lid)

    def clause(op, value):
        negative = op in ('empty', 'not_contains')
        mode = 'present' if op == 'empty' else 'contains' if op == 'not_contains' else op
        query_sql, query_args = values.query(value, spec.get('case', False), mode)
        args.extend(query_args)
        return 'value_id ' + ('NOT IN (' if negative else 'IN (') + query_sql + ')'

    if query.strip():
        sql += ' AND ' + clause('contains', query.strip())
    if conditions:
        sql += ' AND (' + (' OR ' if spec.get('combine') == 'any' else ' AND ').join(clause(c.get('op', 'contains'), c.get('value', '')) for c in conditions) + ')'
    return sql, args


def _summary(alias):
    body = alias + '.body'
    usage = "json_object('pos',CASE WHEN json_type(u.value,'$.pos') IS NULL THEN '' ELSE json_extract(u.value,'$.pos') END,'subclass',CASE WHEN json_type(u.value,'$.subclass') IS NULL THEN '' ELSE json_extract(u.value,'$.subclass') END)"
    return f"json_object('homonym_number',json_extract({body},'$.homonym_number'),'homonym_note',json_extract({body},'$.homonym_note'),'usages',json((SELECT json_group_array({usage}) FROM json_each({body},'$.usages') u)))"


def choice_page(db, lid, needle, page_number, exclude):
    """Count and sort candidate forms on native keys, then fetch page metadata."""
    uses_number = any(c in needle for c in '₀₁₂₃₄₅₆₇₈₉')
    if needle:
        subscript = str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉')

        def matches(form, number):
            label = form + (str(number).translate(subscript) if number else '')
            return needle in label.lower()

        db.create_function('dictionary_choice_match', 2, matches, deterministic=True)

    scope = []
    params = []
    if lid != 'all':
        scope.append('s.language_id=?')
        params.append(lid)
    total = 0
    branches = []
    for table, kind, form in SOURCES:
        if kind == 'lexeme':
            number = 's.homonym_number' if record_sources.native(db) else "json_extract(s.body,'$.homonym_number')"
        else:
            number = ('CASE WHEN EXISTS(SELECT 1 FROM morphemes p WHERE p.language_id=s.language_id '
                      'AND p.form=s.form AND p.number<>s.number) THEN s.number END')
        clauses = list(scope)
        args = list(params)
        if exclude:
            clauses.append(f's.rowid IS NOT (SELECT rowid FROM {table} WHERE id=?)')
            args.append(exclude)
        if needle:
            clauses.append(f'dictionary_choice_match(s.{form},{number if uses_number else "NULL"})')
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        total += db.execute(f'SELECT count(*) FROM {table} s{where}', args).fetchone()[0]
        clauses.append('EXISTS(SELECT 1 FROM languages valid WHERE valid.id=s.language_id)')
        where = ' WHERE ' + ' AND '.join(clauses)
        branches.append((table, kind, form, number, where, args))

    size = 50
    pages = max(1, (total + size - 1) // size)
    page_number = max(1, min(int(page_number), pages))
    if total == 0:
        return dict(items=[],total=total,page=page_number,pages=pages)
    sources = []
    args = []
    for table, kind, form, number, where, bindings in branches:
        sources.append(f"""SELECT * FROM (SELECT '{kind}' target_kind,s.rowid sort_rowid,s.{form} headword,
            {number} homonym_number FROM {table} s{where}
            ORDER BY headword COLLATE NOCASE,homonym_number,sort_rowid LIMIT ?)""")
        args.extend([*bindings,page_number * size])
    sql = f"""WITH candidates AS MATERIALIZED (
        SELECT * FROM ({' UNION ALL '.join(sources)})
        ORDER BY headword COLLATE NOCASE,homonym_number,sort_rowid,target_kind LIMIT ? OFFSET ?
    ) SELECT c.*,coalesce(x.id,m.id) id,coalesce(x.language_id,m.language_id) language_id,
        coalesce(x.revision,m.revision) revision,l.name language_name
        FROM candidates c LEFT JOIN lexemes x ON c.target_kind='lexeme' AND x.rowid=c.sort_rowid
        LEFT JOIN morphemes m ON c.target_kind='morpheme' AND m.rowid=c.sort_rowid
        JOIN languages l ON l.id=coalesce(x.language_id,m.language_id)
        ORDER BY c.headword COLLATE NOCASE,c.homonym_number,c.sort_rowid,c.target_kind"""
    args.extend((size, (page_number - 1) * size))
    items = [dict(id=r['id'],language_id=r['language_id'],headword=r['headword'],revision=r['revision'],
                  rowid=r['sort_rowid'],target_kind=r['target_kind'],language_name=r['language_name'],
                  body={'homonym_number':r['homonym_number']}) for r in db.execute(sql, args)]
    return dict(items=items,total=total,page=page_number,pages=pages)


def page(db, lid, page_number, page_size, *, targets=False, summary=False, ids_only=False, order='', predicate=('', ()), exclude=''):
    """Sort narrow native identities, then hydrate only the requested window."""
    filtered, args = predicate
    def scope(table, kind, omit=False):
        params = []
        source = table + ' s'
        if filtered:
            # Drive selective predicates from matched keys. A tuple IN on the
            # display view made SQLite scan a whole language despite an exact hit.
            source = "(SELECT record_id FROM (" + filtered + ") WHERE kind='" + kind + "') k CROSS JOIN " + source + ' ON s.id=k.record_id'
            params.extend(args)
        if lid != 'all':
            source += ' WHERE s.language_id=?'
            params.append(lid)
        if exclude and not omit:
            source += (' AND ' if lid != 'all' else ' WHERE ')+'s.id<>?'
            params.append(exclude)
        return source, params

    branches = [scope('lexemes', 'lexeme')]
    if targets:
        branches.append(scope('morphemes', 'morpheme'))
    count_branches=[scope('lexemes','lexeme',omit=True)]
    if targets:count_branches.append(scope('morphemes','morpheme',omit=True))
    count_params=[value for _, values in count_branches for value in values]
    count_source = ' UNION ALL '.join('SELECT s.id FROM ' + source for source, _ in count_branches)
    total = db.execute('SELECT count(*) FROM (' + count_source + ')', count_params).fetchone()[0]
    if exclude:
        total-=db.execute('SELECT count(*) FROM ('+count_source+') WHERE id=?',[*count_params,exclude]).fetchone()[0]
    size = max(1, total) if str(page_size) == 'all' else int(page_size)
    pages = max(1, (total + size - 1) // size)
    page_number = max(1, min(int(page_number), pages))
    native = record_sources.native(db)
    number = 's.homonym_number' if native else "json_extract(s.body,'$.homonym_number')"
    def date(kind):
        if not order:
            return ''
        import entry_dates
        value = entry_dates.relational_date('s',kind) if native else "json_extract(s.body,'$.created_at')"
        return ',' + value + ' created_at'
    sources = [f"SELECT s.id,s.language_id,s.headword,'lexeme' target_kind,s.rowid sort_rowid,{number} sort_number" + date('lexeme') + ' FROM ' + branches[0][0]]
    if targets:
        sources.append("SELECT s.id,s.language_id,s.form headword,'morpheme' target_kind,s.rowid sort_rowid,CASE WHEN (SELECT count(*) FROM morphemes p WHERE p.language_id=s.language_id AND p.form=s.form)>1 THEN s.number END sort_number" + date('morpheme') + ' FROM ' + branches[1][0])
    params=[]
    if not ids_only and not order:
        # The first K rows of a merged order can only contain the first K
        # from each branch. Let native list indexes stop at that bound instead
        # of hydrating/sorting every identity before displaying a small window.
        bound=page_number*size
        sources=['SELECT * FROM (SELECT b.* FROM ('+sql+') b JOIN languages valid ON valid.id=b.language_id ORDER BY b.headword COLLATE NOCASE,b.sort_number,b.sort_rowid LIMIT ?)' for sql in sources]
        for _, values in branches:params.extend([*values,bound])
    else:
        params=[value for _, values in branches for value in values]
    source=' UNION ALL '.join(sources)
    # The display UNION lists lexemes first when native sort keys coincide.
    # Make that tie explicit; selective joins can otherwise swap the branches.
    ordering = ('x.created_at IS NULL,x.created_at ' + ('DESC' if order == '@added-desc' else 'ASC') + ',x.id,x.target_kind') if order else 'x.headword COLLATE NOCASE,x.sort_number,x.sort_rowid,x.target_kind'
    sql = 'SELECT x.id,x.target_kind FROM (' + source + ') x JOIN languages l ON l.id=x.language_id ORDER BY ' + ordering
    if not ids_only:
        sql += ' LIMIT ? OFFSET ?'
        params += [size, (page_number - 1) * size]
    keys = [(r['target_kind'], r['id']) for r in db.execute(sql, params)]
    if ids_only:
        return [xid for _, xid in keys]
    if native:
        import dictionary_rows
        if summary and not targets:
            rows=dictionary_rows.lexeme_summaries(db,[xid for _,xid in keys])
            return dict(items=[rows[xid] for _,xid in keys],total=total,page=page_number,pages=pages)
        rows = dictionary_rows.targets(db,[xid for _,xid in keys])
        items = []
        for _, xid in keys:
            row = rows[xid]
            if not targets:
                row.pop('target_kind')
                row.pop('rowid')
            if summary:
                body = row['body']
                row['body'] = dict(homonym_number=body.get('homonym_number'),homonym_note=body.get('homonym_note'),
                    usages=[dict(pos=u.get('pos',''),subclass=u.get('subclass','')) for u in body.get('usages') or ()])
            items.append(row)
        return dict(items=items,total=total,page=page_number,pages=pages)
    rows = {}
    source = 'dictionary_targets' if targets else 'lexemes'
    columns = 'x.*,l.name language_name'
    if summary:
        columns = 'x.id,x.language_id,x.headword,' + _summary('x') + ' body,x.revision,' + ('x.rowid,x.target_kind,' if targets else '') + 'l.name language_name'
    for start in range(0, len(keys), 400):
        batch = [xid for _, xid in keys[start:start + 400]]
        sql = 'SELECT ' + columns + ' FROM ' + source + ' x JOIN languages l ON l.id=x.language_id WHERE x.id IN (' + ','.join('?' for _ in batch) + ')'
        for r in db.execute(sql, batch):
            row = {**dict(r), 'body': json.loads(r['body'])}
            rows[(row.get('target_kind', 'lexeme'), row['id'])] = row
    return dict(items=[rows[key] for key in keys], total=total, page=page_number, pages=pages)
