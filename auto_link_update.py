"""Submit the reviewed dictionary matches and continue from the committed snapshot."""
from collections import defaultdict
from functools import lru_cache
import json
import logging
import uuid

import long_tasks
import record_sources
import replacement_preview


STALE = '匹配结果已变化，请重新预览后关联'


def independent_value(item):
    return dict(lexeme_id=item['lexeme_id'],usage_id=item['usage_id'],sense_id=item['sense_id'],
                form_id=item.get('form_id'),features=[],notes='',segmentation_ref=item['segmentation_ref'])


def append_independent(db,items):
    """Batch isolated links whose reviewed unit and source still agree."""
    import gloss_inheritance as gloss
    import independent_links
    import save_validation
    from independent_annotations import has_frozen_sql

    grouped=defaultdict(list)
    for item in items:grouped[item['entry_id']].append(item)
    if not save_validation.trusted(db) or not record_sources.native(db):
        for item in long_tasks.steps(items):
            independent_links.replace(db,item['entry_id'],None,independent_value(item))
        return
    frozen=has_frozen_sql(db,nonempty=True)

    @lru_cache(maxsize=512)
    def pattern(label,meaning):return gloss.pattern(label,meaning)

    ids=list(grouped)
    revisions={}
    for start in long_tasks.steps(range(0,len(ids),400)):
        owners=ids[start:start+400]
        slots={};requested=[];next_positions={}
        for rid in owners:
            refs=[item['segmentation_ref'] for item in grouped[rid]]
            if len({ref['word'] for ref in refs})==len(refs):
                requested.extend((rid,ref['word'],item['lexeme_id'],item['usage_id'],item['sense_id'])
                                 for item,ref in zip(grouped[rid],refs))
        for offset in range(0,len(requested),400):
            batch=requested[offset:offset+400]
            values=','.join('(?,?,?,?,?)' for _ in batch)
            for row in db.execute(f"""WITH selected(example_id,position,target_id,usage_id,sense_id) AS (VALUES {values})
              SELECT k.example_id,k.position,w.form,w.gloss,w.extra,i.word_id,m.id meaning_id,m.gloss meaning,
                b.unit_key prior_key,b.source_hash prior_hash,b.mode prior_mode,
                (SELECT count(*) FROM gloss_bindings p WHERE p.owner_kind='independent' AND p.owner_id=k.example_id
                 AND p.word_id=i.word_id) prior_bindings,
                (SELECT count(*) FROM independent_links l WHERE l.example_id=k.example_id AND l.word_position=k.position) prior_links,
                p.gloss prior_meaning,b.pattern prior_pattern,
                (SELECT COALESCE(max(position),-1)+1 FROM independent_links WHERE example_id=k.example_id) next_position
              FROM selected k CROSS JOIN independent_words i ON i.example_id=k.example_id AND i.position=k.position
              JOIN sentence_word_rows w ON w.kind='independent' AND w.owner_id=k.example_id AND w.position=k.position
              LEFT JOIN gloss_meanings m ON m.target_id=k.target_id AND m.usage_id=k.usage_id AND m.sense_id=k.sense_id
              LEFT JOIN independent_links l ON l.example_id=k.example_id AND l.word_position=k.position AND l.unit_key='@word'
              LEFT JOIN gloss_bindings b ON b.id=l.payload->>'$.gloss_binding_id'
                AND b.owner_kind='independent' AND b.owner_id=k.example_id AND b.word_id=i.word_id
              LEFT JOIN gloss_meanings p ON p.id=b.meaning_id
              WHERE i.word_id IS w.extra->>'$.annotation_id'
                  AND NOT {frozen}
              AND NOT EXISTS (SELECT 1 FROM independent_word_overrides o WHERE o.example_id=k.example_id AND o.position=k.position)""",
              [part for slot in batch for part in slot]):
                slots[row['example_id'],row['position']]=row
                next_positions[row['example_id']]=row['next_position']
        links=[];bindings=[];counts={}
        for rid in owners:
            checked=[]
            for item in grouped[rid]:
                ref=item['segmentation_ref'];slot=slots.get((rid,ref['word']))
                if slot is None or (slot['form'],slot['gloss'])!=(ref['form'],ref['gloss']):break
                value=independent_value(item);binding=None
                if slot['word_id'] is not None and slot['meaning_id'] is not None:
                    word=dict(json.loads(slot['extra']),form=slot['form'],gloss=slot['gloss'])
                    fingerprint=gloss.source_hash(word)
                    # An existing whole-word provider that reproduces
                    # the raw gloss leaves this simple segment's template intact.
                    if (slot['prior_links'] or slot['prior_bindings']) and not (
                            slot['prior_links']==slot['prior_bindings']==1 and slot['prior_key']=='@word' and
                            slot['prior_mode']=='inherit' and slot['prior_hash']==fingerprint and
                            slot['prior_meaning'] is not None and ref['key']!='@word' and not word.get('morph_groups') and
                            not any(mark in word['form']+word['gloss'] for mark in '<>#\\[]~') and
                            gloss.value(dict(mode='inherit',meaning_gloss=slot['prior_meaning'],pattern=slot['prior_pattern']))==ref['gloss']):break
                    bid=str(uuid.uuid4());value['gloss_binding_id']=bid
                    recipe=pattern if len(ref['unit_gloss'])+len(slot['meaning'])<8192 else gloss.pattern
                    binding=(bid,rid,slot['word_id'],ref['key'],slot['meaning_id'],recipe(ref['unit_gloss'],slot['meaning']),fingerprint)
                elif slot['prior_links'] or slot['prior_bindings']:break
                checked.append((value,binding))
            else:
                for offset,(value,binding) in enumerate(checked):
                    if binding:bindings.append(binding)
                    links.append((rid,next_positions[rid]+offset,value))
                counts[rid]=len(checked)
                continue
            for item in grouped[rid]:independent_links.replace(db,rid,None,independent_value(item))
        independent_links.put_many(db,links,append=True)
        db.executemany('''INSERT INTO gloss_bindings(id,owner_kind,owner_id,word_id,unit_key,meaning_id,mode,pattern,source_hash,revision)
                       VALUES(?,'independent',?,?,?,?,'inherit',?,?,1)''',bindings)
        revisions.update(counts)
        # The same guarded query checked every slot in counts, including those
        # whose dictionary target has no inherited-label row.
        direct=getattr(db,'auto_independent_appends',None)
        if direct is None:db.auto_independent_appends=direct=set()
        direct.update(f'{rid}:{position}' for rid,position,_ in links)
    record_sources.bump_example_revisions(db,revisions)


