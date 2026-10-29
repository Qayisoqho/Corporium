import long_tasks
"""Stable corpus units and an evidence-linked lexicon with sense-scoped gloss updates."""
import link_review
import morpheme_registry
import synonyms
import json
import uuid
import hashlib
import re
import unicodedata
import font_catalog
import dictionary_data
import annotations
import grammar
import homonyms
import morphology
import categories
import dictionary_organization
import dictionary_search
import entry_dates
import example_numbering
import gloss_inheritance
import paradigms
from collections import Counter,defaultdict,OrderedDict
from contextvars import ContextVar
from corpus import analyze, boundary_count, clean, gloss_relations

TABLES = ('corpus_units','lexemes','lexical_links')+dictionary_data.TABLES+annotations.TABLES+grammar.TABLES+morphology.TABLES+categories.TABLES+dictionary_organization.TABLES+morpheme_registry.TABLES+synonyms.TABLES+link_review.TABLES
TAG_TYPES = ('register','region','period','generation','domain','other')
ORTHOGRAPHY_FONTS = ('Junicode','IPAPANNEW','SimSun','KaiTi','Microsoft YaHei','serif','sans-serif')
synced_entries = ContextVar('synced_entries', default=None)


def initialize(db):
    link_review.initialize(db)
    synonyms.initialize(db)
    morpheme_registry.initialize(db)
    dictionary_organization.initialize(db)
    dictionary_data.initialize(db)
    example_numbering.initialize(db)
    annotations.initialize(db)
    grammar.initialize(db)
    morphology.initialize(db)
    for r in db.execute('SELECT id,body FROM dictionary_examples').fetchall():
        b=json.loads(r['body'])
        if any(not w.get('annotation_id') for w in b.get('words',[])):
            annotations.independent_ids({},b)
            db.execute('UPDATE dictionary_examples SET body=? WHERE id=?',(json.dumps(b,ensure_ascii=False),r['id']))
    db.executescript('''
    CREATE TABLE IF NOT EXISTS corpus_units(id TEXT PRIMARY KEY,entry_id TEXT NOT NULL,kind TEXT NOT NULL,parent_id TEXT,position INTEGER NOT NULL,form TEXT NOT NULL,gloss TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,revision INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS units_entry ON corpus_units(entry_id,active,kind,position);
    CREATE INDEX IF NOT EXISTS units_parent ON corpus_units(parent_id,active,position);
    CREATE TABLE IF NOT EXISTS lexemes(id TEXT PRIMARY KEY,language_id TEXT NOT NULL,headword TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS lexemes_language ON lexemes(language_id,headword);
    CREATE TABLE IF NOT EXISTS lexical_links(id TEXT PRIMARY KEY,unit_id TEXT NOT NULL UNIQUE,lexeme_id TEXT NOT NULL,usage_id TEXT,sense_id TEXT,notes TEXT NOT NULL DEFAULT '',language_id TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS links_lexeme ON lexical_links(lexeme_id);
    ''')
    import dictionary_targets
    dictionary_targets.initialize(db)
    categories.initialize(db)
    # Only old/unindexed sentences need migration; never rewrite their original body.
    for row in db.execute('SELECT id FROM entries WHERE id NOT IN (SELECT entry_id FROM corpus_units)').fetchall():
        sync_entry(db,row['id'])
    # Rebuild changed separator analyses, preserving slot IDs and existing evidence.
    if db.execute('PRAGMA user_version').fetchone()[0]<3:
        for row in db.execute('SELECT id FROM entries').fetchall():
            sync_entry(db,row['id'])
        db.execute('PRAGMA user_version=3')

    if db.execute('PRAGMA user_version').fetchone()[0]<4:
        for row in db.execute("SELECT id FROM entries WHERE body LIKE '%~%'").fetchall():
            sync_entry(db,row['id'])
        db.execute('PRAGMA user_version=4')

def match_units(old, specs):
    """Conservative identity matching. Ambiguous changed repetitions get new IDs."""
    signature=lambda x:(x['form'],x['gloss'])
    if [signature(x) for x in old]==[signature(x) for x in specs]:
        return [r['id'] for r in old]
    old_forms=Counter(x['form'] for x in old);new_forms=Counter(x['form'] for x in specs)
    old_pairs=Counter(signature(x) for x in old);new_pairs=Counter(signature(x) for x in specs)
    by_form={x['form']:x['id'] for x in old};by_pair={signature(x):x['id'] for x in old}
    result=[]
    for x in specs:
        if old_forms[x['form']]==new_forms[x['form']]==1: result.append(by_form[x['form']])
        elif old_pairs[signature(x)]==new_pairs[signature(x)]==1: result.append(by_pair[signature(x)])
        else: result.append(str(uuid.uuid4()))
    return result


def prepare_sync(db,entry_ids,word_positions=None):
    """Bounded prefetch for an internal dictionary sync in one write transaction."""
    marks=','.join('?' for _ in entry_ids);result={eid:([],{}) for eid in entry_ids}
    if word_positions is None:
        units=db.execute('SELECT * FROM corpus_units WHERE entry_id IN ('+marks+') AND active=1 ORDER BY entry_id,position',entry_ids)
    else:
        # Every word slot is needed to verify the fixed structure. Only affected
        # slots need child units and their potentially large segment snapshots.
        selected=json.dumps({eid:list(word_positions[eid]) for eid in entry_ids})
        units=db.execute('''WITH wanted AS (SELECT key entry_id,value positions FROM json_each(?))
            SELECT u.* FROM wanted w JOIN corpus_units u ON u.entry_id=w.entry_id
            LEFT JOIN corpus_units p ON p.id=u.parent_id
            WHERE u.active=1 AND (u.kind='word' OR p.position IN (SELECT value FROM json_each(w.positions)))
            ORDER BY u.entry_id,u.position''',(selected,))
    owners={}
    for row in units:
        result[row['entry_id']][0].append(dict(row))
        if row['kind']=='morpheme':owners[row['id']]=row['entry_id']
    mids=list(owners)
    for start in range(0,len(mids),400):
        batch=mids[start:start+400]
        for row in db.execute('SELECT id,body FROM unit_segments WHERE id IN ('+','.join('?' for _ in batch)+')',batch):
            result[owners[row['id']]][1][row['id']]=row['body']
    return result


def sync_entry(db,eid,word_ids=None,morph_ids=None,preserve_complex=False,analyzed_body=None,preserve_slots=False,word_positions=None,stored_body=None,unit_state=None):
    row=db.execute('SELECT body FROM entries WHERE id=?',(eid,)).fetchone()
    if unit_state is None:
        old=[dict(r) for r in db.execute('SELECT * FROM corpus_units WHERE entry_id=? AND active=1 ORDER BY position',(eid,))]
        previous_segments={r['id']:r['body'] for r in db.execute('SELECT s.id,s.body FROM unit_segments s JOIN corpus_units u ON u.id=s.id WHERE u.entry_id=?',(eid,))}
    else:old,previous_segments=unit_state
    # Explicit slot correspondence needs no label-based identity matching.
    # During reconciliation the bindings may already describe the new source;
    # applying them to the transaction's old sentence would mix two snapshots.
    if not preserve_slots:old=gloss_inheritance.previous_units(db,eid,old)
    # A synchronous meaning/form update has just analyzed and saved this exact
    # body. Reuse it only while the stored snapshot still matches.
    if row and analyzed_body is not None and (stored_body if stored_body is not None else json.dumps(analyzed_body,ensure_ascii=False))==row['body']:
        words=analyzed_body['words']
    else:words=analyze(json.loads(row['body']))['words'] if row else []
    children=defaultdict(list)
    for unit in old:
        if unit['kind']=='morpheme':children[unit['parent_id']].append(unit)
    if preserve_slots:
        slots=[r for r in old if r['kind']=='word']
        if len(slots)!=len(words):raise ValueError('词格数量已变化，请重新核对关联后保存')
        word_ids=[r['id'] for r in slots]
        morph_ids={r['id']:[m['id'] for m in children[r['id']]] for r in slots}
        if any(len(morph_ids[r['id']])!=len(w['morphemes']) for i,(r,w) in enumerate(zip(slots,words)) if word_positions is None or i in word_positions):
            raise ValueError('语素数量已变化，请重新核对关联后保存')
    ids=word_ids if word_ids is not None else match_units([r for r in old if r['kind']=='word'],words)
    targets=[];segment_data={}
    for n,(word,uid) in enumerate(zip(words,ids)):
        # Internal boundary-preserving dictionary sync knows exactly which
        # words changed. Leave every other saved unit/snapshot intact.
        if preserve_slots and word_positions is not None and n not in word_positions:continue
        targets.append(dict(id=uid,entry_id=eid,kind='word',parent_id=None,position=n,form=word['form'],gloss=word['gloss']))
        morphs=word['morphemes']
        old_morphs=children[uid]
        mids=(morph_ids or {}).get(uid) or match_units(old_morphs,morphs)
        for j,(m,mid) in enumerate(zip(morphs,mids)):
            snapshot={k:word[k] for k in ('form','gloss')}
            previous_segment=previous_segments.get(mid)
            if previous_segment and not (preserve_complex and uid in (morph_ids or {})):
                previous_segment=json.loads(previous_segment)
                if (m.get('kind')!='simple' or previous_segment.get('kind')!='simple') and (previous_segment.get('key')!=m.get('key') or previous_segment.get('snapshot')!=snapshot or previous_segment.get('fragments')!=m.get('fragments') or previous_segment.get('kind')!=m.get('kind')):mid=str(uuid.uuid4())
            segment_data[mid]={**m,'snapshot':snapshot}
            targets.append(dict(id=mid,entry_id=eid,kind='morpheme',parent_id=uid,position=j,form=m['form'],gloss=m['gloss']))
    live={x['id'] for x in targets}
    if preserve_slots and word_positions is not None:live.update(r['id'] for r in old)
    for r in old:
        if r['id'] not in live: db.execute('UPDATE corpus_units SET active=0,revision=revision+1 WHERE id=?',(r['id'],))
    previous={x['id']:x for x in old}
    for x in targets:
        before=previous.get(x['id'])
        if before and all(before[k]==v for k,v in x.items()): continue
        db.execute('INSERT INTO corpus_units(id,entry_id,kind,parent_id,position,form,gloss) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id,position=excluded.position,form=excluded.form,gloss=excluded.gloss,active=1,revision=corpus_units.revision+1',tuple(x.values()))
    for uid,data in segment_data.items():
        encoded=json.dumps(data,ensure_ascii=False)
        if previous_segments.get(uid)==encoded:continue
        db.execute('INSERT INTO unit_segments VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body WHERE body<>excluded.body',(uid,encoded))
    if synced_entries.get() is not None:synced_entries.get()[eid]=row['body'] if row else None


