import json
import base64
import sqlite3
import uuid
import hashlib
import argparse
from contextlib import contextmanager, closing
from pathlib import Path
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer as BaseThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from corpus import parse, analyze, match, export_entry, compact_edited_pairs
from operations import organize
import metadata
import journal
import manual_status
import script_tags
import languages
import lexicon
import morpheme_registry
import quick_edit
import homophones
import synonyms
import phonology
import font_catalog
import dictionary_data
import homepage
import annotations
import grammar
import grammaticality
import grammar_audit_cache
import segmentation
import categories
import long_tasks
import backup_policy
import punctuation
import text_replace
import dictionary_replace
import dictionary_batch
import sentence_dictionary
import corpus_search
import analysis_workspace
import timeline
import media_engine
import object_media
import recorder
import collaborators
import grammar_survey
import example_groups
import example_numbering
import survey_search
import fieldwork_notes
import code_switching
import survey_templates
import people_queries
import word_transfer
import language_exchange
import dictionary_organization
import excel_exchange
import docx_exchange
import tempfile
import shutil
import legal_notices
import ui_localization

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'corpus.sqlite3'


class ThreadingHTTPServer(BaseThreadingHTTPServer):
    # A workspace loads many scripts/fonts at once, sometimes from several windows.
    request_queue_size = 128


@contextmanager
def connect(*, audit=True, path=None, cancellable=False, observe_snapshot=False):
    db = sqlite3.connect(DB if path is None else path)
    db.row_factory = sqlite3.Row
    import gloss_inheritance
    db.execute('PRAGMA foreign_keys=ON')
    gloss_token=gloss_inheritance.CURRENT.set(None)
    gloss_changes_token=gloss_inheritance.CHANGES.set(None)
    observer=grammar_audit_cache.Snapshot(db) if observe_snapshot else None
    observer_token=grammar_audit_cache.CURRENT.set(observer)
    sync_token = lexicon.synced_entries.set({})
    audit_promotion=None
    try:
        try:
            if cancellable:
                db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-8192')
                job=long_tasks.CURRENT.get()
                db.set_progress_handler(lambda:int(job['cancel'].is_set()),5000)
                db.execute('BEGIN IMMEDIATE')
            if audit and journal.action.get():
                if not db.in_transaction:db.execute("BEGIN IMMEDIATE")
                changes = journal.watch(db)
                gloss_inheritance.CHANGES.set(changes)
                audit_promotion=grammar_audit_cache.prepare_promotion(db)
            yield db
            if db.total_changes and not example_numbering.needed(db):example_numbering.assign_missing(db)
            if audit and journal.action.get():
                association_removals=lexicon.association_removals_only(changes)
                grammaticality.normalize_rows(db,changes)
                manual_status.normalize_rows(db,changes)
                import dictionary_gloss_sync
                meaning_changes=gloss_inheritance.sync_meanings(db,changes)
                import dictionary_form_sync
                dictionary_form_sync.sync(db,changes)
                lexicon.sync_changes(db,changes)
                gloss_inheritance.synchronize(db,changes)
                gloss_inheritance.validate_meaning_changes(db,meaning_changes)
                grammaticality.validate(db,changes)
                lexicon.validate_changes(db,changes,association_removals)
                collaborators.cleanup(db,changes)
                timeline.text_order.cleanup(db,changes)
                object_media.cleanup(db,changes)
                code_switching.sync_changes(db,changes)
                if any(t in {'object_media','lexemes','morphemes','dictionary_examples','timeline_media','timeline_speakers'} for t,_ in changes):object_media.validate(db)
                collaborators.validate_changes(db,changes)
                if any(t in example_groups.TABLES or t=='dictionary_examples' for t,_ in changes):example_groups.validate(db)
                journal.record(db, changes, journal.action.get())
                if any(a!=b for a,b in changes.values()):analysis_workspace.invalidate(db)
            if cancellable:long_tasks.committing(db)
            db.commit()
            if audit_promotion is not None:grammar_audit_cache.promote(db,audit_promotion,changes)
        except BaseException:
            # An interrupted progress handler must never interrupt the rollback.
            db.set_progress_handler(None,0)
            db.rollback()
            raise
    finally:
        grammar_audit_cache.CURRENT.reset(observer_token)
        if observer is not None:observer.close()
        if audit_promotion is not None:audit_promotion.close()
        lexicon.synced_entries.reset(sync_token)
        gloss_inheritance.CURRENT.reset(gloss_token)
        gloss_inheritance.CHANGES.reset(gloss_changes_token)
        db.close()


