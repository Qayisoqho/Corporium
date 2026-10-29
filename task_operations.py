"""Allowlisted background operations; reuse business validation and undo journaling."""
from pathlib import Path
import journal
import languages
import long_tasks

OPERATIONS={
    'analysis-run','analysis-save','import','import-language','language-package-import',
    'excel-inspect','excel-preview','excel-import',
    'text-replace-preview','text-replace-apply',
    'dictionary-replace-preview','dictionary-replace-apply','dictionary-batch-preview','dictionary-batch-apply',
    'punctuation-preview','punctuation-apply','lexeme-auto-link',
    'dict-org-assign','homophone-phonology-save','morpheme-assign','morpheme-merge',
    'move','copy-text','copy-entries','merge','split','word-transfer',
    'timeline-text-order','timeline-interval','timeline-delete-interval','timeline-split','timeline-merge',
    'lexeme-save','morpheme-save',
}

def run(job):
    import server
    request=job['request'];operation=request.get('operation')
    if operation not in OPERATIONS:raise ValueError('不支持的批量操作')
    body=request.get('body')
    if not isinstance(body,dict):raise ValueError('任务参数无效')
    body={**body,'_language':request.get('language','ordos')}
    created=[];job['created']=created;committed=False
    action=journal.action.set(journal.LABELS.get('/api/'+operation))
    scope=journal.scope.set(body['_language'])
    try:
        with server.connect(path=job['project'],cancellable=True) as db:
            lid=body['_language']
            if operation!='language-package-import':
                if operation in ('analysis-run','analysis-save'):
                    if lid!='all':languages.require(db,lid)
                else:lid=languages.request_scope(db,operation,body)
                journal.scope.set(lid)
            long_tasks.checkpoint(None,'正在处理，取消将完整回滚本次操作…')
            result=dispatch(db,Path(job['project']),operation,body,lid,created)
            long_tasks.checkpoint(None,'正在校验关联并整理撤销记录…')
        committed=True
        # Retention is a post-commit housekeeping step; cancelling must not prune old backups.
        import backup_policy,logging
        for folder in job.get('backup_folders',set()):
            try:backup_policy.prune(folder)
            except Exception as error:logging.warning('Cannot prune completed task backups: %s',error)
        return result
    except BaseException:
        # connect has already rolled back and closed, so files cannot be committed references.
        if committed:raise
        for path in created:path.unlink(missing_ok=True)
        import language_exchange
        with language_exchange.LOCK:
            for token in job.get('staged',[]):language_exchange.discard(token)
        raise
    finally:
        journal.scope.reset(scope);journal.action.reset(action)

def dispatch(db,path,operation,body,lid,created):
    import server
    if operation=='analysis-run':
        import analysis_workspace
        return analysis_workspace.run(db,lid,body)
    if operation=='analysis-save':
        import analysis_workspace
        return analysis_workspace.mutate(db,lid,'save',body)
    if operation=='import':return server.import_into(db,body['title'],body.get('source',''),body['content'])
    if operation=='import-language':return languages.import_bundle(db,body['bundle'],lid)
    if operation=='language-package-import':
        import language_exchange
        source=language_exchange.staged(path,body.get('token'),'import')
        return language_exchange.import_new(db,path,source,body.get('name',''),created)
    if operation.startswith('excel-'):
        import excel_exchange
        return excel_exchange.dispatch(db,path,operation.removeprefix('excel-'),body,lid)
    for prefix,module in [('text-replace-',server.text_replace),('dictionary-replace-',server.dictionary_replace),('punctuation-',server.punctuation)]:
        if operation.startswith(prefix):return (module.preview if operation.endswith('-preview') else module.apply)(db,body,lid)
    if operation=='lexeme-auto-link':return server.lexicon.mutate(db,operation,body,lid)
    if operation=='lexeme-save':return server.lexicon.mutate(db,operation,body,lid)
    if operation=='morpheme-save':return server.morpheme_registry.mutate(db,operation,body,lid)
    if operation in ('dictionary-batch-preview','dictionary-batch-apply'):return (server.dictionary_batch.apply if operation.endswith('-apply') else server.dictionary_batch.preview)(db,lid,body)
    if operation=='dict-org-assign':return server.dictionary_organization.mutate(db,lid,'assign',body)
    if operation=='homophone-phonology-save':return server.phonology.mutate(db,lid,body)
    if operation in ('morpheme-assign','morpheme-merge'):return server.morpheme_registry.mutate(db,operation,body,lid)
    if operation=='word-transfer':return server.word_transfer.apply(db,body,lid)
    if operation.startswith('timeline-'):return server.timeline.mutate(db,lid,operation.removeprefix('timeline-'),body)
    return server.organize(db,operation,body,path.parent/'backups')