def apply(db,body,lid):
    import auto_match_index
    import lexicon

    options=lexicon.auto_match_options(body.get('text_id',''),body.get('ignore_symbols','-=.'),body.get('ignore_position','edges'))
    cached=replacement_preview.reuse(db,'auto-match',lid,body,options,stale=STALE)
    plan=cached[0] if cached is not None else lexicon.auto_link_plan(db,lid,*options,prepare_index=auto_match_index.available(db))
    if body.get('token')!=plan['token']:raise ValueError(STALE)
    items=plan['matches']
    if body.get('mode','strict')=='candidates':
        selected=body.get('selected')
        if not isinstance(selected,list) or not selected or any(not isinstance(v,str) for v in selected) or len(set(selected))!=len(selected):
            raise ValueError('请勾选有效的候选')
        available={row['candidate_id']:row for row in plan['suggestions']}
        if not set(selected)<=available.keys():raise ValueError('候选已变化，请重新预览')
        items=[available[key] for key in selected]
        if len({row['unit_id'] for row in items})!=len(items):raise ValueError('同一处语料只能选择一组词条、义项和形式')
    elif body.get('mode','strict')!='strict':raise ValueError('关联模式无效')

    from contextlib import nullcontext
    from read_views import association_batch

    if len(items)>=10000:db.execute('PRAGMA cache_size=-196608')
    # Small saves keep their precise invalidation. Large batches publish the
    # affected view tokens once and keep per-owner projection queues active.
    context=association_batch(db) if len(items)>=400 else nullcontext()
    with context:
        return write_items(db,body,lid,options,plan,items)


def write_items(db,body,lid,options,plan,items):
    import lexicon
    import morphology
    import multipart_forms

    occupied=set()
    for item in long_tasks.steps(items):
        coverage=set(item.get('coverage',()))
        if coverage&occupied:raise ValueError('所选候选共用了片段，请为每个片段选择一种组合或关联')
        occupied.update(coverage)

    @lru_cache(maxsize=512)
    def lexeme(xid):return lexicon.get_lexeme(db,xid)

    pending=[];independent=[]
    appended={}
    def flush():
        if not pending:return
        db.executemany('''INSERT INTO lexical_links(id,unit_id,lexeme_id,usage_id,sense_id,notes,language_id,revision)
                        VALUES(?,?,?,?,?,'',?,1)''',((link,row['unit_id'],row['lexeme_id'],row['usage_id'],row['sense_id'],lid)
                            for link,row in long_tasks.steps(pending)))
        for link,row in long_tasks.steps(pending):
            if row['form_id']:morphology.set_analysis(db,link,{'form_id':row['form_id']},lexeme(row['lexeme_id']))
            appended.setdefault(row['entry_id'],set()).add(link)
        pending.clear()

    for item in long_tasks.steps(items):
        if item.get('multipart_group'):
            flush()
            if independent:append_independent(db,independent);independent.clear()
            multipart_forms.apply(db,item,lid)
        elif item.get('owner_kind')=='independent':
            flush();independent.append(item)
        else:
            if independent:append_independent(db,independent);independent.clear()
            pending.append((str(uuid.uuid4()),item))
            if len(pending)==400:flush()
    flush()
    if independent:append_independent(db,independent)
    if not any(row.get('multipart_group') for row in items):
        db.auto_word_appends=appended
    if body.get('reuse_preview') is True:
        db.auto_link_applied=(plan,options,items)
    return dict(ok=True,count=len(items))