def init():
    import storage_optimization
    DB.parent.mkdir(exist_ok=True)
    # Preserve the complete pre-migration database, including old undo records.
    if DB.exists():
        with closing(sqlite3.connect(DB)) as old:
            missing_languages=not old.execute("SELECT 1 FROM sqlite_master WHERE name='languages'").fetchone()
            missing_dictionary=not old.execute("SELECT 1 FROM sqlite_master WHERE name='morphology_analyses'").fetchone() or not old.execute("SELECT 1 FROM sqlite_master WHERE name='morph_class_templates'").fetchone()
            missing_sentence_layers='anchor' not in {r[1] for r in old.execute('PRAGMA table_info(annotation_layers)')} or not old.execute("SELECT 1 FROM sqlite_master WHERE name='category_classes'").fetchone()
            missing_track_tree=old.execute("SELECT 1 FROM sqlite_master WHERE name='timeline_tracks'").fetchone() and 'parent_id' not in {r[1] for r in old.execute('PRAGMA table_info(timeline_tracks)')}
            missing_track_color=old.execute("SELECT 1 FROM sqlite_master WHERE name='timeline_tracks'").fetchone() and 'color' not in {r[1] for r in old.execute('PRAGMA table_info(timeline_tracks)')}
            missing_session_order=old.execute("SELECT 1 FROM sqlite_master WHERE name='timeline_sessions'").fetchone() and 'position' not in {r[1] for r in old.execute('PRAGMA table_info(timeline_sessions)')}
            missing_text_order=not old.execute("SELECT 1 FROM sqlite_master WHERE name='timeline_text_orders'").fetchone()
            missing_notes=not old.execute("SELECT 1 FROM sqlite_master WHERE name='fieldwork_notes'").fetchone()
            missing_code_spans=any(not old.execute('SELECT 1 FROM sqlite_master WHERE name=?',(t,)).fetchone() for t in code_switching.TABLES)
            missing_survey=not old.execute("SELECT 1 FROM sqlite_master WHERE name='survey_nodes'").fetchone()
            missing_example_groups=not old.execute("SELECT 1 FROM sqlite_master WHERE name='example_groups'").fetchone()
            missing_example_numbers=example_numbering.needed(old)
            missing_object_media=not old.execute("SELECT 1 FROM sqlite_master WHERE name='object_media'").fetchone()
            missing_organization=not old.execute("SELECT 1 FROM sqlite_master WHERE name='semantic_classes'").fetchone()
            missing_collaborators=not old.execute("SELECT 1 FROM sqlite_master WHERE name='collaborator_assignments'").fetchone()
            missing_inheritance=not old.execute("SELECT 1 FROM sqlite_master WHERE name='gloss_migrations'").fetchone()
            if missing_example_numbers or missing_example_groups or grammaticality.corpus_rows_needed(old) or storage_optimization.needed(old) or missing_inheritance or script_tags.needed(old) or manual_status.needed(old) or missing_code_spans or missing_object_media or missing_organization or missing_survey or missing_notes or missing_collaborators or missing_languages or missing_dictionary or missing_sentence_layers or missing_track_tree or missing_track_color or missing_session_order or missing_text_order or old.execute('PRAGMA user_version').fetchone()[0]<4 or not old.execute("SELECT 1 FROM sqlite_master WHERE name='corpus_units'").fetchone():
                backup_policy.sqlite_snapshot(DB.parent/'backups',old,'languages' if missing_languages else 'lexicon')
    with connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS texts(id TEXT PRIMARY KEY,title TEXT,source TEXT,original TEXT,digest TEXT UNIQUE,errors TEXT);
        CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY,text_id TEXT,position INTEGER,body TEXT,revision INTEGER DEFAULT 1);
        CREATE INDEX IF NOT EXISTS entries_text ON entries(text_id,position);
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,entry_id TEXT,created TEXT,body TEXT,revision INTEGER);''')
        metadata.initialize(db)
        journal.initialize(db)
        languages.initialize(db)
        code_switching.initialize(db)
        lexicon.initialize(db)
        analysis_workspace.initialize(db)
        timeline.initialize(db)
        object_media.initialize(db)
        collaborators.initialize(db)
        grammar_survey.initialize(db)
        example_groups.initialize(db)
        fieldwork_notes.initialize(db)
        code_switching.rebuild(db)
        manual_status.migrate(db)
        script_tags.recover(db)
        import gloss_inheritance
        gloss_inheritance.initialize(db)
        gloss_inheritance.migrate(db)
        storage_optimization.migrate(db)
        import word_analysis_memory
        word_analysis_memory.initialize(db)
        if grammaticality.migrate_corpus(db):analysis_workspace.invalidate(db)
    backup_policy.prune(DB.parent/'backups')


def import_text(title, source, original):
    with connect() as db:return import_into(db,title,source,original)


def import_into(db,title,source,original):
    long_tasks.checkpoint(None,'正在解析文本…')
    entries, errors = parse(original)
    if not entries:
        raise ValueError('未找到可导入的 #gloss / #pass 调用：'+json.dumps(errors, ensure_ascii=False))
    digest = hashlib.sha256(original.encode()).hexdigest()
    lid=journal.scope.get()
    languages.require(db,lid)
    scoped_digest=hashlib.sha256((lid+'\0'+original).encode()).hexdigest()
    existing = db.execute('SELECT id FROM texts WHERE language_id=? AND digest IN (?,?)', (lid,digest,scoped_digest)).fetchone()
    if existing:
        return {'id': existing['id'], 'duplicate': True}
    tid = str(uuid.uuid4())
    db.execute('INSERT INTO texts(id,title,source,original,digest,errors,language_id) VALUES(?,?,?,?,?,?,?)', (tid, title, source, original, scoped_digest, json.dumps(errors, ensure_ascii=False),lid))
    for i, entry in long_tasks.steps(enumerate(entries)):
        eid=str(uuid.uuid4())
        db.execute('INSERT INTO entries(id,text_id,position,body) VALUES(?,?,?,?)', (eid, tid, i+1, json.dumps(entry, ensure_ascii=False)))
        lexicon.sync_entry(db,eid)
    return {'id': tid, 'count': len(entries), 'errors': errors}


class Handler(BaseHTTPRequestHandler):
    def ui_language(self):
        return ui_localization.language(getattr(self,'headers',{}))

    def send(self, value, code=200, mime='application/json; charset=utf-8'):
        if mime.startswith('application/json'):
            value=ui_localization.present(value,urlparse(getattr(self,'path','')).path,self.ui_language())
        elif mime.startswith('text/html'):
            source=value.decode('utf-8') if isinstance(value,bytes) else value
            if isinstance(source,str) and '<body' in source and 'data-ui-ready=' not in source:value=ui_localization.bootstrap_html(source)
        data = json.dumps(value, ensure_ascii=False).encode() if mime.startswith('application/json') else value.encode() if isinstance(value, str) else value
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            self.get()
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.send({'error': str(exc)}, 400)
        except Exception as exc:
            self.send({'error': str(exc)}, 500)

    def get(self):
        url = urlparse(self.path)
        q = {k:v[0] for k,v in parse_qs(url.query).items()}
        if url.path=='/api/recorder-context':
            with connect(audit=False) as db:result=recorder.target_context(db,q.get('kind'),q.get('id',''),q.get('language','ordos'))
            return self.send(result)
        if url.path=='/api/recorder-devices':return self.send({'devices':recorder.audio_capture.devices()})
        if url.path=='/api/recorder-pending':return self.send({'items':recorder.SERVICE.pending(DB,q.get('language','ordos'))})
        if url.path=='/api/recorder-status':return self.send(recorder.SERVICE.status(DB,q.get('token')))
        if url.path=='/api/recorder-file':
            source,name=recorder.SERVICE.playback(DB,q.get('token'))
            if isinstance(source,bytes):return media_engine.stream_bytes(self,source,name)
            return media_engine.stream_file(self,source)
        if url.path in ui_localization.ASSET_PATHS:
            if url.path=='/i18n-catalog.js':
                return self.send('globalThis.CorporiumMessages='+json.dumps(ui_localization.catalog(),ensure_ascii=True)+';',mime='text/javascript; charset=utf-8')
            return self.send((ROOT/'web'/url.path[1:]).read_bytes(),mime=('text/css' if url.path.endswith('.css') else 'text/javascript')+'; charset=utf-8')
        if url.path=='/licenses/catalog':return self.send(legal_notices.catalog())
        if url.path=='/licenses/document':return self.send(legal_notices.document(q.get('id','')))
        if url.path=='/licenses/developer-font':
            return self.send((ROOT/'font'/'Junicode'/'Junicode.ttf').read_bytes(),mime='font/ttf')
        if url.path in {'/licenses','/license-notices.js','/license-notices.css','/style.css'}:
            name='licenses.html' if url.path=='/licenses' else url.path[1:]
            mime='text/html' if url.path=='/licenses' else 'text/css' if url.path.endswith('.css') else 'text/javascript'
            return self.send((ROOT/'web'/name).read_bytes(),mime=mime+'; charset=utf-8')
        if url.path=='/api/task-status':return self.send(long_tasks.view(DB,q.get('id')))
        if url.path=='/api/task-download':
            kind=q.get('kind')
            if kind not in ('project-backup','language-json','analysis-json','export'):raise ValueError('导出文件类型无效')
            path=language_exchange.staged(DB,q.get('token'),kind)
            name='project.corporium-backup' if kind=='project-backup' else 'analysis.json' if kind=='analysis-json' else 'language.json' if kind=='language-json' else 'language.corporium'
            requested=q.get('name','')
            if kind=='analysis-json' and requested.endswith('.json') and len(requested)<=128 and all(c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._' for c in requested):name=requested
            self.send_response(200);self.send_header('Content-Type','application/json' if kind in ('language-json','analysis-json') else 'application/zip');self.send_header('Content-Disposition','attachment; filename="'+name+'"');self.send_header('Content-Length',str(path.stat().st_size));self.send_header('Cache-Control','no-store');self.end_headers()
            with path.open('rb') as f:shutil.copyfileobj(f,self.wfile,1024*1024)
            return
        if url.path=='/api/language-example':
            return self.send((ROOT/'packaging/examples/Telira.corporium').read_bytes(),mime='application/zip')
        if url.path=='/api/language-package-download':
            path=language_exchange.staged(DB,q.get('token'),'export')
            self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Content-Disposition','attachment; filename="language.corporium"');self.send_header('Content-Length',str(path.stat().st_size));self.send_header('Cache-Control','no-store');self.end_headers()
            with path.open('rb') as f:shutil.copyfileobj(f,self.wfile,1024*1024)
            return
        if url.path=='/api/timeline-file':
            with connect(audit=False) as db:
                asset=timeline.media_view(db,q.get('asset'))
                path=media_engine.playable(DB,asset,q.get('proxy')=='true')
            return media_engine.stream_file(self,path)
        if url.path=='/api/object-media':
            with connect(audit=False) as db:return self.send(object_media.listing(db,q['kind'],q['id']))
        if url.path=='/api/object-media-assets':
            with connect(audit=False) as db:
                lid=q.get('language','ordos')
                return self.send([timeline.media_view(db,r[0]) for r in db.execute('SELECT id FROM timeline_media WHERE language_id=? ORDER BY rowid DESC',(lid,))])
        if url.path=='/api/timeline-job':return self.send(media_engine.job_view(DB,q.get('id')))
        if url.path=='/api/timeline-wave-settings':
            import waveform_cache
            return self.send(waveform_cache.settings(DB))
        if url.path=='/api/fonts':
            return self.send(font_catalog.scan(q.get('refresh')=='true'))
        if url.path=='/api/font-file':
            data,mime=font_catalog.font_file(q.get('id',''))
            return self.send(data,mime=mime)
        with connect(observe_snapshot=url.path=='/api/grammar-audit') as db:
            # Sentence bodies and stable units must come from the same snapshot.
            db.execute('BEGIN')
            lid=q.get('language','all')
            if url.path=='/api/home':
                return self.send(homepage.overview(db))
            # The catalogue must load even when a previous project's language is stale.
            if url.path == '/api/languages':
                return self.send([dict(r) for r in db.execute('SELECT l.*, (SELECT COUNT(*) FROM texts t WHERE t.language_id=l.id) text_count, (SELECT COUNT(*) FROM entries e JOIN texts t ON t.id=e.text_id WHERE t.language_id=l.id) entry_count FROM languages l ORDER BY l.rowid')])
            if lid!='all': languages.require(db,lid)
            if url.path=='/api/collaborators':return self.send({**timeline.hierarchy.catalog(db),'writing_types':[dict(r) for r in db.execute('SELECT w.*,l.name language_name FROM writing_types w JOIN languages l ON l.id=w.language_id ORDER BY l.name,w.position,w.name')]})
            if url.path=='/api/collaborator-links':return self.send(collaborators.batch(db,q.get('kind','corpus'),[v for v in q.get('ids','').split(',') if v]))
            if url.path=='/api/fieldwork-notes':
                languages.require(db,lid)
                return self.send(fieldwork_notes.detail(db,lid,q['id']) if q.get('id') else fieldwork_notes.listing(db,lid))
            if url.path=='/api/fieldwork-search':return self.send(fieldwork_notes.search(db,lid,q))
            if url.path=='/api/timeline-catalog':return self.send(timeline.hierarchy.catalog(db))
            if url.path=='/api/timeline-list':return self.send(timeline.listing(db,lid))
            if url.path=='/api/timeline-text-order':
                timeline.session(db,lid,q.get('id'))
                return self.send(timeline.text_order.state(db,lid,q.get('text_id'),q.get('id')))
            if url.path=='/api/timeline-clips':
                result=timeline.sentence_clips(db,[v for v in q.get('ids','').split(',') if v])
                proxies={}
                for clips in result.values():
                    for clip in clips:
                        if clip['asset'] not in proxies:
                            asset=timeline.media_view(db,clip['asset'])
                            proxies[clip['asset']]=(media_engine.cache_root(DB)/(media_engine.cache_key(asset)+'.mp4')).is_file()
                        clip['proxy']=proxies[clip['asset']]
                return self.send(result)
            if url.path=='/api/timeline-detail':
                result=timeline.detail(db,lid,q)
                if result['media']:
                    try:media_engine.resolve(DB,result['media'])
                    except (ValueError,OSError) as error:result['media']['unavailable']=str(error)
                return self.send(result)
            if url.path=='/api/timeline-pending':return self.send(timeline.pending(db,lid,q))
            if url.path=='/api/timeline-wave':
                s=timeline.session(db,lid,q['id']);asset=timeline.media_view(db,s['media_id'])
                if not asset:return self.send({'ready':False,'channels':[]})
                return self.send(media_engine.wave_data(DB,asset,timeline.number(q.get('start',0)),timeline.number(q.get('end',60000)),q.get('pixels',1200),q.get('compact')=='1'))
            if url.path=='/api/analysis-fields':return self.send(analysis_workspace.analysis_fields.catalog(db,lid))
            if url.path=='/api/dialogue':return self.send(people_queries.dialogue(db,lid,q))
            if url.path=='/api/analysis-records':return self.send(analysis_workspace.listing(db,lid))
            if url.path=='/api/analysis-result':return self.send(analysis_workspace.result_page(db,lid,q))
            if url.path=='/api/analysis-group':return self.send(analysis_workspace.evidence_page(db,lid,q))
            if url.path=='/api/analysis-export':return self.send(analysis_workspace.export_result(db,lid,q))
            if url.path=='/api/grammar-tags':return self.send(grammar.listing(db,lid))
            if url.path=='/api/grammar-reference':return self.send(grammar.reference())
            if url.path=='/api/grammaticality-types':return self.send(grammaticality.catalog(db,q.get('lexical_language',lid)))
            if url.path=='/api/backup-policy':return self.send(backup_policy.status(DB.parent/'backups'))
            if url.path=='/api/classes':return self.send(categories.listing(db,lid))
            if url.path=='/api/quick-edit-settings':return self.send(quick_edit.get(db,lid))
            if url.path=='/api/homophones':return self.send(homophones.table(db,lid,q))
            if url.path=='/api/synonyms':return self.send(synonyms.list_links(db,lid,q.get('kind'),q.get('id')))
            if url.path=='/api/synonym-search':return self.send(synonyms.search(db,lid,q))
            if url.path=='/api/homophone-phonology':return self.send(phonology.get(db,lid))
            if url.path=='/api/homophone-words':return self.send(homophones.source_words(db,lid,q.get('identity',''),q.get('page',1)))
            if url.path=='/api/morphemes':return self.send(morpheme_registry.listing(db,lid,q.get('q',''),q.get('page',1),q.get('status',''),q.get('search'),q.get('page_size',30),q.get('sort_order','')))
            if url.path=='/api/morpheme':return self.send(morpheme_registry.detail(db,q['id'],lid))
            if url.path=='/api/dictionary-counts':
                return self.send({table:db.execute('SELECT count(*) FROM '+table+(' WHERE language_id=?' if lid!='all' else ''),(lid,) if lid!='all' else ()).fetchone()[0] for table in ('lexemes','morphemes')})
            if url.path=='/api/morpheme-components':return self.send(morpheme_registry.components(db,q['id'],lid))
            if url.path=='/api/morphology-options':return self.send(lexicon.morphology.options(db,lid,q.get('entry_id','')))
            if url.path=='/api/grammar-audit':return self.send(grammar.audit(db,q))
            if url.path=='/api/homonym-preview':return self.send(lexicon.homonyms.plan(db,q.get('lexical_language',lid),q.get('form',''),q.get('exclude','')))
            if url.path=='/api/lexemes':
                return self.send(lexicon.list_lexemes(db,q.get('lexical_language',lid),q.get('q',''),q.get('page',1),q.get('page_size',30),category=q.get('semantic_class',''),order=q.get('sort_order',''),search=q.get('search'),summary=q.get('summary')=='1',targets=q.get('targets')=='all',counts=q.get('counts')!='0'))
            if url.path=='/api/morpheme-search-options':
                import morpheme_search
                return self.send(morpheme_search.catalog(db,lid))
            if url.path=='/api/dictionary-search-options':return self.send(lexicon.dictionary_search.catalog(db,q.get('lexical_language',lid)))
            if url.path=='/api/dictionary-organization':return self.send(dictionary_organization.listing(db,q.get('lexical_language',lid)))
            if url.path=='/api/dictionary-layout':
                import dictionary_layout
                return self.send(dictionary_layout.tree(db,lid,json.loads(q.get('path','[]')),q.get('page',1)))
            if url.path=='/api/survey':return self.send(grammar_survey.listing(db,lid))
            if url.path=='/api/survey-detail':return self.send(grammar_survey.detail(db,lid,q.get('id'),q.get('page',1)))
            if url.path=='/api/example-groups-library':return self.send(example_groups.library(db,lid,q))
            if url.path=='/api/example-group':return self.send(example_groups.detail(db,lid,q.get('id')))
            if url.path=='/api/survey-search':return self.send(survey_search.search(db,lid,q))
            if url.path=='/api/survey-locate':return self.send(survey_search.locate(db,lid,q))
            if url.path=='/api/survey-templates':return self.send(survey_templates.listing(DB.parent/'templates'/'grammar'))
            if url.path=='/api/independent-example':
                d=annotations.get(db,'independent',q.get('id'))
                if lid not in ('all',d['language_id']):raise ValueError('例句不属于当前语言')
                code_switching.attach(db,d['body'],'independent',d['id'],d)
                return self.send(d)
            if url.path=='/api/example-library':return self.send(annotations.search(db,q))
            if url.path=='/api/punctuation-settings':return self.send(punctuation.settings(db,lid))
            if url.path=='/api/layers':return self.send(annotations.layers(db,q.get('lexical_language',lid)))
            if url.path=='/api/annotations':
                d=annotations.get(db,q['kind'],q['id']);code_switching.attach(db,d['body'],q['kind'],q['id'],d)
                return self.send(d)
            if url.path=='/api/code-catalog':return self.send(code_switching.catalog(db))
            if url.path=='/api/code-detail':return self.send(code_switching.detail(db,q['kind'],q['id']))
            if url.path=='/api/segmentation':return self.send(segmentation.get(db,q['kind'],q['id']))
            if url.path=='/api/export-layer-status':return self.send({'count':db.execute("SELECT COUNT(*) FROM annotation_cells c JOIN entries e ON e.id=c.record_id WHERE c.owner_kind='corpus' AND e.text_id=?",(q['id'],)).fetchone()[0]})
            if url.path=='/api/writing-types':
                return self.send(dictionary_data.types(db,q.get('lexical_language',lid),catalog_only=q.get('catalog_only')=='1'))
            if url.path=='/api/dictionary-examples':
                return self.send(dictionary_data.examples(db,q['id']))
            if url.path=='/api/lexeme-auto-preview':
                q.update({k:v[0] for k,v in parse_qs(url.query,keep_blank_values=True).items() if k=='ignore_symbols'})
                return self.send(lexicon.auto_link_plan(db,lid,q.get('text_id',''),q.get('ignore_symbols','-=.'),q.get('ignore_position','edges')))
            if url.path=='/api/lexeme':
                return self.send(lexicon.get_lexeme(db,q['id']))
            if url.path=='/api/lexeme-examples':
                return self.send(lexicon.examples(db,q['id'],q.get('page',1),q.get('kind','all'),q.get('form_id','all')))
            if url.path=='/api/unit-dictionary':
                return self.send(lexicon.unit_info(db,q['id']))
            if url.path == '/api/undo-state':
                # History and its view token must describe the same SQLite snapshot.
                if not db.in_transaction:db.execute('BEGIN')
                state=journal.state(db,q.get('language','ordos'))
                state['workspace_revision']=journal.workspace_revision(db)
                return self.send(state)
            if url.path == '/api/texts':
                rows = db.execute("SELECT t.id,t.title,t.source,t.errors,t.language_id,l.name language_name,i.folder_id,COALESCE(i.metadata,'{}') metadata,COALESCE(i.revision,0) info_revision,COUNT(e.id) count FROM texts t JOIN languages l ON l.id=t.language_id LEFT JOIN entries e ON e.text_id=t.id LEFT JOIN text_info i ON i.text_id=t.id WHERE (?='all' OR t.language_id=?) GROUP BY t.id ORDER BY COALESCE(json_extract(i.metadata,'$._sidebar_order'),t.rowid),t.rowid",(lid,lid)).fetchall()
                return self.send([dict(r) for r in rows])
            if url.path == '/api/folders':
                return self.send([dict(r) for r in db.execute("SELECT * FROM folders WHERE (?='all' OR language_id=?) ORDER BY position,id",(lid,lid))])
            if url.path == '/api/entries':
                return self.send(corpus_search.search(db,q,lid))
            if url.path == '/api/history':
                rows = db.execute('SELECT * FROM history WHERE entry_id=? ORDER BY id DESC', (q['id'],)).fetchall()
                result=[]
                for step in db.execute('SELECT * FROM undo_steps WHERE applied=1 ORDER BY id DESC'):
                    if step['label']!=journal.LABELS['/api/save']: continue
                    for c in journal.decode_changes(step['changes']):
                        before,after=c['before'],c['after']
                        if c['table']=='entries' and before and after and before['id']==q['id'] and before['body']!=after['body']:
                            result.append({'created':step['created'],'body':json.loads(before['body']),'revision':before['revision']})
                result.extend({**dict(r),'body':json.loads(r['body'])} for r in rows)
                owner=db.execute('SELECT t.language_id FROM entries e JOIN texts t ON t.id=e.text_id WHERE e.id=?',(q['id'],)).fetchone()
                limit=journal.state(db,owner[0] if owner else 'ordos')['step_limit']
                return self.send(result[:limit])
            if url.path == '/api/positions':
                return self.send([{'id':r['id'],'position':r['position'],'translation':json.loads(r['body'])['translation'][:100]} for r in db.execute('SELECT id,position,body FROM entries WHERE text_id=? ORDER BY position',(q['id'],))])
            if url.path == '/api/backup':
                return self.send({'format':'ordos-corpus-v1', 'created':datetime.now(timezone.utc).isoformat(), 'object_media_files':object_media.backup_files(db,DB), **{table:[dict(r) for r in db.execute('SELECT rowid AS rowid,* FROM '+table)] for table in metadata.TABLES}})
            if url.path == '/api/word-transfer-snapshot':
                return self.send(word_transfer.snapshot(db,q['kind'],q['id']))
            if url.path == '/api/export-language':
                return self.send(language_exchange.export_bundle(db,lid))
            if url.path == '/api/export':
                text = db.execute('SELECT * FROM texts WHERE id=?',(q['id'],)).fetchone()
                if q.get('original') == 'true':
                    return self.send(text['original'],mime='text/plain; charset=utf-8')
                import gloss_inheritance
                entries = [gloss_inheritance.load(db,'corpus',r['id'],r['body']) for r in gloss_inheritance.iter_rows(db,db.execute('SELECT id,body FROM entries WHERE text_id=? ORDER BY position',(q['id'],)),'corpus')]
                return self.send('\n\n'.join(export_entry(e) for e in entries),mime='text/plain; charset=utf-8')
        fonts = {
            '/font/IPAPANNEW.TTF': 'IPAPANNEW.TTF',
            '/font/Junicode/Junicode.ttf': 'Junicode/Junicode.ttf',
            '/font/Junicode/Junicode-Italic.ttf': 'Junicode/Junicode-Italic.ttf',
            '/font/Junicode/Junicode-Bold.ttf': 'Junicode/Junicode-Bold.ttf',
            '/font/Junicode/Junicode-BoldItalic.ttf': 'Junicode/Junicode-BoldItalic.ttf',
        }
        if url.path in fonts:
            path=font_catalog.ROOT/fonts[url.path]
            if not path.is_file():path=ROOT/'font'/'Junicode'/'Junicode.ttf'
            return self.send(path.read_bytes(), mime='font/ttf')
        files = {'/classes.js':'classes.js','/display-tools.js':'display-tools.js','/ui-tools.js':'ui-tools.js','/grammar.js':'grammar.js','/inline-editor.js':'inline-editor.js','/example-library.js':'example-library.js','/':'index.html','/fonts.js':'fonts.js','/home.js':'home.js','/dictionary-manager.js':'dictionary-manager.js','/app.js':'app.js','/organize.js':'organize.js','/metadata.js':'metadata.js','/undo.js':'undo.js','/languages.js':'languages.js','/lexicon.js':'lexicon.js','/lexicon-extra.js':'lexicon-extra.js','/style.css':'style.css'}
        files.update({'/reduplication.js':'reduplication.js','/text-tools.js':'text-tools.js','/word-structure.js':'word-structure.js','/punctuation.js':'punctuation.js','/workspace-layout.js':'workspace-layout.js','/typography.js':'typography.js','/morphology.js':'morphology.js','/segmentation.js':'segmentation.js','/multipart-forms.js':'multipart-forms.js','/multipart-forms.css':'multipart-forms.css','/favicon.ico':'favicon.ico'})
        files['/layer-order.js']='layer-order.js'
        files['/analysis-workspace.js']='analysis-workspace.js'
        files['/gloss-sources.js']='gloss-sources.js'
        files['/grammar-candidates.js']='grammar-candidates.js'
        files['/grammaticality.js']='grammaticality.js'
        files['/paradigms.js']='paradigms.js'
        files['/language-exchange.js']='language-exchange.js'
        files['/language-deletion.js']='language-deletion.js'
        files['/word-transfer.js']='word-transfer.js'
        files['/sentence-create.js']='sentence-create.js'
        files['/sentence-search.js']='sentence-search.js'
        files['/dialogue.js']='dialogue.js'
        files['/dialogue.css']='dialogue.css'
        files['/workspace-navigation.js']='workspace-navigation.js'
        files['/workspace-loading.js']='workspace-loading.js'
        files['/morpheme-colors.js']='morpheme-colors.js'
        files['/morph-color-settings.js']='morph-color-settings.js'
        files['/dictionary-replace.js']='dictionary-replace.js'
        files['/dictionary-organization.js']='dictionary-organization.js'
        files['/dictionary-search.js']='dictionary-search.js'
        files['/dictionary-list.js']='dictionary-list.js'
        files['/rich-text.js']='rich-text.js'
        files['/fieldwork-notes.js']='fieldwork-notes.js'
        files['/dictionary-batch.js']='dictionary-batch.js'
        files['/fieldwork-notes.css']='fieldwork-notes.css'
        files['/long-tasks.js']='long-tasks.js'
        files['/morphemes.js']='morphemes.js'
        files['/homophones.js']='homophones.js'
        files['/quick-edit-rows.js']='quick-edit-rows.js'
        files['/quick-edit.js']='quick-edit.js'
        for name in ('ipa-symbols.js','ipa-keyboard.js','ipa-keyboard.css','dictionary-layout.js','dictionary-layout.css','sentence-dictionary.js','sentence-dictionary.css'):files['/'+name]=name
        files['/synonyms.js']='synonyms.js'
        files['/homophone-phonology.js']='homophone-phonology.js'
        files['/excel-exchange.js']='excel-exchange.js'
        files['/docx-exchange.js']='docx-exchange.js'
        files['/text-exchange.js']='text-exchange.js'
        files['/text-drag.js']='text-drag.js'
        files['/code-switching.js']='code-switching.js'
        files['/code-switching.css']='code-switching.css'
        files['/sentence-inspector.js']='sentence-inspector.js'
        files['/object-media.js']='object-media.js'
        files['/recorder.js']='recorder.js'
        files['/recorder.css']='recorder.css'
        files.update({'/licenses':'licenses.html','/license-notices.js':'license-notices.js','/license-notices.css':'license-notices.css'})
        files['/example-groups.js']='example-groups.js'
        files['/example-groups.css']='example-groups.css'
        files.update({'/formatted-copy-format.js':'formatted-copy-format.js','/formatted-copy.js':'formatted-copy.js','/formatted-copy.css':'formatted-copy.css'})
        files['/analysis-workspace.css']='analysis-workspace.css'
        files.update({'/ordering.js':'ordering.js','/workbench.js':'workbench.js','/workbench.css':'workbench.css','/survey-search.js':'survey-search.js','/grammar-survey.js':'grammar-survey.js','/grammar-survey.css':'grammar-survey.css','/sentence-pairs.js':'sentence-pairs.js'})
        files.update({'/collaborators.js':'collaborators.js','/participants.js':'participants.js','/timeline-tree.js':'timeline-tree.js','/timeline.js':'timeline.js','/waveform.js':'waveform.js','/timeline.css':'timeline.css','/timeline-geometry.js':'timeline-geometry.js','/sentence-audio.js':'sentence-audio.js','/range-playback.js':'range-playback.js'})
        if url.path=='/favicon.ico':return self.send((ROOT/'web/favicon.ico').read_bytes(),mime='image/x-icon')
        if url.path in files:
            mime = 'text/html' if url.path in ('/','/licenses') else 'text/css' if url.path.endswith('.css') else 'text/javascript'
            return self.send((ROOT/'web'/files[url.path]).read_bytes(),mime=mime+'; charset=utf-8')
        self.send({'error':'未找到'},404)

    def do_POST(self):
        token = journal.action.set(journal.LABELS.get(self.path))
        scope_token = journal.scope.set('ordos')
        try:
            self.post()
        finally:
            journal.action.reset(token)
            journal.scope.reset(scope_token)

    def post(self):
        if not self.path.startswith(('/api/task-','/api/recorder-')) and long_tasks.active(DB):return self.send({'error':'当前项目正在处理后台任务，请等待完成或取消任务后再修改。'},409)
        if self.path.startswith('/api/object-media-upload?'):
            if self.headers.get('Origin') not in (None,'http://'+self.headers.get('Host','')) or self.headers.get('Content-Type')!='application/octet-stream':return self.send({'error':'拒绝跨站上传'},403)
            path=None
            try:
                q={k:v[0] for k,v in parse_qs(urlparse(self.path).query).items()}
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=256*1024**2:raise ValueError('单个媒体文件须在 256 MB 以内')
                with tempfile.NamedTemporaryFile(suffix=Path(q.get('name','')).suffix,dir=language_exchange.STAGING.name,delete=False) as f:
                    path=Path(f.name);left=size
                    while left:
                        chunk=self.rfile.read(min(left,1024*1024))
                        if not chunk:raise ValueError('媒体上传未完成')
                        f.write(chunk);left-=len(chunk)
                return self.send({'token':language_exchange.stage(DB,path,'object-media-upload')})
            except Exception as e:
                if path:path.unlink(missing_ok=True)
                return self.send({'error':str(e)},400)
        if self.path=='/api/language-package-upload':
            if self.headers.get('Origin') not in (None,'http://'+self.headers.get('Host','')) or self.headers.get('Content-Type')!='application/octet-stream':return self.send({'error':'拒绝跨站上传'},403)
            path=None
            try:
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=language_exchange.MAX_PACKAGE:raise ValueError('数据包须在 20 GB 以内')
                with tempfile.NamedTemporaryFile(suffix='.corporium',dir=language_exchange.STAGING.name,delete=False) as f:
                    path=Path(f.name);left=size
                    while left:
                        chunk=self.rfile.read(min(left,1024*1024))
                        if not chunk:raise ValueError('数据包上传未完成')
                        f.write(chunk);left-=len(chunk)
                if self.headers.get('X-Corporium-Preview')=='deferred':
                    result={'token':language_exchange.stage(DB,path,'import')};path=None
                    return self.send(result)
                bundle=language_exchange.read(path)
                try:result=language_exchange.info(bundle)
                finally:bundle.close()
                result['token']=language_exchange.stage(DB,path,'import');path=None
                return self.send(result)
            except Exception as e:return self.send({'error':str(e)},400)
            finally:
                if path:path.unlink(missing_ok=True)
        # Local writes only; prevent browser cross-origin form requests.
        if self.headers.get('Origin') not in (None, 'http://'+self.headers.get('Host','')) or not self.headers.get('Content-Type','').startswith('application/json'):
            return self.send({'error':'拒绝跨站写入'},403)
        try:
            size = int(self.headers.get('Content-Length',0))
            if size > 20_000_000:
                raise ValueError('文件超过 20 MB')
            body = json.loads(self.rfile.read(size))
            if self.path.startswith('/api/recorder-'):
                lid=body.get('_language','ordos');journal.scope.set(lid)
                if self.path=='/api/recorder-start':
                    if long_tasks.active(DB):raise ValueError('请等待当前后台任务完成，再开始录音')
                    with connect(audit=False) as db:context=recorder.describe(db,lid,body)
                    return self.send(recorder.SERVICE.start(DB,context,body))
                if self.path=='/api/recorder-stop':return self.send(recorder.SERVICE.stop(DB,body.get('token')))
                if self.path=='/api/recorder-release':return self.send(recorder.SERVICE.release(DB,body.get('token')))
                with recorder.SERVICE.lock:
                    take=recorder.SERVICE._find(DB,body.get('token'))
                    if take['context']['language_id']!=lid:raise ValueError('请选择材料所属语言')
                    if self.path=='/api/recorder-keep':
                        if long_tasks.active(DB):raise ValueError('请等待当前后台任务完成，再关联录音')
                        with connect() as db:result=recorder.SERVICE.attach(db,DB,lid,body)
                        take.update(state='linked',session_id=result.get('session_id',result.get('id','')))
                        recorder.SERVICE._persist(take)
                        return self.send(result)
                    if self.path=='/api/recorder-discard':
                        if take['state']!='ready' or body.get('confirmed') is not True:raise ValueError('请先停止录音并确认放弃关联')
                        take['state']='discarded';recorder.SERVICE._persist(take)
                        return self.send({'ok':True})
                raise ValueError('未知录音操作')
            if self.path=='/api/task-start':
                request=body.get('request',{})
                if not isinstance(request,dict):raise ValueError('任务参数无效')
                return self.send({'id':long_tasks.submit(DB,body.get('kind'),{**request,'language':request.get('language',body.get('_language','ordos'))})})
            if self.path=='/api/task-cancel':return self.send(long_tasks.cancel(DB,body.get('id')))
            if self.path=='/api/task-forget':
                long_tasks.view(DB,body.get('id'))
                with long_tasks.LOCK:
                    if long_tasks.JOBS[body['id']]['state'] not in long_tasks.ACTIVE:del long_tasks.JOBS[body['id']]
                return self.send({'ok':True})
            if self.path.startswith('/api/fieldwork-note-'):
                action=self.path.removeprefix('/api/fieldwork-note-')
                with connect() as db:
                    lid=languages.request_scope(db,'fieldwork-note-'+action,body);journal.scope.set(lid)
                    result=fieldwork_notes.mutate(db,lid,action,body)
                return self.send(result)
            if self.path=='/api/object-media-save':
                lid=body.get('_language','ordos');journal.scope.set(lid);asset=None
                try:
                    with connect(audit=False) as db:
                        row=object_media.owner(db,body.get('kind'),body.get('record_id'))
                        if row['language_id']!=lid:raise ValueError('请选择材料所属语言')
                    if body.get('token'):
                        source=language_exchange.staged(DB,body['token'],'object-media-upload')
                        asset=object_media.ingest(DB,source,body.get('filename',source.name))
                    with connect() as db:result=object_media.mutate(db,lid,body,asset)
                    return self.send(result)
                except Exception:
                    if asset:(DB.parent/asset['path']).unlink(missing_ok=True)
                    raise
            if self.path=='/api/language-package-import':
                created=[]
                try:
                    path=language_exchange.staged(DB,body.get('token'),'import')
                    with connect() as db:result=language_exchange.import_new(db,DB,path,body.get('name',''),created)
                    return self.send(result)
                except Exception:
                    for p in created:p.unlink(missing_ok=True)
                    raise
            if self.path=='/api/language-package-export':
                with connect(audit=False) as db:result=language_exchange.prepare(db,DB,body.get('_language','ordos'),body.get('include_media') is True)
                return self.send(result)
            if self.path.startswith('/api/timeline-'):
                lid=body.get('_language','ordos');action=self.path.removeprefix('/api/timeline-')
                if action=='wave-settings':
                    import waveform_cache
                    return self.send(waveform_cache.settings(DB,body))
                with connect(audit=False) as db:languages.require(db,lid)
                journal.scope.set(lid)
                if action=='import':return self.send(media_engine.import_media(DB,body))
                if action=='cancel':return self.send(media_engine.cancel(DB,body.get('job')))
                if action=='prepare':
                    with connect(audit=False) as db:
                        s=timeline.session(db,lid,body['id']);asset=timeline.media_view(db,s['media_id'])
                        if not asset:raise ValueError('请先导入媒体')
                    return self.send(media_engine.prepare(DB,asset,body.get('kind','wave')))
                asset=media_engine.imported(DB,body.get('job')) if action in ('replace-preview','replace') or (action=='create' and body.get('job')) else None
                with connect() as db:result=timeline.mutate(db,lid,action,body,asset)
                return self.send(result)
            if self.path.startswith('/api/analysis-'):
                lid=body.get('_language','ordos')
                with connect(audit=False) as db:
                    if lid!='all':languages.require(db,lid)
                    action=self.path.removeprefix('/api/analysis-')
                    result=analysis_workspace.run(db,lid,body) if action=='run' else analysis_workspace.mutate(db,lid,action,body)
                return self.send(result)
            if self.path=='/api/backup-policy':return self.send(backup_policy.save_policy(DB.parent/'backups',body.get('limit')))
            if self.path in ('/api/language-delete-preview','/api/delete-language'):
                import language_deletion
                try:
                    with connect(audit=False) as db:
                        db.execute('BEGIN IMMEDIATE' if self.path=='/api/delete-language' else 'BEGIN')
                        result=language_deletion.remove(db,DB,body) if self.path=='/api/delete-language' else language_deletion.preview(db,body)
                except sqlite3.Error as error:raise ValueError('删除未完成，资料已保留：'+str(error)) from error
                return self.send(result)
            with connect(audit=False) as db:
                lid=languages.request_scope(db,self.path.removeprefix('/api/'),body)
            journal.scope.set(lid)
            if self.path=='/api/text-export':
                with connect(audit=False) as db:
                    t=db.execute('SELECT * FROM texts WHERE id=? AND language_id=?',(body.get('id'),lid)).fetchone()
                    if not t:raise ValueError('请选择当前语言的文本')
                    import gloss_inheritance
                    content='\n\n'.join(export_entry(gloss_inheritance.load(db,'corpus',r['id'],r['body'])) for r in gloss_inheritance.iter_rows(db,db.execute('SELECT id,body FROM entries WHERE text_id=? ORDER BY position,id',(t['id'],)),'corpus'))
                raw=content.encode('utf-8')
                with tempfile.NamedTemporaryFile(suffix='.typ',dir=language_exchange.STAGING.name,delete=False) as f:
                    f.write(raw);path=Path(f.name)
                return self.send(dict(name=t['title']+'.typ',data=base64.b64encode(raw).decode(),token=language_exchange.stage(DB,path,'text-export')))
            if self.path.startswith('/api/excel-'):
                with connect() as db:result=excel_exchange.dispatch(db,DB,self.path.removeprefix('/api/excel-'),body,lid)
                return self.send(result)
            if self.path.startswith('/api/docx-'):
                with connect(audit=self.path=='/api/docx-import') as db:result=docx_exchange.dispatch(db,DB,self.path.removeprefix('/api/docx-'),body,lid)
                return self.send(result)
            if self.path.startswith('/api/dict-org-'):
                with connect() as db:result=dictionary_organization.mutate(db,lid,self.path.removeprefix('/api/dict-org-'),body)
                return self.send(result)
            if self.path in ('/api/example-group-save','/api/example-group-delete'):
                with connect() as db:result=example_groups.mutate(db,lid,self.path.removeprefix('/api/example-group-'),body)
                return self.send(result)
            if self.path in ('/api/dictionary-batch-preview','/api/dictionary-batch-apply'):
                with connect(audit=self.path.endswith('-apply')) as db:result=(dictionary_batch.apply if self.path.endswith('-apply') else dictionary_batch.preview)(db,lid,body)
                return self.send(result)
            if self.path in ('/api/sentence-dictionary-preview','/api/sentence-dictionary-apply','/api/sentence-gloss-preview','/api/sentence-gloss-apply'):
                action = self.path.removeprefix('/api/')
                operation = {
                    'sentence-dictionary-preview': sentence_dictionary.intake_preview,
                    'sentence-dictionary-apply': sentence_dictionary.intake_apply,
                    'sentence-gloss-preview': sentence_dictionary.completion_preview,
                    'sentence-gloss-apply': sentence_dictionary.completion_apply,
                }[action]
                with connect(audit=action.endswith('-apply')) as db:
                    result = operation(db, body, lid)
                return self.send(result)
            if self.path=='/api/survey-template-file':
                with connect() as db:result=survey_templates.mutate(db,lid,DB.parent/'templates'/'grammar',body)
                return self.send(result)
            if self.path.startswith('/api/survey-'):
                if self.path=='/api/survey-template':body={**body,'_interface_language':self.ui_language()}
                with connect() as db:result=grammar_survey.mutate(db,lid,self.path.removeprefix('/api/survey-'),body)
                return self.send(result)
            if self.path=='/api/collaborator-save':
                with connect() as db:result=collaborators.save(db,body,lid)
                return self.send(result)
            if self.path in ('/api/dictionary-replace-preview','/api/dictionary-replace-apply'):
                with connect() as db:result=(dictionary_replace.preview if self.path.endswith('-preview') else dictionary_replace.apply)(db,body,lid)
                return self.send(result)
            if self.path in ('/api/text-replace-preview','/api/text-replace-apply'):
                with connect() as db:result=(text_replace.preview if self.path.endswith('-preview') else text_replace.apply)(db,body,lid)
                return self.send(result)
            if self.path in ('/api/punctuation-preview','/api/punctuation-apply'):
                with connect() as db:result=(punctuation.preview if self.path.endswith('-preview') else punctuation.apply)(db,body,lid)
                return self.send(result)
            if self.path=='/api/reduplication-preview':
                import reduplication
                return self.send(reduplication.preview(body))
            if self.path in ('/api/segmentation-save','/api/segmentation-link'):
                with connect() as db:result=(segmentation.save if self.path.endswith('-save') else segmentation.link)(db,body,lid)
                return self.send(result)
            if self.path in ('/api/class-save','/api/class-delete'):
                with connect() as db:result=categories.mutate(db,self.path.removeprefix('/api/'),body,lid)
                return self.send(result)
            if self.path in ('/api/grammar-save','/api/grammar-delete'):
                with connect() as db:result=grammar.mutate(db,self.path.removeprefix('/api/'),body,lid)
                return self.send(result)
            if self.path in ('/api/grammaticality-type-save','/api/grammaticality-type-delete'):
                with connect() as db:result=grammaticality.mutate_type(db,self.path.rsplit('-',1)[1],body,lid)
                return self.send(result)
            if self.path=='/api/grammaticality-save':
                with connect() as db:result=grammaticality.save(db,body,lid)
                return self.send(result)
            if self.path in ('/api/grammar-register-batch','/api/grammar-ignore','/api/grammar-unignore'):
                with connect() as db:result=grammar.batch(db,self.path.removeprefix('/api/'),body,lid)
                return self.send(result)
            if self.path=='/api/word-transfer':
                with connect() as db:result=word_transfer.apply(db,body,lid)
                return self.send(result)
            if self.path=='/api/inline-save':
                with connect() as db:result=annotations.inline_save(db,body,journal.scope.get())
                return self.send(result)
            if self.path=='/api/gloss-source-save':
                import gloss_inheritance
                with connect() as db:result=gloss_inheritance.set_mode(db,body,lid)
                return self.send(result)
            if self.path in ('/api/code-save','/api/code-delete','/api/code-link','/api/code-unlink'):
                with connect() as db:result=code_switching.mutate(db,self.path.removeprefix('/api/code-'),body,lid)
                return self.send(result)
            if self.path=='/api/sentence-create':
                with connect() as db:result=annotations.create_sentence(db,body,lid)
                return self.send(result)
            if self.path in ('/api/layer-save','/api/layer-delete','/api/layer-order','/api/annotation-save'):
                with connect() as db:result=annotations.mutate(db,self.path.removeprefix('/api/'),body,lid)
                return self.send(result)
            if self.path in ('/api/writing-save','/api/writing-delete','/api/example-save','/api/example-delete'):
                with connect() as db:
                    result=dictionary_data.mutate(db,self.path.removeprefix('/api/'),body,lid)
                return self.send(result)
            if self.path in ('/api/lexeme-to-morpheme-preview','/api/lexeme-to-morpheme'):
                import morpheme_conversion
                with connect() as db:result=(morpheme_conversion.preview if self.path.endswith('-preview') else morpheme_conversion.convert)(db,lid,body)
                return self.send(result)
            if self.path in ('/api/morpheme-sync-writings','/api/morpheme-save','/api/morpheme-assign','/api/morpheme-merge','/api/morpheme-delete','/api/morpheme-unassign'):
                with connect() as db:result=morpheme_registry.mutate(db,self.path.removeprefix('/api/'),body,lid)
                return self.send(result)
            if self.path=='/api/quick-edit-settings':
                with connect() as db:result=quick_edit.save(db,lid,body)
                return self.send(result)
            if self.path=='/api/homophone-phonology-save':
                with connect() as db:result=phonology.mutate(db,lid,body)
                return self.send(result)
            if self.path=='/api/synonym-save':
                with connect() as db:result=synonyms.mutate(db,lid,body)
                return self.send(result)
            if self.path=='/api/morpheme-save-preview':
                with connect() as db:result=morpheme_registry.save_plan(db,lid,body.get('id'),lexicon.normalize(body.get('body',{})),body.get('assignments'))
                return self.send(result)
            if self.path in ('/api/lexeme-save','/api/lexeme-delete','/api/lexeme-link','/api/lexeme-unlink','/api/lexeme-auto-link','/api/dictionary-examples-unlink'):
                with connect() as db:
                    result=lexicon.mutate(db,self.path.removeprefix('/api/'),body,lid)
                return self.send(result)
            if self.path=='/api/import-language':
                with connect() as db:
                    result=languages.import_bundle(db,body['bundle'],lid)
                return self.send(result)
            if self.path=='/api/save-language':
                with connect() as db:
                    result=languages.save(db,body)
                return self.send(result)
            if self.path in ('/api/undo','/api/redo','/api/undo-limit'):
                with connect() as db:
                    result = journal.apply(db,self.path,body)
                return self.send(result)
            if self.path in ('/api/organize-text','/api/save-text-info','/api/save-folder','/api/delete-folder','/api/order-folder'):
                with connect() as db:
                    result=metadata.update(db,self.path.removeprefix('/api/'),body)
                return self.send(result)
            if self.path in ('/api/duplicate-entry','/api/delete-entry','/api/delete-text','/api/move','/api/copy-entries','/api/merge','/api/split','/api/reorder-entry'):
                with connect() as db:
                    result=organize(db,self.path.removeprefix('/api/'),body,DB.parent/'backups')
                return self.send(result)
            if self.path == '/api/import':
                return self.send(import_text(body['title'],body.get('source',''),body['content']))
            if self.path == '/api/new-text':
                if body.get('empty'):
                    title=body.get('title','').strip()
                    if not title:raise ValueError('请填写文本标题')
                    tid=str(uuid.uuid4())
                    with connect() as db:db.execute('INSERT INTO texts(id,title,source,original,digest,errors,language_id) VALUES(?,?,?,?,NULL,?,?)',(tid,title,'','','[]',lid))
                    return self.send({'id':tid,'count':0,'errors':[]})
                return self.send(import_text(body['title'],body.get('source',''), '#pass([], (([], []),), [])\n// '+str(uuid.uuid4())))
            if self.path == '/api/save':
                with connect() as db:
                    if not db.in_transaction: db.execute('BEGIN IMMEDIATE')
                    row = db.execute('SELECT * FROM entries WHERE id=?',(body['id'],)).fetchone()
                    if row is None:
                        raise ValueError('条目不存在')
                    if row['revision'] != body['revision']:
                        return self.send({'error':'此条目已被修改，请刷新后再编辑'},409)
                    import gloss_inheritance
                    gloss_inheritance.check_revision(db,'corpus',body['id'],body)
                    entry = json.loads(row['body'])
                    previous_entry=gloss_inheritance.load(db,'corpus',body['id'],row['body'])
                    entry.update({k:body[k] for k in ('ipa','translation','words','notes')})
                    entry['words']=[{k:w.get(k,'content') for k in ('form','gloss','form_kind','gloss_kind')} for w in body['words']]
                    entry['words'],_=compact_edited_pairs(entry['words'],previous_entry['words'])
                    segmentation.preserve(previous_entry,entry)
                    if body.get('language_id'): languages.require(db,body['language_id'])
                    entry['language_id']=body.get('language_id',entry.get('language_id',''))
                    entry['language_notes']=body.get('language_notes',entry.get('language_notes',''))
                    grammaticality.copy_value(previous_entry,entry,body,'corpus')
                    entry['edited'] = True
                    analyze(entry)
                    # Ensure edited content still exports as one structurally identical call.
                    check, errors = parse(export_entry(entry))
                    if errors or len(check) != 1 or any(check[0][k] != entry[k] for k in ('ipa','translation')) or [(w['form'],w['gloss']) for w in check[0]['words']] != [(w['form'],w['gloss']) for w in entry['words']]:
                        raise ValueError('文本包含未配对的括号或未转义引号；请修正后保存')
                    db.execute('UPDATE entries SET body=?,revision=revision+1 WHERE id=?',(json.dumps(entry,ensure_ascii=False),body['id']))
                with connect() as db:
                    review=db.execute('SELECT COUNT(*) FROM lexical_links l JOIN corpus_units u ON u.id=l.unit_id WHERE u.entry_id=? AND u.active=0',(body['id'],)).fetchone()[0]
                return self.send({'ok':True,'dictionary_review_count':review})
            if self.path == '/api/add':
                with connect() as db:
                    if not db.in_transaction: db.execute('BEGIN IMMEDIATE')
                    if not db.execute('SELECT id FROM texts WHERE id=?',(body['text_id'],)).fetchone():
                        raise ValueError('文本不存在')
                    pos = db.execute('SELECT COALESCE(MAX(position),0)+1 FROM entries WHERE text_id=?',(body['text_id'],)).fetchone()[0]
                    entry = analyze({'function':'pass','ipa':'','translation':'','words':[],'raw':'','line':None,'edited':True})
                    eid=str(uuid.uuid4())
                    db.execute('INSERT INTO entries(id,text_id,position,body) VALUES(?,?,?,?)',(eid,body['text_id'],pos,json.dumps(entry)))
                return self.send({'ok':True,'position':pos,'id':eid})
            self.send({'error':'未知操作'},404)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.send({'error':str(exc)},400)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port',type=int,default=8765)
    ap.add_argument('--import-samples',action='store_true')
    args = ap.parse_args()
    first_run = not DB.exists()
    init()
    if args.import_samples and first_run:
        for file in (ROOT/'import typ').glob('*.typ'):
            result = import_text(file.stem,file.name,file.read_text(encoding='utf-8-sig'))
            print(file.name, json.dumps(result,ensure_ascii=False),flush=True)
    print(f'Local: http://localhost:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