def sync_changes(db, changes):
    for (table,_),(before,after) in long_tasks.steps(list(changes.items())):
        if table!='entries':continue
        eid=(after or before)['id']
        synced=synced_entries.get() or {}
        if eid in synced and synced[eid]==(after['body'] if after else None):continue
        # Metadata, sentence text and ordering do not change word/morpheme identities.
        if before and after and (before['body']==after['body'] or json.loads(before['body'])['words']==json.loads(after['body'])['words']):continue
        sync_entry(db,eid)


def association_removals_only(changes):
    """Prove only edges were removed, before derived gloss freezing.

    New/restored links (including undo) still take full reference validation.
    """
    rows=[(t,a,b) for (t,_),(a,b) in changes.items() if a!=b]
    if not rows:return False
    removed={a['id'] for t,a,b in rows if t=='lexical_links' and a and b is None}
    for table,before,after in rows:
        if table in ('lexical_links','morphology_analyses','component_links','lexical_reviews'):
            if not before or after is not None or before['id'] not in removed:return False
        elif table=='dictionary_examples' and before and after:
            if {k:v for k,v in before.items() if k not in ('body','revision')}!={k:v for k,v in after.items() if k not in ('body','revision')}:return False
            a=json.loads(before['body']);b=json.loads(after['body'])
            old=a.pop('targets',[]);new=b.pop('targets',[])
            if a!=b or len(new)>=len(old):return False
            remaining=iter(old)
            if not all(any(item==candidate for candidate in remaining) for item in new):return False
        else:return False
    return True


def validate_changes(db,changes,association_removals=False):
    changed=[(t,a,b) for (t,_),(a,b) in changes.items() if a!=b and t!='history']
    import timeline
    # Timeline identities, time ranges and catalogs have their own validators.
    # They cannot change lexical units or sense/form references. Sentence
    # renumbering is likewise safe; moving to a different text is not.
    def numbering_only(table,before,after):
        return table=='entries' and before and after and {k:v for k,v in before.items() if k not in ('position','revision')}=={k:v for k,v in after.items() if k not in ('position','revision')}
    changed=[(t,a,b) for t,a,b in changed if t not in timeline.TABLES+gloss_inheritance.TABLES and not numbering_only(t,a,b)]
    tables={t for t,_,_ in changed}
    if not tables:return
    def glossary_only(before,after,fields=('glossary',)):
        if not before or not after:return False
        a={k:v for k,v in before.items() if k not in ('revision','metadata')};b={k:v for k,v in after.items() if k not in ('revision','metadata')}
        am=json.loads(before['metadata']);bm=json.loads(after['metadata'])
        for field in fields:am.pop(field,None);bm.pop(field,None)
        return a==b and am==bm
    # Discovery preferences cannot change any formal definition or reference.
    import grammaticality
    if tables=={'languages'} and all(glossary_only(a,b,(grammaticality.KEY,)) for _,a,b in changed):
        grammaticality.validate(db,changes)
        return
    if tables<= {'entries','dictionary_examples'} and all(a and b and {k:v for k,v in a.items() if k not in ('revision','body')}=={k:v for k,v in b.items() if k not in ('revision','body')} and {k:v for k,v in json.loads(a['body']).items() if k!=grammaticality.FIELD}=={k:v for k,v in json.loads(b['body']).items() if k!=grammaticality.FIELD} for _,a,b in changed):
        grammaticality.validate(db,changes)
        return
    if tables=={'languages'} and all(glossary_only(a,b,(grammar.IGNORED,)) for _,a,b in changed):
        for _,_,b in changed:grammar.ignored_values(json.loads(b['metadata']))
        return
    # Edits preserving tag identities and additive definitions cannot invalidate
    # existing feature references. New root grammar categories add no dependency.
    # Deletions, language moves and other schema/mixed edits still use full checks.
    if tables<= {'grammar_tags','languages','category_classes'} and 'grammar_tags' in tables and all(
        (b and (a is None or a['id']==b['id'] and a['language_id']==b['language_id'])) if t=='grammar_tags' else
        (a is None and b and b['kind']=='grammar' and b['parent_id'] is None) if t=='category_classes' else glossary_only(a,b)
        for t,a,b in changed):
        grammar.validate(db)
        for t,_,b in changed:
            if t=='category_classes' and not db.execute('SELECT 1 FROM languages WHERE id=?',(b['language_id'],)).fetchone():raise ValueError('分类所属语言不存在')
        return
    affected={key:set() for key in ('targets','links','units')}
    for table,a,b in changed:
        key='targets' if table in ('lexemes','morphemes') else 'links' if table in ('lexical_links','morphology_analyses','component_links') else 'units' if table in ('corpus_units','unit_segments') else None
        if key:affected[key].update(row['id'] for row in (a,b) if row)
    if association_removals:
        # No definitions, schemas or source content changed before synchronize().
        # Its frozen labels need local checks, not another full dictionary scan.
        annotations.validate(db)
        validate_unit_references(db,affected)
        for link in affected['links']:
            for table in ('morphology_analyses','component_links','lexical_reviews'):
                if db.execute('SELECT 1 FROM '+table+' WHERE id=?',(link,)).fetchone():
                    raise ValueError('解除关联后仍有依赖记录，请刷新后重试')
        return
    if tables <= {'entries','corpus_units','unit_segments','annotation_cells'}:
        # These edits cannot alter lexeme definitions or morphology references.
        # Check the dependencies they CAN remove; retain full validation otherwise.
        annotations.validate(db)
        validate_unit_references(db,affected)
        return
    local={'lexemes','morphemes','morpheme_components','lexical_links','morphology_analyses','component_links','lexical_reviews','entries','corpus_units','unit_segments','dictionary_examples','annotation_cells'}
    # New containers/categories cannot invalidate earlier occurrence references;
    # edits/deletes to shared schemas still require an unscoped graph check.
    introduced={t for t in ('texts','category_classes') if t in tables and all(a is None and b for table,a,b in changed if table==t)}
    validate_links(db,affected if tables<=local|introduced else None)


def scoped_rows(db,sql,groups,tail=''):
    """Bound SQL parameters while looking up every affected stable identity."""
    for column,values in groups:
        values=list(values)
        for start in range(0,len(values),400):
            batch=values[start:start+400]
            for row in db.execute(sql+' WHERE '+column+' IN ('+','.join('?' for _ in batch)+')'+tail,batch):yield row


def validate_unit_references(db,affected=None):
    sql='SELECT 1 FROM lexical_links l LEFT JOIN corpus_units u ON u.id=l.unit_id'
    rows=db.execute(sql+' WHERE u.id IS NULL LIMIT 1') if affected is None else scoped_rows(db,sql,[('l.id',affected['links']),('l.unit_id',affected['units'])],' AND u.id IS NULL LIMIT 1')
    if next(iter(rows),None):raise ValueError('该操作会使已有词典关联失效；请先解除相关关联，再删除或撤销词条')


def enrich(db, items):
    if not items: return
    gloss_inheritance.prefetch(db,'corpus',[item['id'] for item in items])
    for item in items:
        gloss_inheritance.resolve(db,'corpus',item['id'],item)
    for item in items:annotations.enrich(db,item,'corpus',item['id'])
    by_entry={x['id']:x for x in items}
    units=list(db.execute('SELECT u.*,l.id link_id,l.lexeme_id FROM corpus_units u LEFT JOIN lexical_links l ON l.unit_id=u.id WHERE u.active=1 AND u.entry_id IN ('+','.join('?' for _ in items)+')',list(by_entry)))
    parents={}
    for u in units:
        if u['kind']=='word':
            word=by_entry[u['entry_id']]['words'][u['position']]
            word['unit_id']=u['id'];word['linked_lexeme']=u['lexeme_id'];parents[u['id']]=word
    for u in units:
        if u['kind']=='morpheme' and u['parent_id'] in parents:
            if u['position']>=len(parents[u['parent_id']]['morphemes']): continue
            m=parents[u['parent_id']]['morphemes'][u['position']]
            m['unit_id']=u['id'];m['linked_lexeme']=u['lexeme_id']


def tags(value):
    if not isinstance(value,list): raise ValueError('使用标签格式不正确')
    result=[]
    for t in value:
        if isinstance(t,dict) and not text(t.get('value','')).strip() and not text(t.get('note','')).strip():continue
        if not isinstance(t,dict) or not isinstance(t.get('type'),str) or not t.get('type','').strip(): raise ValueError('使用标签类型不正确')
        label=text(t.get('value','')).strip()
        if not label: raise ValueError('请填写标签内容')
        result.append({'type':t['type'],'value':label,'note':text(t.get('note',''))})
    return result


def text(value):
    if not isinstance(value,str): raise ValueError('词典字段应为文本')
    return value


def normalize(body):
    if not isinstance(body,dict): raise ValueError('词条格式不正确')
    body=discard_empty_new_rows(body)
    result={k:text(body.get(k,'')) for k in ('notes','homonym_note')}
    result['semantic_classes']=body.get('semantic_classes',[])
    result['homonym_number']=homonyms.number(body.get('homonym_number'))
    result['tags']=tags(body.get('tags',[]));result['usages']=[];result['variants']=[]
    seen=set()
    def rows(value):
        if not isinstance(value,list) or any(not isinstance(x,dict) for x in value): raise ValueError('词类、义项或变体的格式不正确')
        return value
    def identity(x):
        uid=x.get('id') or str(uuid.uuid4())
        if not isinstance(uid,str) or uid in seen: raise ValueError('词类、义项或变体的标识重复')
        seen.add(uid);return uid
    result['orthographies']=[]
    for item in rows(body.get('orthographies',[])):
        label=text(item.get('label','')).strip();value=text(item.get('text',''))
        font=item.get('font','Junicode')
        if not label or not value.strip(): raise ValueError('请填写书写形式的名称和内容，或移除空白项')
        if not font_catalog.valid_font(font): raise ValueError('请选择列表中的书写字体')
        result['orthographies'].append(dict(id=identity(item),label=label,text=value,font=font,type_id=text(item.get('type_id',''))))
    for variant in rows(body.get('variants',[])):
        form=text(variant.get('form','')).strip()
        if not form: raise ValueError('请填写变体形式，或移除空白变体')
        result['variants'].append({'id':identity(variant),'form':form,'notes':text(variant.get('notes','')),'tags':tags(variant.get('tags',[]))})
    for usage in rows(body.get('usages',[])):
        u={'id':identity(usage),'pos':text(usage.get('pos','')).strip(),'subclass':text(usage.get('subclass','')).strip(),'notes':text(usage.get('notes','')),'tags':tags(usage.get('tags',[])),'senses':[]}
        for sense in rows(usage.get('senses',[])):
            s={'id':identity(sense),'tags':tags(sense.get('tags',[]))}
            for k in ('short_gloss','definition','notes'): s[k]=text(sense.get(k,''))
            import sense_gloss
            sense_gloss.normalize(sense,s)
            if not any(s[k].strip() for k in ('short_gloss','definition','notes')) and not s.get('gloss_addition') and not s['tags'] and not sense.get('features'): raise ValueError('请填写义项内容，或移除空白义项')
            u['senses'].append(s)
        result['usages'].append(u)
    return paradigms.normalize(body,morphology.normalize(body,result))