def unchanged_match_source(before,after):
    from auto_match_sources import WORD_INPUTS

    if not before or not after or any(before.get(key)!=after.get(key) for key in ('id','text_id','position','language_id')):
        return False
    if record_sources.same_body(before['body'],after['body']):return True
    old,new=(record_sources.body(row,mutable=False) for row in (before,after))
    keys=('form','gloss',*WORD_INPUTS)
    return (old.get('language_id')==new.get('language_id') and len(old['words'])==len(new['words']) and
            all(all(a.get(key)==b.get(key) for key in keys) for a,b in zip(old['words'],new['words'])))


def retain_matches(plan,items,changes):
    if plan.get('multipart_warnings') or any(row.get('multipart_group') for row in plan['suggestions']):
        return None
    occupied={row['unit_id'] for row in items}
    revisions={}
    for (table,_),(before,after) in changes.items():
        if before==after or table in ('history','gloss_bindings'):continue
        if table in ('entries','dictionary_examples') and unchanged_match_source(before,after):
            kind='corpus' if table=='entries' else 'independent'
            revisions[kind,after['id']]=after['revision']
        elif table in ('lexical_links','independent_links','morphology_analyses') and before is None and after:
            continue
        else:
            return None

    def retain(rows):
        kept=[]
        for row in rows:
            if row['unit_id'] in occupied:continue
            kind=row.get('owner_kind','corpus')
            revision=revisions.get((kind,row['entry_id']))
            if revision is not None:
                row={**row,'entry_revision':revision}
                if kind=='independent':row['unit_revision']=revision
            kept.append(row)
        return kept

    return {**plan,'token':None,'already_linked':plan['already_linked']+len(items),
            **{key:retain(plan[key]) for key in ('matches','ambiguous','suggestions')}}


class Continuation:
    def __init__(self,body):
        self.resume=None
        self.view=None
        self.base=body.get('_view_revision')
        visible=body.get('_visible_corpus')
        self.visible=visible if isinstance(visible,list) and len(visible)<=100 and all(isinstance(rid,str) for rid in visible) else None

    def begin(self, db):
        import journal
        import save_validation

        self.matches_base=(self.visible is not None and isinstance(self.base,str) and len(self.base)==64 and
                           save_validation.trusted(db) and journal.workspace_revision(db)==self.base)

    def finish(self, db, changes):
        import journal

        self.resume=getattr(db,'auto_link_applied',None)
        if self.resume:
            plan,options,items=self.resume
            self.remaining=retain_matches(plan,items,changes)
            self.lid=journal.scope.get()
            self.path=db.execute('PRAGMA database_list').fetchone()['file']
            self.stamp=replacement_preview.snapshot(db)
            if self.matches_base and self.remaining is not None and all(not item.get('owner_kind') for item in items):
                affected={item['entry_id'] for item in items}
                self.view=(journal.workspace_revision(db),[rid for rid in self.visible if rid in affected])

    def attach(self, result):
        if not self.resume:return
        import lexicon
        import server

        _,options,_=self.resume
        try:
            with server.connect(path=self.path,audit=False) as db:
                db.execute('BEGIN')
                if self.stamp is not None and replacement_preview.snapshot(db)!=self.stamp:
                    raise ValueError(STALE)
                if self.stamp is not None and self.remaining is not None:
                    if not replacement_preview.store(db,'auto-match',self.lid,self.remaining,None,options):
                        lexicon.sign_auto_plan(self.remaining)
                else:
                    self.remaining=lexicon.auto_link_plan(db,self.lid,*options,review=True,prepare_index=True)
                result['remaining_plan']=self.remaining
                if self.view is not None and self.stamp is not None:
                    self.attach_view(db,result)
        except ValueError as error:
            result['preview_error']=str(error)
        except Exception:
            logging.exception('Could not refresh committed dictionary matches')
            result['preview_error']=STALE

    def attach_view(self,db,result):
        import corpus_search
        import journal

        current,ids=self.view
        if journal.workspace_revision(db)!=current:return
        try:
            records=corpus_search.saved_cards(db,ids,batched=True)
        except Exception:
            logging.exception('Could not load saved dictionary links for visible sentences')
            return
        history=dict(journal.state(db,self.lid),workspace_revision=current)
        result['_view_update']=dict(base=self.base,current=current,records=records,history=history)
