"""Reuse a reviewed replacement preview while its SQLite snapshot still agrees."""
import logging
from os import stat
from secrets import token_urlsafe
from sys import getsizeof

from read_views import Cache


REPLACEMENT_LIMIT = 24 * 1024**2
CACHE = Cache(64 * 1024**2)
AUTO_MATCH_CACHE = Cache(96 * 1024**2)
CONTINUED = 'remaining-'
REVIEWED = 'reviewed-'
STALE = '待替换列表已变化，请重新预览'


def snapshot(db):
    import analysis_workspace
    import record_sources
    import save_validation

    if not record_sources.native(db):
        return None
    path = db.execute('PRAGMA database_list').fetchone()['file']
    proof = save_validation.state(db)
    schema = db.execute('PRAGMA main.schema_version').fetchone()[0]
    if not path or not proof or proof['rules'] != save_validation.RULES_VERSION or proof['checked_schema'] != schema:
        return None
    try:
        file = stat(path)
    except OSError:
        return None
    # Epoch guards also catch source writes made outside the app.
    return (path, file.st_dev, file.st_ino, schema, proof['signature'], proof['epoch'], analysis_workspace.version(db))


def size(value, limit):
    seen=set()
    pending=[value];total=0
    while pending and total<=limit:
        item=pending.pop();identity=id(item)
        if identity in seen:continue
        seen.add(identity);total+=getsizeof(item)
        if isinstance(item,dict):
            pending.extend(item.keys());pending.extend(item.values())
        elif isinstance(item,(list,tuple)):
            pending.extend(item)
    return total


def remember(db, module, lid, plan, rows, options):
    ids = {match['id'] for match in plan['changes']}
    records = [row for row in rows if row['id'] in ids]
    return store(db, module, lid, plan, records, options)


def store(db, module, lid, plan, records, options):
    stamp = snapshot(db)
    if not stamp:
        return False
    data = (plan, records, options)
    # Keep a reviewed language batch within its own bounded cache.
    cache=AUTO_MATCH_CACHE if module=='auto-match' else CACHE
    limit = cache.limit if module == 'auto-match' else REPLACEMENT_LIMIT
    cost = size(data, limit)
    if cost > limit:
        return False
    if plan.get('token') is None:
        plan['token'] = REVIEWED + token_urlsafe(24)
    cache.put((stamp, module, lid, plan['token']), data, cost)
    return True


def latest_auto_match(db,lid,options):
    stamp=snapshot(db)
    if stamp:
        with AUTO_MATCH_CACHE.lock:
            for key in reversed(AUTO_MATCH_CACHE.items):
                if key[:3]==(stamp,'auto-match',lid):
                    plan,_,saved=AUTO_MATCH_CACHE.items[key][0]
                    if saved==options:return plan
    return None


def reuse(db, module, lid, body, options, *, stale=STALE):
    token = body.get('token')
    if not isinstance(token, str):
        return None
    stamp = snapshot(db) if body.get('reuse_preview') is True else None
    cache=AUTO_MATCH_CACHE if module=='auto-match' else CACHE
    data = cache.get((stamp, module, lid, token)) if stamp else None
    if data is not None and data[2] == options:
        return data
    if token.startswith((CONTINUED, REVIEWED)):
        raise ValueError(stale)
    # Full preview tokens still support the original scope revalidation.
    return None


def needs_confirmation(body, cached, plan, issues):
    if not issues:
        return False
    if body.get('confirm_conflicts') is not True:
        return True
    if body.get('confirm_preview') is not True:
        return False
    return cached is None or len(plan['changes']) != 1 or issues != plan.get('conflicts')


def track_owner(db, body, kind, selected):
    if body.get('reuse_preview') is not True or len(selected) != 1:
        return
    owner = next(iter(selected))
    code = code_profile(db, kind, owner) if kind in ('corpus', 'independent') else None
    db.replacement_owner = (kind, owner, code)


def code_profile(db, kind, owner):
    row = db.execute('SELECT * FROM code_sentence_index WHERE owner_kind=? AND record_id=?', (kind, owner)).fetchone()
    return tuple(row) if row else None


def schedule(db, body, plan, rows, options, remaining, *, reviewed=False):
    if body.get('reuse_preview') is not True:
        return
    if remaining:
        ids = {match['id'] for match in plan['changes'] if match['key'] in remaining}
        db.replacement_resume = (plan, [row for row in rows if row['id'] in ids], options, reviewed)


class Continuation:
    """Prepare the remaining reviewed matches after the write has committed."""

    def __init__(self, operation, body):
        self.operation = operation
        self.body = body
        self.resume = None
        self.view = None
        self.matches_base = False

    def begin(self, db):
        import journal
        import save_validation

        base = self.body.get('_view_revision')
        self.matches_base = (isinstance(base, str) and len(base) == 64 and
                             save_validation.trusted(db) and journal.workspace_revision(db) == base)

    def finish(self, db, changes):
        import journal
        from save_validation import ViewUpdate

        owner = getattr(db, 'replacement_owner', None)
        tables = {'corpus': 'entries', 'independent': 'dictionary_examples', 'lexeme': 'lexemes'}
        if self.matches_base and owner and owner[0] in tables:
            kind, rid, prior_code = owner
            self.view = ViewUpdate(tables[kind], kind, rid, self.body['_view_revision'], matches_base=True)
            self.view.finish(db, changes)
            if self.view.receipt is not None:
                if kind == 'lexeme' and 'record' not in self.view.receipt:
                    import lexicon
                    self.view.receipt['record'] = lexicon.get_lexeme(db, rid)
                elif kind != 'lexeme' and 'record' in self.view.receipt:
                    self.view.receipt['code_unchanged'] = code_profile(db, kind, rid) == prior_code

        self.resume = getattr(db, 'replacement_resume', None)
        if self.resume:
            self.lid = journal.scope.get()
            self.path = db.execute('PRAGMA database_list').fetchone()['file']
            self.stamp = snapshot(db)

    def attach(self, result):
        if self.view is not None:
            self.view.attach(result)
        if not self.resume:
            return
        import server

        module = server.dictionary_replace if self.operation.startswith('dictionary-') else server.text_replace
        old, rows, options, reviewed = self.resume
        wanted = result['remaining_keys']
        try:
            with server.connect(path=self.path, audit=False) as db:
                db.execute('BEGIN')
                if self.stamp is not None and snapshot(db) != self.stamp:
                    raise ValueError(STALE)
                if self.stamp is not None:
                    if module is server.text_replace:
                        local = self.view.record_id if reviewed and self.view and self.view.receipt is not None else None
                        plan, current, opt = module.remaining_preview(db, self.lid, old, rows, options, wanted, local=local)
                    else:
                        plan, current, opt = module.remaining_preview(db, self.lid, old, rows, options, set(wanted))
                    plan['token'] = CONTINUED + token_urlsafe(24)
                    if remember(db, module.__name__, self.lid, plan, current, opt):
                        result['remaining_preview'] = plan
                        return
                # Projects without a usable snapshot keep the regular token.
                body = {**self.body, 'reuse_preview': False}
                plan = module.preview(db, body, self.lid)
                wanted_keys = set(wanted)
                plan['changes'] = [match for match in plan['changes'] if match['key'] in wanted_keys]
                result['remaining_preview'] = plan
        except ValueError as error:
            result['preview_error'] = str(error)
        except Exception:
            logging.exception('Could not refresh a committed replacement preview')
            result['preview_error'] = STALE