def discard_empty_new_rows(body):
    """Drop untouched new rows before morphology pairs sources with normalized rows.

    Existing stable identities and partially filled rows still undergo validation.
    """
    body=dict(body)
    def blank(row,fields):return all(isinstance(row.get(k,''),str) and not row.get(k,'').strip() for k in fields)
    def no_tags(row):
        values=row.get('tags',[])
        return isinstance(values,list) and all(isinstance(t,dict) and blank(t,('value','note')) for t in values)
    for key in ('orthographies','variants','usages'):
        values=body.get(key,[])
        if not isinstance(values,list) or any(not isinstance(r,dict) for r in values):continue
        kept=[]
        for original in values:
            row=dict(original)
            if key=='usages':
                senses=row.get('senses',[])
                if isinstance(senses,list):
                    row['senses']=[s for s in senses if not isinstance(s,dict) or s.get('id') or not(blank(s,('short_gloss','definition','notes','gloss_addition')) and no_tags(s) and not s.get('features'))]
                empty=blank(row,('pos','subclass','notes')) and no_tags(row) and not row.get('features') and not row.get('senses')
            elif key=='variants':
                empty=blank(row,('form','notes','pronunciation','conditions','source')) and no_tags(row) and not row.get('features') and not row.get('condition_types')
            else:
                empty=blank(row,('text',)) and (bool(row.get('type_id')) or blank(row,('label',)))
            if row.get('id') or not empty:kept.append(row)
        body[key]=kept
    return body


def selection(body,usage_id,sense_id):
    if not usage_id:
        if sense_id: raise ValueError('请先选择词类用法')
        return None,None
    usage=next((x for x in body['usages'] if x['id']==usage_id),None)
    if not usage: raise ValueError('关联的词类用法已不存在，请先调整语料关联')
    sense=next((s for s in usage['senses'] if s['id']==sense_id),None) if sense_id else None
    if sense_id and sense is None:
        sense=next((s for u in paradigms.usages(body) if u['id']==usage_id for s in u['senses'] if s['id']==sense_id),None)
    if sense_id and not sense: raise ValueError('关联的义项已不存在，请先调整语料关联')
    return usage,sense


