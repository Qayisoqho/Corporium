"""Preview first. Convert only exactly reconstructable paradigm labels; keep sense IDs."""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import sys
import uuid
from contextlib import closing

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import paradigms


def split_label(label,base):
    if label==base:return ''
    if label.startswith(base+'.'):
        extra=label[len(base)+1:]
        try:
            if paradigms.compose(base,extra)==label:return extra
        except ValueError:pass
    return None


def plan(row):
    body=json.loads(row['body']) if isinstance(row['body'],str) else row['body']
    b=copy.deepcopy(body);changes=[];added=[];skipped=[]
    usages={u['id']:u for u in b.get('usages',[])}
    for table in b.get('paradigms',[]):
        usage=usages[table['usage_id']];senses=usage['senses']
        pending=[m for r in table['rows'] for f in r['realizations'] for m in f['meanings'] if m.get('gloss_mode','independent')=='independent' and m.get('short_gloss','').strip()]
        if not pending:continue
        # A single explicitly existing meaning and a common whole-atom prefix
        # permit an extra shared base WITHOUT changing the original citation sense.
        if len(senses)==1:
            labels=[senses[0].get('short_gloss',''),*(m['short_gloss'] for m in pending)]
            prefix=labels[0].split('.')
            for label in labels[1:]:
                parts=label.split('.');n=0
                while n<min(len(parts),len(prefix)) and parts[n]==prefix[n]:n+=1
                prefix=prefix[:n]
            common='.'.join(prefix)
            if common and common!=labels[0] and all(split_label(label,common) is not None for label in labels):
                sense=dict(id=str(uuid.uuid4()),short_gloss=common,definition=senses[0].get('definition',''),notes='',tags=[],features=[])
                senses.append(sense);added.append(dict(table=table['title'],sense_id=sense['id'],short_gloss=common))
        for m in pending:
            candidates=[(s,split_label(m['short_gloss'],s.get('short_gloss',''))) for s in senses if s.get('short_gloss') and (not m.get('base_sense_id') or s['id']==m['base_sense_id'])]
            candidates=[(s,extra) for s,extra in candidates if extra is not None]
            if not candidates and len(senses)==2 and added and senses[-1]['id']==added[-1]['sense_id']:
                extra=split_label(m['short_gloss'],senses[-1]['short_gloss'])
                if extra is not None:candidates=[(senses[-1],extra)]
            if len(candidates)!=1:
                skipped.append(dict(sense_id=m['id'],label=m['short_gloss'],reason='无法唯一确定基本义项'));continue
            base,extra=candidates[0];before=m['short_gloss']
            m.update(gloss_mode='inherit',base_sense_id=base['id'],gloss_addition=extra,short_gloss='')
            assert paradigms.effective_gloss(b,table,m)==before
            changes.append(dict(table=table['title'],sense_id=m['id'],before=before,base=base['short_gloss'],addition=extra,after=before))
        inherited=[m for r in table['rows'] for f in r['realizations'] for m in f['meanings']]
        bases={m.get('base_sense_id') for m in inherited if m.get('gloss_mode')=='inherit'}
        if len(bases)==1 and all(m.get('gloss_mode')=='inherit' for m in inherited):table['default_base_sense_id']=next(iter(bases))
        for r in table['rows']:
            extras={m['gloss_addition'] for f in r['realizations'] for m in f['meanings'] if m.get('gloss_mode')=='inherit'}
            if len(extras)==1 and all(m.get('gloss_mode')=='inherit' for f in r['realizations'] for m in f['meanings']):r['gloss_addition']=next(iter(extras))
    # All old meanings, including citation meanings, must retain their exact labels.
    before={(u['id'],s['id']):s.get('short_gloss','') for u in paradigms.usages(body) for s in u['senses']}
    after={(u['id'],s['id']):s.get('short_gloss','') for u in paradigms.usages(b) for s in u['senses']}
    assert all(after[k]==v for k,v in before.items())
    return b,dict(id=row['id'],headword=row.get('headword',row.get('form','')),changes=changes,added_bases=added,skipped=skipped)


def run(path,apply=False):
    path=Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        planned=[(dict(r),*plan(dict(r))) for r in db.execute('SELECT * FROM lexemes') if json.loads(r['body']).get('paradigms')]
    result=dict(database=str(path),applied=apply,entries=[r for old,b,r in planned],backup=None)
    changed=[(old,b,r) for old,b,r in planned if r['changes']]
    if not apply or not changed:return result
    import server,journal,lexicon
    # This script is deliberately opt-in; it never initializes or upgrades a project.
    backup=path.parent/'backups'/('before-paradigm-inheritance-'+uuid.uuid4().hex+'.sqlite3')
    backup.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup)) as dst:src.backup(dst)
    result['backup']=str(backup)
    original=server.DB
    try:
        server.DB=path
        for lid in dict.fromkeys(old['language_id'] for old,b,r in changed):
            a=journal.action.set('精简变形表标注');s=journal.scope.set(lid)
            try:
                with server.connect() as db:
                    for old,b,r in changed:
                        if old['language_id']!=lid:continue
                        current=db.execute('SELECT revision,body FROM lexemes WHERE id=?',(old['id'],)).fetchone()
                        if not current or current['revision']!=old['revision'] or current['body']!=old['body']:raise ValueError('词条在预览后已修改，请重新迁移')
                        lexicon.mutate(db,'lexeme-save',dict(id=old['id'],revision=old['revision'],headword=old['headword'],body=b),lid)
            finally:journal.scope.reset(s);journal.action.reset(a)
    finally:server.DB=original
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('database',type=Path);p.add_argument('--apply',action='store_true');p.add_argument('--report',type=Path);args=p.parse_args()
    result=run(args.database,args.apply);raw=json.dumps(result,ensure_ascii=False,indent=2)
    if args.report:args.report.write_text(raw,encoding='utf-8')
    print(raw)
