"""Disposable proof that scoped saves start from a fully checked database.

Persistent source triggers also notice writes from other SQLite connections and
older clients. No research content or undo records are stored in this cache.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import sqlite3
import record_sources


# Bump when validation rules change, independently of the release number.
RULES_VERSION = 4
TABLE = 'save_validation_state'
PREFIX = 'save_validation_watch_'
CURRENT = ContextVar('save_validation', default=None)


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def state(db):
    try:
        row = db.execute('SELECT rules,signature,epoch,checked_epoch,checked_schema FROM ' + TABLE + ' WHERE id=1').fetchone()
        return dict(zip(('rules','signature','epoch','checked_epoch','checked_schema'), row)) if row else None
    except sqlite3.OperationalError:
        return None


def snapshot(db):
    row = state(db)
    if row and row['rules'] == RULES_VERSION and row['epoch'] == row['checked_epoch'] and row['checked_schema'] == db.execute('PRAGMA main.schema_version').fetchone()[0]:
        return row
    return None


def definitions(db):
    import journal
    import independent_annotations
    import read_views
    specifications = []
    triggers = {}
    relational = record_sources.native(db)
    child_sources = {
        'sentence_text_rows': ('kind', 'owner_id', {'corpus':'entries','independent':'dictionary_examples'}),
        'sentence_word_rows': ('kind', 'owner_id', {'corpus':'entries','independent':'dictionary_examples'}),
        'dictionary_value_rows': ('target_kind', 'target_id', {'lexeme':'lexemes','morpheme':'morphemes'}),
    } if relational else {}
    snapshots = (independent_annotations.FRAGMENTS, independent_annotations.REF_VALUES,
                 independent_annotations.OVERRIDE_VALUES, independent_annotations.FROZEN_VALUES) if independent_annotations.enabled(db) else ()
    batched = relational and read_views.association_batch_ready(db)
    batch_tables=(*read_views.ASSOCIATION_TABLES,independent_annotations.FRAGMENTS,independent_annotations.REF_VALUES)
    if batched:
        # Publish the batch's epoch in SQLite when the writer clears the
        # marker. This also covers older clients that already use the marker.
        name=PREFIX+'association_batch'
        triggers[name]=(f'CREATE TRIGGER {quote(name)} AFTER DELETE ON read_view_association_batch '
                        f'BEGIN UPDATE {TABLE} SET epoch=epoch+1 WHERE id=1; END')
    for table in dict.fromkeys((*journal.TABLES,*child_sources,*snapshots)):
        columns = [r[1] for r in db.execute('PRAGMA main.table_info(' + quote(table) + ')')]
        if not columns:
            continue
        native_owner = relational and table in record_sources.TABLES
        if native_owner:
            columns = list(record_sources.META[table])
        specifications.append((table, columns))
        fields = columns if table in child_sources or table in snapshots else ['rowid',*columns]
        changed = ' OR '.join('OLD.' + quote(c) + ' IS NOT NEW.' + quote(c) for c in fields)
        if native_owner:
            changed += ' OR ' + record_sources.change_sql(db,table)
        for event in ('INSERT','UPDATE','DELETE'):
            name = PREFIX + table + '_' + event.lower()
            condition = ' WHEN ' + changed if event == 'UPDATE' else ''
            if table in child_sources:
                kind, owner, sources = child_sources[table]
                ref = 'OLD' if event == 'DELETE' else 'NEW'
                case = 'CASE '+ref+'.'+kind+' '+ ' '.join(f"WHEN '{k}' THEN '{v}'" for k,v in sources.items()) + ' END'
                condition = (' WHEN NOT EXISTS(SELECT 1 FROM record_source_writes '
                             f'WHERE source=({case}) AND owner_id={ref}.{owner})')
            elif table in snapshots:
                # Normal writes publish a complete snapshot by changing its
                # parent row. Notice direct edits to a live child as well.
                refs=('OLD','NEW') if event=='UPDATE' else ('OLD',) if event=='DELETE' else ('NEW',)
                if table==independent_annotations.FROZEN_VALUES:
                    predicate=lambda ref:('NOT EXISTS(SELECT 1 FROM record_source_writes '
                        f"WHERE source='dictionary_examples' AND owner_id={ref}.owner_id)")
                else:
                    parent,key=('independent_word_overrides','snapshot') if table==independent_annotations.OVERRIDE_VALUES else ('independent_links','ref_snapshot')
                    predicate=lambda ref:(f'EXISTS(SELECT 1 FROM {parent} WHERE id={ref}.parent_id '
                                          f'AND {key}={ref}.snapshot)')
                active=' OR '.join(predicate(ref) for ref in refs)
                condition=(' WHEN ('+condition[6:]+') AND ('+active+')') if condition else ' WHEN '+active
            if batched and table in batch_tables:
                batch='NOT EXISTS(SELECT 1 FROM read_view_association_batch WHERE id=1)'
                condition=' WHEN '+batch+(' AND ('+condition[6:]+')' if condition else '')
            triggers[name] = 'CREATE TRIGGER ' + quote(name) + ' AFTER ' + event + ' ON ' + quote(table) + condition + ' BEGIN UPDATE ' + TABLE + ' SET epoch=epoch+1 WHERE id=1; END'
    signature = hashlib.sha256(json.dumps(specifications, ensure_ascii=True).encode()).hexdigest()
    return signature, triggers


def initialize(db, prior=None):
    """Repair guards; only trusted startup migrations can carry a prior proof."""
    signature, expected = definitions(db)
    columns = {r[1] for r in db.execute('PRAGMA main.table_info(' + TABLE + ')')}
    if columns and columns != {'id','rules','signature','epoch','checked_epoch','checked_schema'}:
        drop(db)
    db.execute('CREATE TABLE IF NOT EXISTS ' + TABLE + '(id INTEGER PRIMARY KEY CHECK(id=1),rules INTEGER NOT NULL,signature TEXT NOT NULL,epoch INTEGER NOT NULL,checked_epoch INTEGER NOT NULL,checked_schema INTEGER NOT NULL)')
    db.execute('INSERT OR IGNORE INTO ' + TABLE + ' VALUES(1,?,?,0,-1,-1)', (RULES_VERSION,signature))
    previous = state(db)
    existing = {r[0]:r[1] for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND substr(name,1,?)=?", (len(PREFIX),PREFIX))}
    for name, sql in existing.items():
        if expected.get(name) != sql:
            db.execute('DROP TRIGGER ' + quote(name))
    for name, sql in expected.items():
        if existing.get(name) != sql:
            db.execute(sql)
    preserve = prior is not None and previous is not None and prior['rules'] == RULES_VERSION and prior['signature'] == signature and previous['epoch'] == prior['epoch'] and previous['signature'] == signature
    db.execute('UPDATE ' + TABLE + ' SET rules=?,signature=?,checked_epoch=?,checked_schema=? WHERE id=1',
               (RULES_VERSION,signature,previous['epoch'] if preserve else -1,db.execute('PRAGMA main.schema_version').fetchone()[0]))


def drop(db):
    drop_triggers(db)
    db.execute('DROP TABLE IF EXISTS ' + TABLE)


def drop_triggers(db):
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND substr(name,1,?)=?", (len(PREFIX),PREFIX))]
    for name in names:
        db.execute('DROP TRIGGER ' + quote(name))


@dataclass
class Check:
    db: object
    trusted: bool
    schema: int
    finalizing: bool = False
    full_checked: bool = False
    scoped_structure: bool = False


def begin(db):
    schema = db.execute('PRAGMA main.schema_version').fetchone()[0]
    row = state(db)
    if row is None or row['rules'] != RULES_VERSION or row['checked_schema'] != schema:
        initialize(db)
        schema = db.execute('PRAGMA main.schema_version').fetchone()[0]
    return CURRENT.set(Check(db, snapshot(db) is not None, schema))


def trusted(db):
    check = CURRENT.get()
    return bool(check and check.db is db and check.trusted)


def full_checked(db):
    check = CURRENT.get()
    if check and check.db is db and check.finalizing:
        check.full_checked = True


@contextmanager
def final_check(db):
    check = CURRENT.get()
    previous = check.finalizing if check and check.db is db else None
    if previous is not None:
        check.finalizing = True
    try:
        yield
    finally:
        if previous is not None:
            check.finalizing = previous


def complete(db):
    check = CURRENT.get()
    if check and check.db is db and (check.trusted or check.full_checked) and check.schema == db.execute('PRAGMA main.schema_version').fetchone()[0]:
        db.execute('UPDATE ' + TABLE + ' SET checked_epoch=epoch,checked_schema=? WHERE id=1', (check.schema,))


@dataclass
class ViewUpdate:
    """Describe the committed changes that can refresh the requesting view."""
    table: str
    kind: str
    record_id: str
    base: str
    assignment_revision: int | None = None
    matches_base: bool = False
    receipt: dict | None = None

    def begin(self, db):
        import journal
        self.matches_base = trusted(db) and journal.workspace_revision(db) == self.base

    def finish(self, db, changes):
        if not self.matches_base:
            return
        changed = []
        meanings_changed = []
        for (table,_),(before,after) in changes.items():
            if table=='history' or before==after:continue
            if table=='gloss_bindings' and before and after and before['owner_kind']==self.kind and before['owner_id']==self.record_id:
                # capture_canonical only advances these markers after checking
                # that the already-displayed effective gloss equals the source.
                markers={'source_binding_revision','source_meaning_revision'}
                if all(before.get(k)==after.get(k) for k in before.keys()|after.keys() if k not in markers):continue
            if table=='gloss_meanings' and self.kind=='lexeme' and before and after and before['target_id']==self.record_id:
                if all(before.get(k)==after.get(k) for k in before.keys()|after.keys() if k not in ('gloss','revision')):
                    if before['gloss']!=after['gloss']:
                        meanings_changed.append((before['gloss'],after['gloss']))
                    continue
            changed.append((table,before,after))
        check=CURRENT.get()
        if check and check.db is db and check.scoped_structure:
            if self.kind == 'lexeme':
                self.lexeme_structure(db, changed, meanings_changed)
            else:
                self.sentence_structure(db, changed)
            if self.receipt:
                return
        if len(changed) != 1:
            return
        table, before, after = changed[0]
        if table != self.table or not before or not after or after['id'] != self.record_id:
            return
        sense_edit=sense_text_only(changed)
        if meanings_changed and not sense_edit:return
        if not sense_edit and not text_only(changed):return
        old, new = record_sources.body(before,mutable=False), record_sources.body(after,mutable=False)
        if self.kind=='lexeme' and _variant_notes(old)!=_variant_notes(new):
            self.lexeme_structure(db,changed,meanings_changed)
            if self.receipt:return
        fields = ('notes',) if self.kind == 'lexeme' else ('translation', 'notes')
        values = {key: new.get(key, '') for key in fields if new.get(key, '') != old.get(key, '')}
        self.record_receipt(db,before['revision'],after['revision'],values=values)
        if sense_edit:
            self.receipt['sense_text']=True
            self.receipt.update(_lexeme_evidence_update(old,new,meanings_changed))
            self.receipt.setdefault('evidence',[])

    def record_receipt(self, db, before, after, **details):
        import journal
        self.receipt = dict(kind=self.kind, id=self.record_id, before_revision=before, revision=after,
                            base=self.base, current=journal.workspace_revision(db), **details)

    def sentence_structure(self, db, changed):
        owner = self.record_id
        units = {row['id']: row['entry_id'] for table, before, after in changed if table == 'corpus_units'
                 for row in (before, after) if row}

        def local_unit(uid):
            if uid not in units:
                row = db.execute('SELECT entry_id FROM corpus_units WHERE id=?', (uid,)).fetchone()
                units[uid] = row[0] if row else None
            return units[uid] == owner

        before = after = None
        tier_changed = False
        for table, a, b in changed:
            rows = [row for row in (a, b) if row]
            if table == self.table and all(row['id'] == owner for row in rows):
                before, after = a, b
            elif table == 'annotation_cells' and all((row['owner_kind'], row['record_id']) == (self.kind, owner) for row in rows):
                tier_changed = True
            elif table == 'gloss_bindings' and all((row['owner_kind'], row['owner_id']) == (self.kind, owner) for row in rows):
                continue
            elif self.kind == 'independent' and table in ('independent_links', 'independent_word_overrides') and all(row['example_id'] == owner for row in rows):
                continue
            elif self.kind == 'corpus' and table == 'corpus_units' and all(row['entry_id'] == owner for row in rows):
                continue
            elif self.kind == 'corpus' and table in ('unit_segments', 'lexical_links', 'lexical_reviews'):
                for row in rows:
                    if table == 'lexical_reviews':
                        link = db.execute('SELECT unit_id FROM lexical_links WHERE id=?', (row['id'],)).fetchone()
                        if not link or not local_unit(link[0]):
                            return
                    elif not local_unit(row['unit_id'] if table == 'lexical_links' else row['id']):
                        return
            else:
                return
        if before is None and after is None and tier_changed:
            # A manual tier can change without advancing the sentence revision.
            before = after = db.execute('SELECT * FROM '+self.table+' WHERE id=?',(owner,)).fetchone()
        if not before or not after:
            return
        if any(before[key] != after[key] for key in record_sources.ATTRIBUTES[self.table]):
            return
        import gloss_inheritance
        # Read the display after synchronization, independently of earlier draft reads.
        token = gloss_inheritance.CURRENT.set(None)
        try:
            if self.kind == 'corpus':
                import corpus_search
                record = corpus_search.saved_card(db, owner)
            else:
                import annotations
                record = annotations.independent_card(db, owner)
        finally:
            gloss_inheritance.CURRENT.reset(token)
        if record:
            self.record_receipt(db, before['revision'], after['revision'], record=record, values={})

    def lexeme_structure(self,db,changed,meanings_changed):
        before=after=None
        registry=False
        evidence=set()
        for table,a,b in changed:
            rows=[row for row in (a,b) if row]
            if table=='lexemes' and a and b and a['id']==b['id']==self.record_id:
                before,after=a,b
            elif table=='morpheme_components' and all(row['lexeme_id']==self.record_id for row in rows):registry=True
            elif table=='morphemes' and _same_columns(a,b,{'revision'}):continue
            elif table=='category_classes' and not a and b and b['kind'] in ('pos','form','usage_tag'):continue
            elif table in ('entries','corpus_units','unit_segments','lexical_links','lexical_reviews'):evidence.add('corpus')
            elif table=='dictionary_examples':evidence.add('independent')
            elif table in ('annotation_cells','gloss_bindings'):evidence.update(row['owner_kind'] for row in rows)
            else:return
        if after:
            old,new=(record_sources.body(row,mutable=False) for row in (before,after))
            import word_structure
            if old.get('semantic_classes',[])!=new.get('semantic_classes',[]):return
            morphology=old.get('word_structure',{})!=new.get('word_structure',{})
            writings=old.get('orthographies',[])!=new.get('orthographies',[])
            variants=old.get('variants',[])!=new.get('variants',[]) or (writings and bool(new.get('variants')))
            heading=(before['headword'],old.get('homonym_number'))!=(after['headword'],new.get('homonym_number'))
            memberships=old.get('word_structure',{}).get('memberships',[])!=new.get('word_structure',{}).get('memberships',[])
            form_list=[v['id'] for v in old.get('variants',[])]!=[v['id'] for v in new.get('variants',[])]
            relation=old.get('relation')!=new.get('relation')
            morphology_options=relation or word_structure.references(old)!=word_structure.references(new)
            usages=_display_usages(old)!=_display_usages(new)
            fields={
                'summary':memberships or any(old.get(field)!=new.get(field) for field in ('entry_type','orthographies','homonym_note')),
                'tags':old.get('tags')!=new.get('tags'),
                'definitions':usages,
                'paradigms':old.get('paradigms',[])!=new.get('paradigms',[]) or (usages and bool(new.get('paradigms'))),
                'list':old.get('homonym_note')!=new.get('homonym_note') or _list_labels(old)!=_list_labels(new),
                'form_list':form_list,
                'morphology_details':form_list or relation or old.get('features',[])!=new.get('features',[]),
            }
            evidence_update=_lexeme_evidence_update(old,new,meanings_changed,evidence)
            prior_revision,revision=before['revision'],after['revision']
        elif registry and self.assignment_revision is not None:
            morphology=variants=heading=False
            prior_revision=revision=self.assignment_revision
            fields={}
            evidence_update={}
            morphology_options=False
        else:return
        details=dict(structure=dict(heading=heading,morphology=morphology,variants=variants,
                                   registry=registry or morphology,evidence=sorted(evidence)),values={})
        details.update(evidence_update)
        presentation=[key for key,edited in fields.items() if edited]
        if presentation:details['presentation']=presentation
        if morphology_options:details['morphology_options']=True
        if registry or morphology or self.assignment_revision is not None:
            import morpheme_registry
            data=morpheme_registry.components(db,self.record_id,'all')
            if data['lexeme']['revision']!=revision:return
            details['components']=data['items']
            if self.assignment_revision is not None:details['record']=data['lexeme']
        self.record_receipt(db,prior_revision,revision,**details)

    def attach(self, result):
        if self.receipt is not None:
            result['_view_update'] = self.receipt


def view_update(operation, body):
    if operation=='lexeme-auto-link' and body.get('reuse_preview') is True:
        from auto_link_update import Continuation
        return Continuation(body)
    if operation in ('dictionary-replace-apply','text-replace-apply') and body.get('reuse_preview') is True:
        from replacement_preview import Continuation
        return Continuation(operation,body)
    base = body.get('_view_revision')
    if not isinstance(base, str) or len(base) != 64:
        return None
    if operation=='morpheme-assign' and body.get('lexeme_id') and type(body.get('lexeme_revision')) is int:
        return ViewUpdate('lexemes','lexeme',body['lexeme_id'],base,assignment_revision=body['lexeme_revision'])
    if not body.get('id'):return None
    if operation == 'lexeme-save':
        return ViewUpdate('lexemes', 'lexeme', body['id'], base)
    if operation == 'inline-save' and body.get('kind') == 'corpus':
        return ViewUpdate('entries','corpus',body['id'],base)
    if operation == 'inline-save' and body.get('kind') == 'independent':
        return ViewUpdate('dictionary_examples', 'independent', body['id'], base)
    return None


def _retain_unknown(raw, normalized):
    """Supply canonical defaults without hiding unknown fields at any depth."""
    if isinstance(raw,dict) and isinstance(normalized,dict):
        return {key:_retain_unknown(raw[key],normalized[key]) if key in raw and key in normalized else raw[key] if key in raw else normalized[key] for key in raw.keys() | normalized.keys()}
    if isinstance(raw,list) and isinstance(normalized,list):
        return [_retain_unknown(a,b) for a,b in zip(raw,normalized)] if len(raw) == len(normalized) else raw
    return normalized


def sense_text_only(changed):
    """Only strings on existing, ordered sense identities can differ."""
    if len(changed)!=1:return False
    table,before,after=changed[0]
    if table!='lexemes' or not before or not after:return False
    old=record_sources.body(before,mutable=False);new=record_sources.body(after)
    edited=False
    for left,right in zip(old.get('usages',[]),new.get('usages',[])):
        if left.get('id')!=right.get('id'):return False
        for a,b in zip(left.get('senses',[]),right.get('senses',[])):
            if a.get('id')!=b.get('id'):return False
            for name in ('short_gloss','definition','notes'):
                if a.get(name,'')==b.get(name,''):continue
                if not isinstance(a.get(name,''),str) or not isinstance(b.get(name,''),str):return False
                edited=True
                if name in a:b[name]=a[name]
                else:b.pop(name,None)
    return edited and text_only([(table,before,{**after,'body':new})])


def text_only(changed):
    """Prove unchanged identities, definitions, slots, layers and dependencies."""
    dictionary=('lexemes','morphemes')
    if not changed:return False
    for table, before, after in changed:
        if table not in (*dictionary,'entries','dictionary_examples') or not before or not after:
            return False
        if {k:v for k,v in before.items() if k not in ('body','revision')} != {k:v for k,v in after.items() if k not in ('body','revision')}:
            return False
        try:
            bodies = [dict(record_sources.body(row,mutable=table=='lexemes')) for row in (before,after)]
            if any(not isinstance(body,dict) for body in bodies):
                return False
            fields = ('notes',) if table in dictionary else ('notes','translation')
            if any(not isinstance(body.get(field,''),str) for body in bodies for field in fields):
                return False
            if table == 'lexemes':
                import lexicon
                bodies = [_retain_unknown(body,lexicon.normalize(body)) for body in bodies]
                import multipart_forms
                for body in bodies:
                    # The editor materializes these optional, equivalent defaults.
                    # An omitted legacy circumfix can infer parts, unlike [].
                    if not multipart_forms.circumfix(body):
                        body.setdefault('form_parts',[])
                        for variant in body.get('variants',[]):
                            if not multipart_forms.circumfix(variant):variant.setdefault('form_parts',[])
                    # Notes on an existing form cannot affect an occurrence link.
                    for variant in body.get('variants',[]):
                        if not isinstance(variant.get('notes',''),str):return False
                        variant.pop('notes',None)
                    for usage in body.get('usages',[]):
                        for sense in usage.get('senses',[]):
                            sense.setdefault('gloss_addition','')
                            sense.setdefault('show_gloss_addition',True)
            elif table not in dictionary:
                for body, row in zip(bodies,(before,after)):
                    if 'edited' in body and not isinstance(body['edited'],bool):
                        return False
                    body.pop('edited',None)
                    if table == 'dictionary_examples':
                        if body.get('language_id',row['language_id']) != row['language_id']:
                            return False
                        body['language_id'] = row['language_id']
                        body.setdefault('original','')
                    body.setdefault('grammaticality','')
            for body in bodies:
                for field in fields:
                    body.pop(field,None)
            if bodies[0] != bodies[1]:
                return False
        except (ValueError,TypeError,KeyError,AttributeError):
            return False
    return True


def validate_research_text(db,changed):
    """Check the edited note/outline payload when its identity and placement stay fixed."""
    editable={'survey_nodes':{'body','title','revision'},'fieldwork_notes':{'body','title','preview','revision'}}
    if not all(table in editable and _same_columns(before,after,editable[table])
               for table,before,after in changed):
        return False
    import fieldwork_notes,grammar_survey
    for table,_,row in changed:
        body=json.loads(row['body'])
        if table=='fieldwork_notes':
            title,_,preview=fieldwork_notes.clean(db,row['language_id'],dict(title=row['title'],body=body))
            if row['title']!=title or row['preview']!=preview:raise ValueError('调查笔记内容或顺序格式无效')
        else:
            title=row['title']
            if not isinstance(title,str) or not title.strip() or len(title)>500:raise ValueError('调查条目无效')
            grammar_survey.clean_body(db,body,row['language_id'])
    return True


def _same_columns(before, after, excluded):
    return bool(before and after and all(before.get(k)==after.get(k)
                for k in before.keys()|after.keys() if k not in excluded))


def _target_dependencies(body,kind):
    editable={'word_structure','form_parts'}
    if kind=='lexemes':editable.update(('homonym_number','headword_source'))
    fields={key:value for key,value in body.items() if key not in editable}
    if kind=='lexemes' and 'usages' in fields:
        fields['usages']=_display_usages(body)
    if 'variants' in fields:
        # Meanings and paradigms refer to variant IDs, not to their realization.
        fields['variants']=[{k:v for k,v in item.items() if k not in ('form','form_parts','pronunciation')}
                            for item in fields['variants']]
    return fields


def _display_usages(body):
    return [{**usage,'senses':[{'gloss_addition':'','show_gloss_addition':True,**sense}
                              for sense in usage.get('senses',[])]} for usage in body.get('usages',[])]


def _list_labels(body):
    return [(usage.get('pos',''),usage.get('subclass','')) for usage in body.get('usages',[])]


def _variant_notes(body):
    return [(form['id'],form.get('notes','')) for form in body.get('variants',[])]


def _evidence_labels(body):
    import paradigms
    return [(usage['id'],usage.get('pos',''),[(sense['id'],sense.get('short_gloss',''),
                sense.get('gloss_addition',''),sense.get('show_gloss_addition',True))
                for sense in usage['senses']]) for usage in paradigms.usages(body)]


def _lexeme_evidence_update(old,new,meanings,physical=()):
    if not meanings and _evidence_labels(old)==_evidence_labels(new):return {}
    import gloss_inheritance
    if physical or any(gloss_inheritance.complex_meaning_change(a,b) for a,b in meanings):
        return dict(evidence=['corpus','independent'])
    # Classifications can change without affecting the sentence bodies.
    return dict(evidence_rows=True,evidence=['corpus','independent'] if meanings else [])


def _base_targets(body):
    base=(body.get('relation') or {}).get('base_id')
    return {base} if base else set()


def _check_new_edges(edits,lookup,references,error):
    for owner,added in edits:
        seen=set()
        pending=list(added)
        while pending:
            target=pending.pop()
            if target==owner:
                raise ValueError(error)
            if target not in seen:
                seen.add(target)
                record=lookup(target)
                if record:pending.extend(references(record['body'])-seen)


def validate_structure(db,changed,affected):
    """Validate changed rows and the selections that could have become invalid."""
    import annotations,dictionary_data,dictionary_link_changes,dictionary_organization,dictionary_relations
    import homonyms,independent_links,lexicon,morphology,morpheme_registry,word_structure
    from functools import cache

    allowed={'entries','dictionary_examples','lexemes','morphemes','morpheme_components',
             'corpus_units','unit_segments','annotation_cells','lexical_links','lexical_reviews',
             'morphology_analyses','component_links','category_classes',*independent_links.TABLES}
    if any(table not in allowed for table,_,_ in changed):return False
    native=record_sources.native(db)
    targets=set();examples=set();links=set();cells=set();components=[];groups=set()
    changed_entries=set();removed_selections=set();removed_links=set();removed_analyses=set()
    inserted_links={after['id'] for table,before,after in changed
                    if table=='lexical_links' and before is None and after}
    component_edges=[];base_edges=[]
    for table,before,after in changed:
        if table in ('entries','dictionary_examples'):
            if not _same_columns(before,after,{'body','revision'}):return False
            if before['body']!=after['body']:
                old,new=(record_sources.body(row,mutable=False) for row in (before,after))
                if old.get('language_id','')!=new.get('language_id',''):return False
            if table=='dictionary_examples':examples.add(after['id'])
        elif table in ('lexemes','morphemes'):
            if not (native and table=='lexemes' and before is None and after and trusted(db)):
                if not _same_columns(before,after,{'body','revision','headword','form','number'}):return False
                if before['body']==after['body'] and _same_columns(before,after,{'revision'}):continue
            old=record_sources.body(before,mutable=False) if before else {}
            new=record_sources.body(after,mutable=False)
            xid=after['id']
            added=word_structure.references(new)-word_structure.references(old)
            if native and table=='lexemes':
                changed_entries.add(xid)
                if dictionary_link_changes.identities(old)-dictionary_link_changes.identities(new):
                    removed_selections.add(xid)
                if added:component_edges.append((xid,added))
                bases=_base_targets(new)-_base_targets(old)
                if bases:base_edges.append((xid,bases))
            elif _target_dependencies(old,table)!=_target_dependencies(new,table) or added:
                return False
            targets.add(xid)
            if table=='lexemes':
                groups.update((row['language_id'],row['headword']) for row in (before,after) if row)
        elif table=='lexical_links':
            if before and not after:removed_links.add(before['id'])
            elif native and before is None and after:continue
            elif not _same_columns(before,after,{'revision'}):return False
        elif table in ('morphology_analyses','component_links'):
            if native and table=='morphology_analyses' and before is None and after and after['id'] in inserted_links:
                continue
            if not before or after:return False
            if table=='morphology_analyses':removed_analyses.add(before['id'])
        elif table=='category_classes':
            # Saving a word can register new POS, form and usage-tag categories.
            # An edit to an existing definition can invalidate references anywhere.
            if before or not after or after['kind'] not in ('pos','form','usage_tag'):return False
            if after['parent_id'] and not db.execute('SELECT 1 FROM category_classes WHERE id=? AND kind=? AND language_id=?',
                    (after['parent_id'],after['kind'],after['language_id'])).fetchone():return False
        elif table=='annotation_cells' and after:
            cells.add(after['id'])
        elif table=='morpheme_components' and after:
            components.append(after)
        elif table=='independent_links' and after:
            links.add(after['id'])

    if not trusted(db):
        lexicon.validate_links(db)
        return True

    @cache
    def target(xid):
        import dictionary_rows
        return dictionary_rows.targets(db,[xid],prepare=False).get(xid)

    if targets:
        owners=[target(xid) for xid in targets]
        incoming=dictionary_relations.component_owners(db,removed_selections) if removed_selections else set()
        word_structure.validate_entries(db,[*owners,*(target(xid) for xid in incoming-targets)],target)
        for owner in owners:
            morphology.validate_entry(db,owner,target)
            if owner['target_kind']=='morpheme':
                morpheme_registry.clean_variants(db,owner['language_id'],owner['body'])
            elif owner['id'] in changed_entries:
                dictionary_data.validate_writings(db,owner)
                dictionary_organization.validate_ids(db,owner['language_id'],owner['body'].get('semantic_classes',[]))
        _check_new_edges(component_edges,target,word_structure.references,'词条的组分关联不能形成循环包含')
        _check_new_edges(base_edges,target,_base_targets,'所属基本条目不能形成循环关系')
        homonyms.validate(db,(peer for lid,form in groups for peer in homonyms.group(db,lid,form)))
    if removed_selections or removed_analyses or inserted_links:
        scope=dict(links=removed_analyses|inserted_links,targets=removed_selections)
        morphology.validate_occurrences(db,target,scope)
        lexicon.validate_link_selections(db,target,scope)
    if removed_links:
        for table in ('morphology_analyses','component_links','lexical_reviews'):
            if next(lexicon.scoped_rows(db,'SELECT 1 FROM '+table,[('id',removed_links)],' LIMIT 1'),None):
                raise ValueError('解除关联后仍有依赖记录，请刷新后重试')
    independent_links.validate(db,links=links,examples=examples,targets=removed_selections)
    for row in components:
        owner,shared=target(row['lexeme_id']),target(row['morpheme_id'])
        if not owner or not shared or shared['target_kind']!='morpheme' or owner['language_id']!=shared['language_id']:
            raise ValueError('语素整理关联的词条和语素须存在且属于同一语言；删除词条前请先解除组分的语素整理关联')
        morpheme_registry.validate_component_form(json.loads(row['body']),{v['id'] for v in shared['body'].get('variants',[])})
    annotations.validate(db,cells)
    lexicon.validate_unit_references(db,affected)
    check=CURRENT.get()
    if check and check.db is db and check.finalizing:check.scoped_structure=True
    return True