def validate_links(db,affected=None):
    if affected is None:
        import grammaticality
        grammaticality.validate(db)
    targets={r['id']:{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT * FROM dictionary_targets')}
    morpheme_registry.validate(db)
    dictionary_organization.validate(db)
    dictionary_data.validate(db,targets)
    grammar.validate(db)
    homonyms.validate(db)
    morphology.validate(db,targets,affected)
    validate_unit_references(db,affected)
    # Validate every relationship, but decode each dictionary body only once and
    # check identical meaning references once within this transaction snapshot.
    sql='SELECT DISTINCT l.lexeme_id,l.usage_id,l.sense_id,a.form_id FROM lexical_links l LEFT JOIN morphology_analyses a ON a.id=l.id'
    rows=db.execute(sql) if affected is None else scoped_rows(db,sql,[('l.id',affected['links']),('l.lexeme_id',affected['targets'])])
    for r in rows:
        target=targets.get(r['lexeme_id'])
        if target is None:
            raise ValueError('该操作会使已有词典关联失效；请先解除相关关联，再删除或撤销词条')
        selection(target['body'],r['usage_id'],r['sense_id'])
        paradigms.validate_selection(target['body'],r['usage_id'],r['sense_id'],r['form_id'])


def list_lexemes(db,lid,query='',page=1,page_size=30,ids_only=False,category='',order='',search=None,summary=False,targets=False,counts=True):
    import dictionary_paging
    dictionary_paging.paginate([],1,page_size)
    if isinstance(search,str):
        try:search=json.loads(search)
        except ValueError:raise ValueError('搜索条件格式不正确')
    if search is not None and not isinstance(search,dict):raise ValueError('搜索条件格式不正确')
    simple=not search or search=={'field':'all','case':False,'combine':'all','class_id':'','conditions':[]}
    where='';params=()
    if lid!='all':where=' WHERE x.language_id=?';params=(lid,)
    source='dictionary_targets' if targets else 'lexemes'
    sql='SELECT x.*,l.name language_name FROM '+source+' x JOIN languages l ON l.id=x.language_id'+where+" ORDER BY x.headword COLLATE NOCASE,json_extract(x.body,'$.homonym_number'),x.rowid"
    if order in entry_dates.ORDERS:
        sql=sql[:sql.index(' ORDER BY ')]+ ' ORDER BY '+entry_dates.sql_order(order,'x')
    plain=not query.strip() and simple and not category and (not order or order in entry_dates.ORDERS)
    if plain:
        total=db.execute('SELECT count(*) FROM '+source+' x'+where,params).fetchone()[0]
        size=max(1,total) if str(page_size)=='all' else int(page_size)
        pages=max(1,(total+size-1)//size);page=max(1,min(int(page),pages))
        if ids_only:return [r['id'] for r in db.execute(sql,params)]
        rows=[{**dict(r),'body':json.loads(r['body'])} for r in db.execute(sql+' LIMIT ? OFFSET ?',params+(size,(page-1)*size))]
        result=dict(items=rows,total=total,page=page,pages=pages)
    else:
        types={r['id']:r for r in db.execute('SELECT * FROM writing_types')}
        rows=[{**dict(r),'body':dictionary_data.resolve(db,json.loads(r['body']),types)} for r in db.execute(sql,params)]
    if query.strip() or not simple:
        index=dictionary_search.SearchIndex(db,lid,rows,search_spec=search or {},query=query).prepare(search or {})
        rows=[r for r in rows if index.matches(r,query)]
    if not plain:
        rows=dictionary_organization.filter_sort(db,lid,rows,category,order)
        if ids_only:return [r["id"] for r in rows]
        result=dictionary_paging.paginate(rows,page,page_size)
    # The sidebar needs no evidence bodies/counts or complete entry drafts.
    # Full API responses retain the original contract for link pickers and exports.
    if summary:
        for item in result['items']:
            b=item['body'];item['body']={k:b.get(k) for k in ('homonym_number','homonym_note')}
            item['body']['usages']=[{k:u.get(k,'') for k in ('pos','subclass')} for u in b.get('usages',[])]
    else:
        types={r['id']:r for r in db.execute('SELECT * FROM writing_types')}
        independent=Counter()
        if counts:
            for e in db.execute("SELECT body FROM dictionary_examples WHERE (?='all' OR language_id=?)",(lid,lid)):
                for xid in {t['lexeme_id'] for t in json.loads(e['body'])['targets']}:independent[xid]+=1
        for item in result['items']:
            dictionary_data.resolve(db,item['body'],types)
            if counts:item['example_count']=occurrence_count(db,item['id']);item['independent_count']=independent[item['id']]
    words=[r for r in result['items'] if r.get('target_kind')!='morpheme']
    homonyms.decorate_many(db,words)
    return result


def occurrence_count(db,lid,kind='all',form_id='all'):
    """One current semantic unit per occurrence; old links remain reviewable evidence."""
    seen=set()
    target=db.execute('SELECT language_id FROM dictionary_targets WHERE id=?',(lid,)).fetchone()
    if not target:return 0
    # Resolve one target language once. Joining the union of dictionary bodies
    # into every occurrence needlessly scans/copies the same large paradigms.
    form_column='a.form_id' if form_id!='all' else 'NULL form_id'
    form_join=' LEFT JOIN morphology_analyses a ON a.id=l.id' if form_id!='all' else ''
    sql="SELECT u.id,u.kind,u.form,u.gloss,u.parent_id,"+form_column+" FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id JOIN entries e ON e.id=u.entry_id JOIN texts t ON t.id=e.text_id"+form_join+" WHERE l.lexeme_id=? AND u.active=1 AND COALESCE(NULLIF(json_extract(e.body,'$.language_id'),''),t.language_id)=? AND (?='all' OR u.kind=?)"
    for r in db.execute(sql,(lid,target['language_id'],kind,kind)):
        if boundary_count(r['form']):continue
        if form_id!='all':
            if (r['form_id'] or 'unassigned')!=form_id:continue
        key=r['id']
        if r['kind']=='morpheme':
            parent=db.execute('SELECT * FROM corpus_units WHERE id=?',(r['parent_id'],)).fetchone()
            if parent and (parent['form'],parent['gloss'])==(r['form'],r['gloss']) and db.execute("SELECT COUNT(*) FROM corpus_units WHERE parent_id=? AND active=1",(parent['id'],)).fetchone()[0]==1:key=parent['id']
        seen.add(key)
    return len(seen)

def get_lexeme(db,lid):
    row=db.execute('SELECT x.*,l.name language_name FROM dictionary_targets x JOIN languages l ON l.id=x.language_id WHERE x.id=?',(lid,)).fetchone()
    if not row: raise ValueError('词条不存在，请刷新词典')
    value={**dict(row),'body':dictionary_data.resolve(db,json.loads(row['body']))}
    return value if value['target_kind']=='morpheme' else homonyms.decorate(db,value)


def segment_display_gloss(segment,fallback):
    snapshot=(segment or {}).get('snapshot')
    if snapshot:
        parsed=analyze({'words':[dict(snapshot)],'ipa':'','translation':''})['words'][0]
        match=next((m for m in parsed['morphemes'] if m['key']==segment.get('key')),None)
        if match:return match.get('display_gloss',match['gloss'])
    return fallback


def unit_info(db,uid):
    u=db.execute('SELECT u.*,e.revision entry_revision,e.body,e.text_id,e.position sentence_position,t.title,t.language_id FROM corpus_units u LEFT JOIN entries e ON e.id=u.entry_id LEFT JOIN texts t ON t.id=e.text_id WHERE u.id=?',(uid,)).fetchone()
    if not u: raise ValueError('词或语素不存在，请重新打开句子')
    result=dict(u)
    if u['body']:
        body=analyze(gloss_inheritance.load(db,'corpus',u['entry_id'],u['body']))
        wi=u['position'] if u['kind']=='word' else db.execute('SELECT position FROM corpus_units WHERE id=?',(u['parent_id'],)).fetchone()[0]
        word=body['words'][wi] if 0<=wi<len(body['words']) else None
        live=word if u['kind']=='word' else word['morphemes'][u['position']] if word and 0<=u['position']<len(word['morphemes']) else None
        if live:
            result['gloss']=live['gloss'];result['body']=json.dumps(body,ensure_ascii=False)
            result['gloss_sources']=word.get('gloss_sources',[]);result['gloss_revision']=body.get('gloss_revision')
    detail=db.execute('SELECT body FROM unit_segments WHERE id=?',(uid,)).fetchone()
    result['segmentation']=json.loads(detail[0]) if detail else None
    result['display_gloss']=live.get('display_gloss',result['gloss']) if u['body'] and live else segment_display_gloss(result['segmentation'],result['gloss'])
    result['unit_type']='phonological_boundary' if boundary_count(u['form']) else u['kind']
    if u['body'] and u['kind']=='word' and u['active'] and json.loads(u['body'])['words'][u['position']].get('punctuation'):result['unit_type']='punctuation'
    result['gloss_relations']=gloss_relations(result['gloss']) if not boundary_count(u['form']) else []
    result['effective_language_id']=(json.loads(u['body']).get('language_id') or u['language_id']) if u['body'] else None
    result['link']=dict(db.execute("SELECT *, 'confirmed' status FROM lexical_links WHERE unit_id=?",(uid,)).fetchone() or {})
    if result['link']:result['link'].update(morphology.analysis(db,result['link']['id']))
    if result['link'].get('component_ref'):
        result['link']['component_review']=morphology.component_links.review(get_lexeme(db,result['link']['lexeme_id'])['body'],result['link']['component_ref'])
    result['suggested_features']=morphology.suggested_features(db,result['effective_language_id'],result['gloss'])
    return result


def examples(db,lid,page=1,kind='all',form_id='all'):
    if kind not in ('all','word','morpheme'): raise ValueError('请选择全部、整词或语素例证')
    lex=get_lexeme(db,lid)
    if form_id not in ('all','unassigned'):morphology.form_selection(lex['body'],form_id)
    condition=" AND (?='all' OR EXISTS(SELECT 1 FROM morphology_analyses a WHERE a.id=l.id AND a.form_id=?) OR (?='unassigned' AND NOT EXISTS(SELECT 1 FROM morphology_analyses a WHERE a.id=l.id AND a.form_id IS NOT NULL)))"
    params=(lid,kind,kind,form_id,form_id,form_id)
    total=db.execute("SELECT COUNT(*) FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE l.lexeme_id=? AND (?='all' OR u.kind=?)"+condition,params).fetchone()[0]
    page=max(1,min(int(page),max(1,(total+19)//20)))
    result=[]
    for row in db.execute("SELECT l.*,u.entry_id,u.kind,u.active,u.form,u.gloss,u.position unit_position,COALESCE(p.position,u.position) word_position,e.body,e.text_id,e.position,t.title,t.language_id text_language FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id LEFT JOIN corpus_units p ON p.id=u.parent_id LEFT JOIN entries e ON e.id=u.entry_id LEFT JOIN texts t ON t.id=e.text_id WHERE l.lexeme_id=? AND (?='all' OR u.kind=?)"+condition+" ORDER BY u.active DESC,t.rowid,e.position,u.position,l.id LIMIT 20 OFFSET ?",(*params,(page-1)*20)):
        e=dict(row);e['status']='confirmed';e['entry']=analyze(gloss_inheritance.load(db,'corpus',row['entry_id'],e.pop('body'))) if row['body'] else None
        segment=db.execute('SELECT body FROM unit_segments WHERE id=?',(e['unit_id'],)).fetchone()
        e['display_gloss']=segment_display_gloss(json.loads(segment[0]) if segment else None,e['gloss'])
        if e['entry'] and 0<=row['word_position']<len(e['entry']['words']):
            word=e['entry']['words'][row['word_position']]
            unit=word if row['kind']=='word' else word['morphemes'][row['unit_position']] if 0<=row['unit_position']<len(word['morphemes']) else None
            if unit:e['gloss']=unit['gloss'];e['display_gloss']=unit.get('display_gloss',unit['gloss'])
        e.update(morphology.analysis(db,e['id']))
        if e['entry']:annotations.enrich(db,e['entry'],'corpus',e['entry_id'])
        effective=(e['entry'].get('language_id') or e['text_language']) if e['entry'] else None
        e['needs_review']=not e['active'] or effective!=lex['language_id'] or bool(boundary_count(e['form']))
        e['component_review']=morphology.component_links.review(lex['body'],e.get('component_ref'))
        e['review_reason']=link_review.reason(db,e['id'])
        e['needs_review']=e['needs_review'] or e['component_review'] or bool(e['review_reason'])
        result.append(e)
    reference_total=db.execute('SELECT COUNT(*) FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE l.lexeme_id=?',(lid,)).fetchone()[0]
    return {'items':result,'total':total,'reference_total':reference_total,'occurrences':occurrence_count(db,lid,kind,form_id),'page':page,'pages':max(1,(total+19)//20)}


def duplicate(db,lid,request):
    """Copy owned identities; incoming corpus references stay with the source."""
    import copy
    kind=request.get('kind')
    if kind not in ('lexeme','morpheme'):raise ValueError('请选择词条或语素')
    source=get_lexeme(db,request.get('id'))
    if source['language_id']!=lid or source['target_kind']!=kind:raise ValueError('条目不属于当前语言或类型')
    if source['revision']!=request.get('revision'):raise ValueError('条目已变化，请刷新后复制')
    if request.get('confirmed') is not True:raise ValueError('请确认建立独立副本')
    table='lexemes' if kind=='lexeme' else 'morphemes'
    data=json.loads(db.execute('SELECT body FROM '+table+' WHERE id=?',(source['id'],)).fetchone()[0]);identities={}
    def collect(value):
        if isinstance(value,list):
            for child in value:collect(child)
        elif isinstance(value,dict):
            if value.get('id'):identities.setdefault(value['id'],str(uuid.uuid4()))
            for key,child in value.items():
                if key not in ('merged_records','converted_from'):collect(child)
    collect(data)
    keys={'id','parent_id','usage_id','sense_id','form_id','variant_id','base_sense_id','default_base_sense_id','primary_sense_id','analysis_id','component_id','target_id'}
    def remap(value):
        if isinstance(value,list):return [remap(v) for v in value]
        if not isinstance(value,dict):return value
        external=value.get('lexeme_id') and value['lexeme_id']!=source['id']
        return {k:(copy.deepcopy(v) if k in ('merged_records','converted_from') else identities.get(v,v) if k in keys and isinstance(v,str) and not (external and k in ('usage_id','sense_id','form_id')) else remap(v)) for k,v in value.items()}
    data=remap(data);data['homonym_number']=None;data.pop('created_at',None)
    if kind=='lexeme':
        confirmation=homonyms.plan(db,lid,source['headword'])['token']
        result=mutate(db,'lexeme-save',dict(headword=source['headword'],body=data,homonym_confirmation=confirmation),lid)
    else:result=morpheme_registry.mutate(db,'morpheme-save',dict(form=source['headword'],body=data),lid)
    shared=set()
    for row in db.execute('SELECT * FROM morpheme_components WHERE lexeme_id=?',(source['id'],)).fetchall():
        old=json.loads(row['body']);value=remap(old)
        if 'form_id' in old:value['form_id']=old['form_id']
        db.execute('INSERT INTO morpheme_components VALUES(?,?,?,?,?,?,1)',(str(uuid.uuid4()),result['id'],identities.get(row['analysis_id'],row['analysis_id']),identities.get(row['component_id'],row['component_id']),row['morpheme_id'],json.dumps(value,ensure_ascii=False)))
        shared.add(row['morpheme_id'])
    for mid in shared:db.execute('UPDATE morphemes SET revision=revision+1 WHERE id=?',(mid,))
    for row in db.execute('SELECT * FROM object_media WHERE kind=? AND record_id=?',(kind,source['id'])).fetchall():
        db.execute('INSERT INTO object_media VALUES(?,?,?,?,?,?,?,1)',(str(uuid.uuid4()),lid,kind,result['id'],row['asset_id'],json.dumps(remap(json.loads(row['body'])),ensure_ascii=False),row['position']))
    import synonyms
    for row in db.execute('SELECT * FROM synonym_links WHERE language_id=?',(lid,)).fetchall():
        ends=json.loads(row['body']);changed=False
        for end in ends:
            if end.get('kind')==kind and end.get('id')==source['id']:
                end['id']=result['id'];end['sense']=identities.get(end['sense'],end['sense']);changed=True
        if changed:
            ends.sort(key=synonyms.key)
            db.execute('INSERT INTO synonym_links VALUES(?,?,?,?,?)',(str(uuid.uuid4()),lid,*map(synonyms.key,ends),json.dumps(ends,ensure_ascii=False)))
    return get_lexeme(db,result['id'])


def mutate(db,action,body,lid):
    if action=='lexeme-auto-link':
        plan=auto_link_plan(db,lid,body.get('text_id',''),body.get('ignore_symbols','-=.'),body.get('ignore_position','edges'))
        if body.get('token')!=plan['token']: raise ValueError('匹配结果已变化，请重新预览后关联')
        items=plan['matches']
        if body.get('mode','strict')=='candidates':
            selected=body.get('selected',[])
            if not isinstance(selected,list) or not selected or any(not isinstance(v,str) for v in selected) or len(set(selected))!=len(selected):raise ValueError('请勾选有效的候选')
            available={r['candidate_id']:r for r in plan['suggestions']}
            if any(v not in available for v in selected):raise ValueError('候选已变化，请重新预览')
            items=[available[v] for v in selected]
            if len({r['unit_id'] for r in items})!=len(items):raise ValueError('同一处语料只能选择一组词条、义项和形式')
        elif body.get('mode','strict')!='strict':raise ValueError('关联模式无效')
        import multipart_forms
        occupied=set()
        for item in items:
            coverage=set(item.get('coverage',[]))
            if coverage&occupied:raise ValueError('所选候选共用了片段，请为每个片段选择一种组合或关联')
            occupied.update(coverage)
        for item in long_tasks.steps(items):
            if item.get('multipart_group'):
                multipart_forms.apply(db,item,lid)
                continue
            if item.get('owner_kind')=='independent':
                row=db.execute('SELECT body FROM dictionary_examples WHERE id=?',(item['entry_id'],)).fetchone()
                data=json.loads(row['body'])
                data.setdefault('targets',[]).append(dict(lexeme_id=item['lexeme_id'],usage_id=item['usage_id'],sense_id=item['sense_id'],form_id=item.get('form_id'),features=[],notes=item['match_reason'],segmentation_ref=item['segmentation_ref']))
                db.execute('UPDATE dictionary_examples SET body=?,revision=revision+1 WHERE id=?',(json.dumps(data,ensure_ascii=False),item['entry_id']))
                continue
            link_id=str(uuid.uuid4())
            db.execute('INSERT INTO lexical_links(id,unit_id,lexeme_id,usage_id,sense_id,notes,language_id,revision) VALUES(?,?,?,?,?,?,?,1)',(link_id,item['unit_id'],item['lexeme_id'],item['usage_id'],item['sense_id'],item['match_reason'],lid))
            if item.get('form_id'):morphology.set_analysis(db,link_id,{'form_id':item['form_id']},get_lexeme(db,item['lexeme_id']))
        return {'ok':True,'count':len(items)}
    if action=='lexeme-save':
        headword=text(body.get('headword','')).strip()
        if not headword: raise ValueError('请填写词形')
        xid=body.get('id')
        old=get_lexeme(db,xid) if xid else None
        if old and old['target_kind']=='morpheme':raise ValueError('请在语素列表中编辑此记录')
        import multipart_forms,dictionary_link_changes
        link_fingerprint=dictionary_link_changes.token(db,old,body) if old else None
        data=normalize(multipart_forms.align_spellings(body.get('body',{}),headword,old,'headword'))
        categories.register_usages(db,lid,data,True)
        if old and 'form_parts' not in body.get('body',{}) and old['body'].get('form_parts'):
            data['form_parts']=old['body']['form_parts']
        headword,parts=multipart_forms.realization(headword,data)
        if parts:data['form_parts']=parts
        entry_dates.stamp(data,old['body'] if old else None)
        if old and 'semantic_classes' not in body.get('body',{}):data['semantic_classes']=old['body'].get('semantic_classes',[])
        dictionary_organization.validate_ids(db,lid,data['semantic_classes'])
        if old and 'word_structure' not in body.get('body',{}):data['word_structure']=old['body'].get('word_structure',{'memberships':[],'analyses':[]})
        if old and 'paradigms' not in body.get('body',{}) and old['body'].get('paradigms'):
            data['paradigms']=old['body']['paradigms']
            paradigms.normalize(data,data)
        if old and old['revision']!=body.get('revision'):raise ValueError('词条已修改，请重新打开后编辑')
        homonyms.prepare(db,lid,headword,data,old,body.get('homonym_confirmation'))
        registry_plan=None
        if 'morpheme_confirmation' in body:
            registry_plan=morpheme_registry.save_plan(db,lid,xid,data,body.get('morpheme_assignments'))
            if registry_plan['token']!=body['morpheme_confirmation']:raise ValueError('语素或组分已变化，请再次保存并核对同形语素')
        if xid:
            old=get_lexeme(db,xid)
            if old['revision']!=body.get('revision'): raise ValueError('词条已修改，请重新打开后编辑')
            dictionary_link_changes.apply(db,old,data,body,link_fingerprint)
            db.execute('UPDATE lexemes SET headword=?,body=?,revision=revision+1 WHERE id=?',(headword,json.dumps(data,ensure_ascii=False),xid))
            if old['headword']!=headword:homonyms.clear_singleton(db,lid,old['headword'])
        else:
            xid=str(uuid.uuid4())
            db.execute('INSERT INTO lexemes(id,language_id,headword,body) VALUES(?,?,?,?)',(xid,lid,headword,json.dumps(data,ensure_ascii=False)))
        result=get_lexeme(db,xid)
        if registry_plan is not None:morpheme_registry.apply_save_plan(db,result,lid,registry_plan,body.get('morpheme_choices',[]))
        return get_lexeme(db,xid)
    if action=='lexeme-delete':
        old=get_lexeme(db,body['id'])
        if old['target_kind']=='morpheme':raise ValueError('请在语素列表中删除此记录')
        if body.get('confirmed') is not True: raise ValueError('请确认删除词条')
        if old['revision']!=body.get('revision'): raise ValueError('词条已修改，请刷新后删除')
        if db.execute('SELECT 1 FROM lexical_links WHERE lexeme_id=?',(old['id'],)).fetchone():
            raise ValueError('词条仍有关联例证，请先解除关联再删除')
        homonyms.prepare(db,lid,old['headword'],old['body'],old,None)
        db.execute('DELETE FROM lexemes WHERE id=?',(old['id'],));return {'ok':True}
    if action=='lexeme-unlink':
        items=body.get('items',[body])
        if not isinstance(items,list) or not 1<=len(items)<=100:raise ValueError('请选择本页要解除的关联')
        if any(not isinstance(item,dict) or not isinstance(item.get('id'),str) for item in items):raise ValueError('关联记录格式不正确')
        if len({item['id'] for item in items})!=len(items):raise ValueError('请勿重复选择同一关联')
        rows=[]
        for item in items:
            old=db.execute('SELECT * FROM lexical_links WHERE id=?',(item['id'],)).fetchone()
            if not old or old['revision']!=item.get('revision'):raise ValueError('关联已变化，请刷新后重试')
            if old['language_id']!=lid or body.get('lexeme_id',old['lexeme_id'])!=old['lexeme_id']:raise ValueError('词条或语言范围已变化，请重新打开后操作')
            rows.append(old)
        for table in ('component_links','lexical_reviews','morphology_analyses','lexical_links'):
            db.executemany('DELETE FROM '+table+' WHERE id=?',[(r['id'],) for r in rows])
        return {'ok':True,'count':len(rows)}
    if action=='dictionary-examples-unlink':
        target=get_lexeme(db,body.get('lexeme_id'))
        if target['language_id']!=lid:raise ValueError('语言范围已变化，请重新打开后操作')
        items=body.get('items')
        if not isinstance(items,list) or not 1<=len(items)<=20 or any(not isinstance(i,dict) or not isinstance(i.get('id'),str) for i in items):raise ValueError('请选择本页要解除的例句')
        if len({i['id'] for i in items})!=len(items):raise ValueError('请勿重复选择同一例句')
        updates=[]
        for item in items:
            row=db.execute('SELECT * FROM dictionary_examples WHERE id=?',(item['id'],)).fetchone()
            if not row or row['revision']!=item.get('revision'):raise ValueError('例句关联已变化，请刷新后重试')
            if row['language_id']!=lid:raise ValueError('例句所属语言不一致')
            data=json.loads(row['body']);before=data['targets'];form=body.get('form_id','all')
            data['targets']=[t for t in before if not (t['lexeme_id']==target['id'] and (form=='all' or (not t.get('form_id') if form=='unassigned' else t.get('form_id')==form)))]
            if len(before)==len(data['targets']):raise ValueError('例句关联已变化，请刷新后重试')
            updates.append((json.dumps(data,ensure_ascii=False),row['id']))
        db.executemany('UPDATE dictionary_examples SET body=?,revision=revision+1 WHERE id=?',updates)
        return {'ok':True,'count':len(updates)}
    if action=='lexeme-link':
        u=unit_info(db,body['unit_id'])
        if u['unit_type'] in ('phonological_boundary','punctuation'): raise ValueError('音系单位边界或标点不能关联为词或语素')
        if not u['active'] or not u['body']: raise ValueError('这个词或语素已重新切分，请从当前句子重新选择')
        if u['revision']!=body.get('unit_revision') or u['entry_revision']!=body.get('entry_revision'): raise ValueError('句子已变化，请重新打开词语关联窗口')
        old=u['link']
        if body.get('revision',0)!=old.get('revision',0): raise ValueError('关联已变化，请重新打开')
        lex=get_lexeme(db,body['lexeme_id'])
        if lex['revision']!=body.get('lexeme_revision'): raise ValueError('词条已修改，请重新选择词条')
        if lex['language_id']!=u['effective_language_id']: raise ValueError('词条语言须与句子的实际语言一致')
        usage,sense=selection(lex['body'],body.get('usage_id') or None,body.get('sense_id') or None)
        xid=old.get('id') or str(uuid.uuid4())
        db.execute('INSERT INTO lexical_links(id,unit_id,lexeme_id,usage_id,sense_id,notes,language_id,revision) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET lexeme_id=excluded.lexeme_id,usage_id=excluded.usage_id,sense_id=excluded.sense_id,notes=excluded.notes,revision=excluded.revision',
                   (xid,u['id'],lex['id'],usage['id'] if usage else None,sense['id'] if sense else None,text(body.get('notes','')),lid,old.get('revision',0)+1))
        # Older clients that only edit an existing link must not erase its analysis.
        previous=morphology.analysis(db,xid) if old.get('lexeme_id')==lex['id'] else {'component_ref':None}
        if body.get('component_selection') and u['kind']!='morpheme':raise ValueError('请先选择例句中的语素，再关联词条组分')
        morphology.set_analysis(db,xid,{**previous,**{k:v for k,v in body.items() if k!='component_ref'}},lex)
        db.execute('DELETE FROM lexical_reviews WHERE id=?',(xid,))
        return {'ok':True,'id':xid}
    raise ValueError('未知词典操作')


def export_bundle(db,lid,stream=False):
    links=[dict(r) for r in db.execute("SELECT *, 'confirmed' status FROM lexical_links WHERE language_id=?",(lid,))]
    import streaming_json
    units=streaming_json.UnitMap(db,lid) if stream else {r['id']:gloss_inheritance.export_unit(db,r) for r in db.execute('SELECT u.* FROM corpus_units u JOIN entries e ON e.id=u.entry_id JOIN texts t ON t.id=e.text_id WHERE t.language_id=?',(lid,))}
    for link in links:
        long_tasks.checkpoint(None,'正在整理词典及语料关联…')
        if link['unit_id'] in units:continue
        u=dict(db.execute('SELECT * FROM corpus_units WHERE id=?',(link['unit_id'],)).fetchone())
        units[u['id']]=gloss_inheritance.export_unit(db,u) if not stream else u
        if u['parent_id'] and u['parent_id'] not in units:
            parent=db.execute('SELECT * FROM corpus_units WHERE id=?',(u['parent_id'],)).fetchone()
            if parent: units[parent['id']]=gloss_inheritance.export_unit(db,parent) if not stream else dict(parent)
    rows={r['id']:dict(r) for r in db.execute('SELECT * FROM dictionary_targets WHERE language_id=?',(lid,))}
    for link in links:
        if link['lexeme_id'] in rows:continue
        r=db.execute('SELECT * FROM dictionary_targets WHERE id=?',(link['lexeme_id'],)).fetchone()
        rows[r['id']]=dict(r)
    extras=[{**gloss_inheritance.export_body(db,'independent',e),'library_number':e['library_number']} for e in gloss_inheritance.iter_rows(db,db.execute('SELECT d.*,n.number library_number FROM dictionary_examples d JOIN example_numbers n ON n.id=d.id AND n.language_id=d.language_id WHERE d.language_id=? ORDER BY n.ordering',(lid,)),'independent')]
    for e in extras:
        for target in json.loads(e['body'])['targets']:
            if target['lexeme_id'] in rows:continue
            r=db.execute('SELECT * FROM dictionary_targets WHERE id=?',(target['lexeme_id'],)).fetchone()
            rows[r['id']]=dict(r)
    # Include the complete base-entry chain for cross-language referenced entries.
    pending=list(rows.values())
    while pending:
        body=json.loads(pending.pop()['body']);relation=body.get('relation')
        refs=morphology.word_structure.references(body)|({relation['base_id']} if relation else set())
        for ref in refs-rows.keys():
            base=db.execute('SELECT * FROM dictionary_targets WHERE id=?',(ref,)).fetchone()
            if not base:raise ValueError('形态关系缺少基本条目')
            rows[base['id']]=dict(base);pending.append(dict(base))
    languages={lid}|{r['language_id'] for r in rows.values()}
    types=[dict(t) for t in db.execute('SELECT * FROM writing_types') if t['language_id'] in languages]
    entry_ids={r[0] for r in db.execute('SELECT DISTINCT entry_id FROM exchange_units')} if stream else {u['entry_id'] for u in units.values()}
    example_ids={e['id'] for e in extras}
    cells=[dict(c) for c in db.execute('SELECT * FROM annotation_cells') if (c['owner_kind']=='corpus' and c['record_id'] in entry_ids) or (c['owner_kind']=='independent' and c['record_id'] in example_ids)]
    layer_ids={c['layer_id'] for c in cells}
    layer_defs=[dict(l) for l in db.execute('SELECT * FROM annotation_layers') if l['language_id']==lid or l['id'] in layer_ids]
    tag_languages=languages|{l['language_id'] for l in layer_defs}
    tag_languages|={json.loads(r[0]).get('language_id') or lid for r in db.execute('SELECT e.body FROM entries e JOIN texts t ON t.id=e.text_id WHERE t.language_id=?',(lid,))}
    link_ids={l['id'] for l in links}
    analyses=[dict(r) for r in db.execute('SELECT * FROM morphology_analyses') if r['id'] in link_ids]
    segments=streaming_json.Rows(db,'SELECT s.* FROM unit_segments s JOIN exchange_units u ON u.id=s.id',transform=lambda r:gloss_inheritance.export_segment(db,r)) if stream else [gloss_inheritance.export_segment(db,r) for r in db.execute('SELECT * FROM unit_segments') if r['id'] in units]
    return {'example_number_next':example_numbering.export_next(db,lid),'gloss_overrides':gloss_inheritance.export_overrides(db,lid),**{t:[dict(r) for r in db.execute('SELECT * FROM '+t) if r['language_id'] in tag_languages] for t in dictionary_organization.TABLES},**morpheme_registry.export_bundle(db,languages,rows),'synonym_links':synonyms.export_bundle(db,languages),'lexicon_version':13,'lexical_reviews':[dict(r) for r in db.execute('SELECT * FROM lexical_reviews') if r['id'] in link_ids],'component_links':[dict(r) for r in db.execute('SELECT * FROM component_links') if r['id'] in link_ids],'category_classes':[c for c in categories.listing(db) if c['language_id'] in tag_languages],'lexemes':[{k:v for k,v in r.items() if k not in ('target_kind','rowid')} for r in rows.values() if r['target_kind']=='lexeme'],'corpus_units':units.values() if stream else list(units.values()),'lexical_links':links,'morphology_analyses':analyses,'unit_segments':segments,'writing_types':types,'dictionary_examples':extras,'annotation_layers':layer_defs,'annotation_cells':cells,'grammar_tags':[r for r in grammar.listing(db) if r['language_id'] in tag_languages]}


def import_bundle(db,bundle,language_map,entry_map,lid,layouts=None):
    if layouts is None:
        layouts={}
        for target in language_map.values():
            meta=json.loads(db.execute('SELECT metadata FROM languages WHERE id=?',(target,)).fetchone()[0])
            if meta.get('dictionary_layout') and not db.execute('SELECT 1 FROM lexemes WHERE language_id=?',(target,)).fetchone():layouts[target]=meta['dictionary_layout']
    semantic_map=dictionary_organization.import_bundle(db,bundle,language_map)
    classmap=categories.import_bundle(db,bundle,language_map)
    tagmap=grammar.import_bundle(db,bundle,language_map)
    def remap_features(data):
        try:data['features']=[tagmap[t] for t in data.get('features',[])]
        except KeyError:raise ValueError('形态分析缺少语法标签定义')
    relations={};structures={};linkmap={}
    xmap={};submap={};umap={r['id']:str(uuid.uuid4()) for r in bundle.get('corpus_units',[])}
    type_map={}
    for t in long_tasks.steps(bundle.get('writing_types',[])):
        target_language=language_map[t['language_id']]
        name=t['name'];n=1
        while db.execute('SELECT 1 FROM writing_types WHERE language_id=? AND name=?',(target_language,name)).fetchone():
            n+=1;name=t['name']+'（导入 '+str(n)+'）'
        new=dictionary_data.mutate(db,'writing-save',dict(name=name,font=t['font'],position=t['position']),target_language)
        type_map[t['id']]=new['id']
    for x in long_tasks.steps(bundle.get('lexemes',[])):
        if x['language_id'] not in language_map: raise ValueError('词典缺少引用语言的信息')
        data=normalize(json.loads(x['body']))
        try:data['semantic_classes']=[semantic_map[i] for i in data['semantic_classes']]
        except KeyError:raise ValueError('词条缺少语义分类定义')
        structures[x['id']]=data.pop('word_structure',{})
        relations[x['id']]=data.pop('relation',None)
        remap_features(data)
        for part in long_tasks.steps([*data['variants'],*data['usages'],*(s for u in data['usages'] for s in u['senses'])]):remap_features(part)
        for o in long_tasks.steps(data['orthographies']):
            if o.get('type_id'):o['type_id']=type_map[o['type_id']]
        for part in long_tasks.steps([*data['orthographies'],*data['variants'],*data['usages'],*(s for u in data['usages'] for s in u['senses'])]):
            old=part['id'];part['id']=str(uuid.uuid4());submap[(x['id'],old)]=part['id']
        paradigms.remap(data,x['id'],submap)
        target_language=language_map[x['language_id']]
        peer_plan=homonyms.plan(db,target_language,x['headword'])
        if data.get('homonym_number') in {p['number'] for p in peer_plan['peers']}:data['homonym_number']=None
        created=mutate(db,'lexeme-save',{'headword':x['headword'],'body':data,'homonym_confirmation':peer_plan['token']},target_language)
        entry_dates.imported(db,'lexemes',created['id'],json.loads(x['body']))
        xmap[x['id']]=created['id']
    mmap=morpheme_registry.import_bundle(db,bundle,language_map,xmap,submap,classmap,type_map,tagmap,include_components=False,semantic_map=semantic_map)
    xmap.update(mmap)
    for record in bundle.get('morphemes',[]):
        value=json.loads(record['body']);relations[record['id']]=value.get('relation');structures[record['id']]=value.get('word_structure',{})
    for old,relation in long_tasks.steps(relations.items()):
        if not relation:continue
        if relation['base_id'] not in xmap:raise ValueError('形态关系缺少所属基本条目')
        x=get_lexeme(db,xmap[old]);x['body']['relation']={**relation,'base_id':xmap[relation['base_id']]}
        db.execute('UPDATE '+('morphemes' if x['target_kind']=='morpheme' else 'lexemes')+' SET body=? WHERE id=?',(json.dumps(x['body'],ensure_ascii=False),x['id']))
    for old,structure in long_tasks.steps(structures.items()):
        x=get_lexeme(db,xmap[old]);x['body']['word_structure']=morphology.word_structure.remap(structure,old,xmap,submap,classmap,type_map,tagmap)
        db.execute('UPDATE '+('morphemes' if x['target_kind']=='morpheme' else 'lexemes')+' SET body=? WHERE id=?',(json.dumps(x['body'],ensure_ascii=False),x['id']))
    missing_entries={}
    for u in long_tasks.steps(bundle.get('corpus_units',[])):
        if u['kind'] not in ('word','morpheme') or not isinstance(u['position'],int): raise ValueError('词或语素引用格式不正确')
        eid=entry_map.get(u['entry_id']) or missing_entries.setdefault(u['entry_id'],str(uuid.uuid4()))
        if u['parent_id'] and u['parent_id'] not in umap: raise ValueError('语素缺少所属词的引用')
        db.execute('INSERT INTO corpus_units(id,entry_id,kind,parent_id,position,form,gloss,active) VALUES(?,?,?,?,?,?,?,?)',(umap[u['id']],eid,u['kind'],umap.get(u['parent_id']),u['position'],text(u['form']),text(u['gloss']),int(bool(u['active']) and u['entry_id'] in entry_map)))
    for segment in long_tasks.steps(bundle.get('unit_segments',[])):
        if segment['id'] not in umap:raise ValueError('形态片段缺少所属语素')
        data=json.loads(segment['body'])
        if not isinstance(data,dict):raise ValueError('形态片段数据无效')
        db.execute('INSERT INTO unit_segments VALUES(?,?)',(umap[segment['id']],json.dumps(data,ensure_ascii=False)))
    for l in long_tasks.steps(bundle.get('lexical_links',[])):
        if l['unit_id'] not in umap or l['lexeme_id'] not in xmap: raise ValueError('用例关联缺少词条或语料单位')
        linkmap[l['id']]=(str(uuid.uuid4()),l['lexeme_id'])
        db.execute('INSERT INTO lexical_links(id,unit_id,lexeme_id,usage_id,sense_id,notes,language_id,revision) VALUES(?,?,?,?,?,?,?,1)',(linkmap[l['id']][0],umap[l['unit_id']],xmap[l['lexeme_id']],submap[(l['lexeme_id'],l['usage_id'])] if l['usage_id'] else None,submap[(l['lexeme_id'],l['sense_id'])] if l['sense_id'] else None,text(l['notes']),lid))
    for r in long_tasks.steps(bundle.get('lexical_reviews',[])):
        if r['id'] not in linkmap:raise ValueError('待核对记录缺少词典关联')
        db.execute('INSERT INTO lexical_reviews VALUES(?,?)',(linkmap[r['id']][0],text(r['reason'])))
    for a in long_tasks.steps(bundle.get('morphology_analyses',[])):
        if a['id'] not in linkmap:raise ValueError('形态分析缺少用例关联')
        newlink,oldlex=linkmap[a['id']];data={'features':json.loads(a['features'])}
        remap_features(data)
        if a.get('form_id'):
            if (oldlex,a['form_id']) not in submap:raise ValueError('形态分析缺少形式记录')
            data['form_id']=submap[(oldlex,a['form_id'])]
        morphology.set_analysis(db,newlink,data,get_lexeme(db,xmap[oldlex]))
    for r in long_tasks.steps(bundle.get('component_links',[])):
        if r['id'] not in linkmap:raise ValueError('组分关联缺少词典关联')
        newlink,oldlex=linkmap[r['id']]
        ref=morphology.component_links.remap(json.loads(r['body']),oldlex,xmap,submap,classmap,type_map,tagmap)
        morphology.component_links.write(db,newlink,ref)
    emap={};independent_units={}
    imported_examples=example_numbering.import_examples(bundle)
    for e in long_tasks.steps(imported_examples):
        data=json.loads(e['body'])
        for t in long_tasks.steps(data['targets']):
            old=t['lexeme_id'];t['lexeme_id']=xmap[old]
            remap_features(t)
            if t.get('component_ref'):t['component_ref']=morphology.component_links.remap(t['component_ref'],old,xmap,submap,classmap,type_map,tagmap)
            for key in long_tasks.steps(('usage_id','sense_id','form_id')):
                if t.get(key):t[key]=submap[(old,t[key])]
        target_language=language_map[e['language_id']]
        if 'library_number' in e:example_numbering.prepare_import(db,target_language,e['library_number'])
        created=dictionary_data.mutate(db,'example-save',dict(body=data),target_language);emap[e['id']]=created['id']
        for a,b in long_tasks.steps(zip(data.get('words',[]),created['body']['words'])):
            if a.get('annotation_id'):independent_units[a['annotation_id']]=b['annotation_id']
    if bundle.get('example_number_next') is not None:example_numbering.advance(db,lid,bundle['example_number_next'])
    lmap={}
    for l in long_tasks.steps(bundle.get('annotation_layers',[])):
        new=annotations.mutate(db,'layer-save',{k:v for k,v in l.items() if k not in ('id','revision')},language_map[l['language_id']]);lmap[l['id']]=new['id']
    for c in long_tasks.steps(bundle.get('annotation_cells',[])):
        if c['owner_kind']=='corpus':
            rid=entry_map.get(c['record_id']) or missing_entries.get(c['record_id']);uid=umap.get(c['unit_id'])
        else:
            rid=emap.get(c['record_id']);uid=independent_units.setdefault(c['unit_id'],str(uuid.uuid4()))
        if c['unit_id']==annotations.SENTENCE:uid=annotations.SENTENCE
        if not rid or not uid or c['layer_id'] not in lmap:raise ValueError('附加标注缺少所属例句、词或标注层')
        db.execute('INSERT INTO annotation_cells VALUES(?,?,?,?,?,?,1)',(str(uuid.uuid4()),c['owner_kind'],rid,uid,lmap[c['layer_id']],text(c['value'])))
    morpheme_registry.import_components(db,bundle,xmap,mmap,submap,classmap,type_map,tagmap)
    import dictionary_layout
    dictionary_layout.remap_import(db,layouts,semantic_map,classmap,xmap)
    synonyms.import_bundle(db,bundle,language_map,xmap,mmap,submap)
    gloss_inheritance.import_overrides(db,bundle,entry_map,emap,umap,independent_units,linkmap)
    validate_links(db)
    return {'writing_types':type_map,'examples':emap,'lexemes':xmap,'morphemes':mmap,'subparts':submap,'units':umap,'independent_units':independent_units}


def auto_gloss_key(value,lookup,features=()):
    """Only a trailing run of registered, ordinary tags is an unordered bundle.

    Complex structures remain ordered and opaque. Never flatten affixes, infixes,
    relational arguments or bracketed groups into inherent features.
    """
    value=re.sub(r'[;:\\]', '.', value)
    if any(c in value for c in '-=+<>[](){}'):
        return ('structured',value,tuple(sorted(set(features))))
    parts=value.split('.')
    tags=[]
    while parts and parts[-1].casefold() in lookup:
        tags.append(lookup[parts.pop().casefold()])
    # Deduplicate inherited declarations, not repeated tags in the actual gloss.
    tags.extend(f for f in set(features) if f not in tags)
    return ('ordinary', '.'.join(parts), tuple(sorted(tags)))


def morpheme_citation_match(kind,source,spelling):
    """Citation-edge markers are not part of an explicitly segmented surface unit."""
    if kind!='morpheme':return False
    key=lambda value:unicodedata.normalize('NFC',value).strip('-=.')
    return bool(key(source)) and key(source)==key(spelling)


def auto_link_plan(db,lid,text_id='',ignore_symbols='-=.',ignore_position='edges'):
    """Canonically equivalent forms plus complete gloss/features, scoped by language."""
    if not db.execute('SELECT 1 FROM languages WHERE id=?',(lid,)).fetchone():
        raise ValueError('请先选择一个语言，再批量关联')
    if text_id and text_id!='@independent' and not db.execute('SELECT 1 FROM texts WHERE id=? AND language_id=?',(text_id,lid)).fetchone():
        raise ValueError('文本不属于当前语言，请重新选择')
    if not isinstance(ignore_symbols,str) or any(c not in '-=.' for c in ignore_symbols) or ignore_position not in ('edges','all'):raise ValueError('忽略词形标记的设置无效')
    ignore_symbols=''.join(c for c in '-=.' if c in ignore_symbols)
    # Compare equivalent Unicode spellings (e.g. ǰ and j + combining caron)
    # without rewriting source forms, segmentation references or dictionary data.
    def form_key(value):return unicodedata.normalize('NFC',value)
    def stripped(value):
        value=form_key(value)
        return (value.strip(ignore_symbols) if ignore_position=='edges' else value.translate(str.maketrans('', '', ignore_symbols))) if ignore_symbols else value
    import multipart_forms
    multipart_catalog=multipart_forms.Catalog()
    multipart_suggestions=[];multipart_warnings=[]
    index={};relaxed={}
    tag_rows=grammar.listing(db)
    tag_names={t['id']:t['symbol'] for t in tag_rows}
    lookups={}
    for t in tag_rows:
        for name in [t['symbol'],*t['aliases']]:lookups.setdefault(t['language_id'],{})[name.casefold()]=t['id']
    def catalog():
        cursor=db.execute('SELECT * FROM dictionary_targets ORDER BY id')
        while batch:=cursor.fetchmany(200):
            items=[{**dict(x),'body':json.loads(x['body'])} for x in batch]
            homonyms.decorate_many(db,[x for x in items if x['target_kind']=='lexeme'])
            yield from items
    for x in catalog():
        xb=x['body']
        labels={(u['id'],s['id']):f'{ui}.{si}' for ui,u in enumerate(paradigms.usages(xb),1) for si,s in enumerate(u['senses'],1)}
        for u,s,form in paradigms.matching_candidates(xb,x['headword'],lambda gloss,features:auto_gloss_key(gloss,lookups.get(x['language_id'],{}),features)):
            if not s['short_gloss']:continue
            features=list(dict.fromkeys([*xb.get('features',[]),*u.get('features',[]),*s.get('features',[]),*(form.get('features',[]) if form else [])]))
            spelling=form['form'] if form else x['headword']
            key=(x['language_id'],form_key(spelling),auto_gloss_key(s['short_gloss'],lookups.get(x['language_id'],{}),features))
            reason='词形一致；简短释义「'+s['short_gloss']+'」'+('＋固有特征 '+', '.join(tag_names[f] for f in features) if features else '')+' 完整匹配'
            if form:reason+='；使用已登记形式「'+spelling+'」'
            index.setdefault(key,[]).append(dict(target_kind=x['target_kind'],lexeme_id=x['id'],lexeme_revision=x['revision'],headword=x['headword'],homonym_number=xb.get('homonym_number'),usage_id=u['id'],pos=u['pos'],sense_id=s['id'],form_id=form['id'] if form else None,match_reason=reason,matched_form=spelling,short_gloss=s['short_gloss'],sense_label=labels[(u['id'],s['id'])],definition=s.get('definition','')))
            parts=multipart_forms.forms(form or xb,spelling)
            if parts:
                candidate=index[key][-1]
                multipart_catalog.add(x['language_id'],key[2],parts,candidate,xb)
                alias=(key[0],form_key(multipart_forms.lookup(parts)),key[2])
                if alias!=key:index.setdefault(alias,[]).append(candidate)
            normalized=stripped(spelling)
            if normalized:relaxed.setdefault((key[0],normalized,key[2]),[]).append(index[key][-1])
    matches=[];ambiguous=[];suggestions=[];linked=0
    duplicates={}
    def source_rows():
        cursor=db.execute("SELECT e.id,e.revision entry_revision,e.body,e.position sentence_position,t.title FROM entries e JOIN texts t ON t.id=e.text_id WHERE t.language_id=? AND (?='' OR t.id=?) ORDER BY t.id,e.position",(lid,text_id,text_id))
        while batch:=cursor.fetchmany(200):
            grouped=defaultdict(list)
            # Read only matching inputs, once per bounded batch, in the same
            # per-sentence order as the original individual unit queries.
            for u in db.execute("SELECT u.id,u.entry_id,u.revision,u.kind,u.parent_id,u.position,u.form,u.gloss,l.id link_id FROM corpus_units u LEFT JOIN lexical_links l ON l.unit_id=u.id WHERE u.active=1 AND u.entry_id IN ("+','.join('?' for _ in batch)+') ORDER BY u.entry_id,u.kind DESC,u.position,u.id',[e['id'] for e in batch]):grouped[u['entry_id']].append(dict(u))
            for entry in batch:
                long_tasks.checkpoint(None,'正在逐句匹配词典…')
                body=json.loads(entry['body']);units=grouped[entry['id']]
                parents={u['id']:u for u in units if u['kind']=='word'}
                # Stored unit labels are flattened for identity/indexing. Recover
                # scripted glosses and discontinuous infix hosts from the source,
                # only for affected words; keep the ordinary scan and IDs intact.
                semantic={}
                for parent in parents.values():
                    word=body['words'][parent['position']]
                    if '<' in word['form'] or '#' in word['gloss']:
                        semantic[parent['id']]=analyze(dict(ipa='',translation='',words=[dict(word)]))['words'][0].get('morphemes',[])
                def meaning(u):
                    if u['kind']=='word':return clean(u['form']),u['gloss']
                    morphs=semantic.get(u['parent_id'],[])
                    m=morphs[u['position']] if u['kind']=='morpheme' and u['position']<len(morphs) else {}
                    return m.get('lookup_form',u['form']),m.get('display_gloss',u['gloss'])
                duplicates.clear()
                duplicates.update({u['parent_id']:u for u in units if u['kind']=='morpheme' and u['parent_id'] in parents and meaning(u)==meaning(parents[u['parent_id']])})
                metadata={k:entry[k] for k in ('entry_revision','sentence_position','title')}
                if multipart_catalog:
                    proposed,notes=multipart_forms.proposal_rows(db,'corpus',entry['id'],body,units,multipart_catalog,lid,
                        lambda lang,g:auto_gloss_key(g,lookups.get(lang,{})),metadata)
                    multipart_suggestions.extend(proposed);multipart_warnings.extend(notes)
                for u in units:
                    match_form,match_gloss=meaning(u)
                    yield {**u,**metadata,'body_data':body,'match_form':match_form,'match_gloss':match_gloss}
        duplicates.clear()
        if text_id in ('','@independent'):
            import segmentation
            for number,example in enumerate(db.execute('SELECT * FROM dictionary_examples WHERE language_id=? ORDER BY rowid',(lid,)),1):
                data=analyze(json.loads(example['body']))
                if multipart_catalog:
                    proposed,notes=multipart_forms.proposal_rows(db,'independent',example['id'],data,[],multipart_catalog,lid,
                        lambda lang,g:auto_gloss_key(g,lookups.get(lang,{})),dict(entry_revision=example['revision'],sentence_position=number,title='独立例句库'))
                    multipart_suggestions.extend(proposed);multipart_warnings.extend(notes)
                for wi,w in enumerate(data['words']):
                    if w.get('punctuation') or boundary_count(w['form']):continue
                    lookup_form=w.get('analysis_form',w['form'])
                    units=[dict(key='@word',form=w['form'],lookup_form=lookup_form,gloss=w['gloss'],fragments=[])]
                    word_keys={'@word'}
                    if not w.get('infix_ambiguous') and not w.get('group_reviews'):
                        for u in w.get('morphemes',[]):
                            if (u.get('lookup_form',u['form']),u.get('display_gloss',u['gloss']))==(lookup_form,w['gloss']):word_keys.add(u['key'])
                            else:units.append(u)
                    for unit in units:
                        ref=segmentation.reference(w,wi,unit)
                        keys=word_keys if unit['key']=='@word' else {unit['key']}
                        linked_here=any(t.get('segmentation_ref',{}).get('word')==wi and t.get('segmentation_ref',{}).get('key') in keys and not t.get('segmentation_ref',{}).get('detached') for t in data.get('targets',[]))
                        extra={'coverage':[f'independent:{example["id"]}:{wi}:'+k for k in unit.get('members',[unit['key']])]} if multipart_catalog and unit['key']!='@word' else {}
                        yield dict(id='independent:'+example['id']+':'+str(wi)+':'+unit['key'],entry_id=example['id'],entry_revision=example['revision'],revision=example['revision'],kind='word' if unit['key']=='@word' else 'morpheme',parent_id=None,position=wi,form=unit['form'],gloss=unit['gloss'],match_form=unit.get('lookup_form',unit['form']),match_gloss=unit.get('display_gloss',unit['gloss']),body_data=data,sentence_position=number,title='独立例句库',link_id=linked_here,owner_kind='independent',segmentation_ref=ref,**extra)
    choices=OrderedDict();choice_bytes=0
    def matching(effective,form,gloss):
        nonlocal choice_bytes
        key=(effective,form,gloss);saved=choices.get(key)
        if saved is not None:choices.move_to_end(key);return saved[:2]
        if boundary_count(form):return [],[]
        gloss_key=auto_gloss_key(gloss,lookups.get(effective,{}))
        candidates=index.get((effective,form_key(form),gloss_key),[])
        identity=lambda c:(c['lexeme_id'],c['usage_id'],c['sense_id'],c['form_id'])
        exact_ids={identity(c) for c in candidates}
        normalized=stripped(form) if ignore_symbols else ''
        possible=[c for c in relaxed.get((effective,normalized,gloss_key),[]) if identity(c) not in exact_ids] if normalized else []
        if not possible:
            # Multiple exact forms of one sense still permit a sense-only link.
            # With marked alternatives, retain each actual form for selection;
            # collapsing them could invent a primary-form candidate identity.
            grouped={}
            for c in candidates:
                key_sense=(c['lexeme_id'],c['usage_id'],c['sense_id'])
                if key_sense in grouped:
                    grouped[key_sense]={**grouped[key_sense],'form_id':None,'match_reason':'词形与完整标注唯一匹配此义项；具体形式有多个候选，未细分形式'}
                else:grouped[key_sense]=c
            candidates=list(grouped.values())
        size=256+4*sum(map(len,key))+64*(len(candidates)+len(possible))
        if size<=4*1024**2:
            while choices and (len(choices)>=4096 or choice_bytes+size>4*1024**2):choice_bytes-=choices.popitem(last=False)[1][2]
            choices[key]=(candidates,possible,size);choice_bytes+=size
        return candidates,possible
    for r in source_rows():
        body=r.get('body_data')
        if body is None:body=json.loads(r['body'])
        if r['kind']=='word' and body['words'][r['position']].get('punctuation'): continue
        if r['kind']=='morpheme' and r['parent_id'] in duplicates: continue
        effective=body.get('language_id') or lid
        candidates,possible=matching(effective,r.get('match_form',r['form']),r.get('match_gloss',r['gloss']))
        if not candidates and not possible: continue
        if r['link_id'] or duplicates.get(r['id'],{}).get('link_id'):
            linked+=1;continue
        item={k:r[k] for k in ('entry_id','entry_revision','kind','form','gloss','title','sentence_position')}
        item.update(unit_id=r['id'],unit_revision=r['revision'],effective_language_id=effective)
        if r.get('coverage'):item['coverage']=r['coverage']
        if r.get('owner_kind'):item.update(owner_kind=r['owner_kind'],segmentation_ref=r['segmentation_ref'])
        if possible:
            # Exact forms must not hide eligible marked alternatives, or be
            # applied by the strict batch button while those remain unresolved.
            match_form=r.get('match_form',r['form'])
            for c,is_relaxed in [(c,False) for c in candidates]+[(c,True) for c in possible]:
                candidate={**item,**c,'normalized_form':stripped(match_form)}
                candidate['default_selected']=len(candidates)+len(possible)==1
                if is_relaxed:
                    removed=''.join(ch for ch in ignore_symbols if c['matched_form'].count(ch)>stripped(c['matched_form']).count(ch) or match_form.count(ch)>stripped(match_form).count(ch))
                    candidate['match_reason']='忽略标记 '+removed+'（'+('仅首尾' if ignore_position=='edges' else '包含内部')+'）：词典「'+c['matched_form']+'」与语料「'+r['form']+'」均为「'+stripped(match_form)+'」；简短释义与适用特征完整匹配，须人工确认'
                else:candidate['match_reason']+='；另有忽略标记的候选，请核对选择'
                candidate['candidate_id']=hashlib.sha256(json.dumps([r['id'],c['lexeme_id'],c['usage_id'],c['sense_id'],c['form_id']],ensure_ascii=False).encode()).hexdigest()
                suggestions.append(candidate)
            continue
        if not candidates:continue
        if len(candidates)==1: matches.append({**item,**candidates[0]})
        else: ambiguous.append({**item,'candidates':candidates})
    multipart_forms.finish_plan(matches,ambiguous,suggestions,multipart_suggestions)
    payload=dict(language_id=lid,text_id=text_id,matches=matches,ambiguous=ambiguous,already_linked=linked,suggestions=suggestions,ignore_symbols=ignore_symbols,ignore_position=ignore_position)
    if multipart_warnings:payload['multipart_warnings']=multipart_warnings
    # Keep the exact canonical token while letting the native JSON encoder
    # handle each occurrence. Never allocate a second full preview document.
    digest=hashlib.sha256();encoder=json.JSONEncoder(sort_keys=True,ensure_ascii=False)
    digest.update(b'{')
    for i,key in enumerate(sorted(payload)):
        if i:digest.update(b', ')
        digest.update(encoder.encode(key).encode());digest.update(b': ');value=payload[key]
        if isinstance(value,list):
            digest.update(b'[')
            for n,item in enumerate(value):
                if n:digest.update(b', ')
                digest.update(encoder.encode(item).encode())
            digest.update(b']')
        else:digest.update(encoder.encode(value).encode())
    digest.update(b'}')
    payload['token']=digest.hexdigest()
    return payload
