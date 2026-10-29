"""Windows shell. Project files are never stored inside the installation."""
import argparse
import ctypes
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import sys
import threading
from contextlib import closing
from http.cookies import SimpleCookie
from urllib.parse import urlparse,parse_qs
import server
from app_info import VERSION

MIN_WINDOW_SIZE=(1100,600)
ASSETS=Path(__file__).resolve().parent
LOCK=threading.RLock()

def sidebar_minimum_size(collapsed,work_width,scale=1):
    """Work-area width is physical pixels; pywebview's sizes are logical pixels."""
    width=min(MIN_WINDOW_SIZE[0],max(480,round(work_width/max(1,scale)/2))) if collapsed else MIN_WINDOW_SIZE[0]
    return width,MIN_WINDOW_SIZE[1]

class Projects:
    def __init__(self,home):
        self.home=Path(home);self.home.mkdir(parents=True,exist_ok=True)
        self.file=self.home/'desktop.json';self.current=None;self.generation='';self.startup_error=''
        try:self.settings=json.loads(self.file.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.settings={}
        if not isinstance(self.settings,dict):self.settings={}
        recent=self.settings.get('recent',[])
        self.settings['recent']=[p for p in recent if isinstance(p,str) and p.strip()][:10] if isinstance(recent,list) else []
        if not isinstance(self.settings.get('last_project'),str):self.settings.pop('last_project',None)
        if not isinstance(self.settings.get('ui_language'),str) or self.settings['ui_language'] not in server.ui_localization.SUPPORTED:self.settings.pop('ui_language',None)

    def set_ui_language(self,value):
        if server.recorder.SERVICE.busy():raise ValueError('请先停止录音，再切换界面语言')
        if not isinstance(value,str) or value not in server.ui_localization.SUPPORTED:raise ValueError('界面语言无效')
        updated={**self.settings,'ui_language':value}
        pending=self.file.with_suffix('.tmp');pending.write_text(json.dumps(updated,ensure_ascii=False),encoding='utf-8');pending.replace(self.file)
        self.settings=updated
        return {'ok':True,'ui_language':value}

    def remember(self,path):
        updated={**self.settings,'last_project':str(path),'recent':[str(path)]+[p for p in self.settings['recent'] if p!=str(path)][:9]}
        pending=self.file.with_suffix('.tmp');pending.write_text(json.dumps(updated,ensure_ascii=False),encoding='utf-8');pending.replace(self.file)
        self.settings=updated

    def restore_last(self):
        """Resume only the last successful project; never guess another project."""
        path=self.settings.get('last_project') or next(iter(self.settings['recent']),None)
        if not path:return False
        try:
            self.open(path)
            return True
        except Exception as error:
            logging.exception('Could not reopen the last project')
            self.startup_error='无法打开上次的项目：'+str(path)+'\n'+str(error)+'\n请重新选择项目，或从备份恢复。'
            return False

    def create(self,path,backup=None):
        if server.recorder.SERVICE.busy():raise ValueError('请先停止录音，再切换项目')
        path=Path(path).resolve()
        if path.exists() and any(path.iterdir()):raise ValueError('请选择一个空文件夹，新建项目不会覆盖现有文件。')
        path.mkdir(parents=True,exist_ok=True);(path/'data').mkdir(exist_ok=True)
        if backup:
            from restore_backup import restore
            restore(backup,path/'data'/'corpus.sqlite3')
        return self.open(path,new=True)

    def open(self,path,new=False):
        if server.recorder.SERVICE.busy():raise ValueError('请先停止录音，再切换项目')
        path=Path(path).resolve();dbpath=path/'data'/'corpus.sqlite3'
        if not new:
            if not dbpath.is_file():raise ValueError('该文件夹不是 Corporium 项目：未找到 data/corpus.sqlite3。请选择项目最外层文件夹。')
            with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
                names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'texts','entries'}<=names:raise ValueError('不是有效的 Corporium 数据库。')
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('数据库检查失败，请先从备份恢复。')
            # A consistent copy works even when an older browser server is still open.
            import backup_policy
            with closing(sqlite3.connect(dbpath)) as src:backup_policy.sqlite_snapshot(path/'data'/'backups',src,'desktop')
        old=server.DB
        try:
            server.DB=dbpath;server.init()
            fontdir=path/'font';fontdir.mkdir(exist_ok=True)
            bundled=ASSETS/'font'/'Junicode'
            if bundled.exists() and not (fontdir/'Junicode').exists():shutil.copytree(bundled,fontdir/'Junicode')
            self.remember(path)
        except Exception:
            server.DB=old;raise
        server.font_catalog.ROOT=fontdir;server.font_catalog._catalog=None
        self.current=path;self.generation=secrets.token_urlsafe(16);self.startup_error=''
        return self.status()

    def status(self):
        locale=self.settings.get('ui_language','zh-CN')
        return {'version':VERSION,'project':str(self.current) if self.current else None,'recent':self.settings['recent'],'startup_error':server.ui_localization.message(self.startup_error,locale),'ui_language':locale}

def make_handler(projects,token):
    class DesktopHandler(server.Handler):
        def log_message(self,fmt,*args):logging.info(fmt,*args)
        def ui_language(self):return projects.settings.get('ui_language') or super().ui_language()
        def authenticated(self):
            cookie=SimpleCookie()
            try:cookie.load(self.headers.get('Cookie',''))
            except Exception:return False
            return secrets.compare_digest(cookie.get('corporium').value if cookie.get('corporium') else '',token)
        def do_GET(self):
            # Do not hold the project lock while the player reads a large media file.
            parsed=urlparse(self.path)
            if parsed.path in ('/api/timeline-file','/api/recorder-file'):
                with LOCK:
                    q={k:v[0] for k,v in parse_qs(parsed.query).items()}
                    if not self.authenticated() or q.get('project')!=projects.generation:return self.send({'error':'项目已切换，请刷新'},409)
                    try:
                        if parsed.path=='/api/recorder-file':
                            path,name=server.recorder.SERVICE.playback(server.DB,q.get('token'))
                        else:
                            with server.connect(audit=False) as db:asset=server.timeline.media_view(db,q.get('asset'))
                            path=server.media_engine.playable(server.DB,asset,q.get('proxy')=='true')
                    except (ValueError,OSError) as error:return self.send({'error':str(error)},400)
                if isinstance(path,bytes):return server.media_engine.stream_bytes(self,path,name)
                return server.media_engine.stream_file(self,path)
            with LOCK:
                parsed=urlparse(self.path)
                if parsed.path=='/desktop-bootstrap' and secrets.compare_digest(parse_qs(parsed.query).get('token',[''])[0],token):
                    self.send_response(302);self.send_header('Set-Cookie','corporium='+token+'; HttpOnly; SameSite=Strict; Path=/');self.send_header('Location','/');self.end_headers();return
                if not self.authenticated():return self.send({'error':'需要桌面会话'},403)
                if parsed.path=='/desktop.js':return self.send((ASSETS/'web'/'desktop.js').read_bytes(),mime='text/javascript; charset=utf-8')
                if parsed.path=='/desktop-status':return self.send(projects.status())
                # Legal notices are available before choosing a project, still within the desktop session.
                if parsed.path in server.legal_notices.ASSET_PATHS|server.ui_localization.ASSET_PATHS|{'/workbench.css'}:return super().do_GET()
                if parsed.path=='/':
                    file='index.html' if projects.current else 'desktop-start.html'
                    html=(ASSETS/'web'/file).read_text(encoding='utf-8').replace('</body>','<script src="/desktop.js"></script></body>')
                    html=server.ui_localization.bootstrap_html(html,self.ui_language())
                    if projects.current:
                        project_key=hashlib.sha256(str(projects.current).casefold().encode('utf-8')).hexdigest()
                        script='<script>const desktopProjectKey='+json.dumps(project_key)+';const desktopProjectStamp='+json.dumps(projects.generation)+';const desktopFetch=window.fetch.bind(window);window.fetch=(input,init={})=>{if(typeof input==="string"&&input.startsWith("/api/")){init={...init,headers:new Headers(init.headers)};init.headers.set("X-Corporium-Project",desktopProjectStamp);}return desktopFetch(input,init);};</script>'
                        html=html.replace('<head>','<head>'+script)
                    return self.send(html,mime='text/html; charset=utf-8')
                if not projects.current:return self.send({'error':'请先打开项目'},409)
                download_current=parsed.path in ('/api/language-package-download','/api/task-download') and parse_qs(parsed.query).get('project',[''])[0]==projects.generation
                if parsed.path.startswith('/api/') and parsed.path!='/api/font-file' and not download_current and self.headers.get('X-Corporium-Project')!=projects.generation:return self.send({'error':'项目已切换，请刷新页面'},409)
                return super().do_GET()
        def do_POST(self):
            with LOCK:
                if not self.authenticated():return self.send({'error':'需要桌面会话'},403)
                if not projects.current:return self.send({'error':'请先打开项目'},409)
                if self.headers.get('X-Corporium-Project')!=projects.generation:return self.send({'error':'项目已切换，请刷新页面'},409)
                return super().do_POST()
    return DesktopHandler

class Bridge:
    def __init__(self,projects):self._projects=projects;self._window=None;self._sidebar_collapsed=False

    def set_ui_language(self,value):
        try:
            if not self._window.get_current_url().startswith(self._origin+'/'):raise ValueError('无效窗口来源')
            with LOCK:return self._projects.set_ui_language(value)
        except Exception as error:
            return {'error':server.ui_localization.message(str(error),self._ui_language())}

    def _ui_language(self):
        return getattr(self._projects,'settings',{}).get('ui_language','zh-CN')

    def _file_types(self,values):
        return tuple(server.ui_localization.message(value,self._ui_language()) for value in values)

    def _result(self,value):
        return server.ui_localization.present(value,'',self._ui_language())

    def _apply_window_minimum(self):
        from System import Action
        from System.Drawing import Size
        from System.Windows.Forms import Screen
        native=self._window.native
        result={}
        def apply():
            scale=native._scale
            minimum=sidebar_minimum_size(self._sidebar_collapsed,Screen.FromControl(native).WorkingArea.Width,scale)
            native.MinimumSize=Size(*(round(n*scale) for n in minimum))
            self._window.min_size=minimum
            result.update(min_width=minimum[0],min_height=minimum[1])
        if native.InvokeRequired:native.Invoke(Action(apply))
        else:apply()
        return result

    def set_sidebar_collapsed(self,collapsed):
        try:
            if not self._window.get_current_url().startswith(self._origin+'/'):raise ValueError('无效窗口来源')
            if type(collapsed) is not bool:raise ValueError('侧栏状态无效')
            self._sidebar_collapsed=collapsed
            return self._apply_window_minimum()
        except Exception as error:
            logging.exception('Window minimum update failed');return self._result({'error':str(error)})
    def save_task_export(self,token,name,kind):
        if kind not in ('project-backup','language-json','analysis-json','export'):return self._result({'error':'文件类型无效'})
        # pywebview's filter parser rejects hyphenated extensions; keep the
        # suggested .corporium-backup filename and validate package contents.
        types=('Corporium 备份 (*.*)',) if kind=='project-backup' else ('JSON 数据 (*.json)',) if kind in ('language-json','analysis-json') else ('Corporium 语言数据包 (*.corporium)',)
        return self._save_staged_file(token,name,kind,types)

    def save_language_package(self,token,name):
        return self._save_staged_file(token,name,'export',('Corporium 语言数据包 (*.corporium)',))

    def save_excel_export(self,token,name):
        return self._save_staged_file(token,name,'excel-export',('Excel 工作簿 (*.xlsx)',) if str(name).lower().endswith('.xlsx') else ('ZIP 压缩文件 (*.zip)',))

    def save_text_export(self,token,name):
        return self._save_staged_file(token,name,'text-export',('Typst 文本 (*.typ)',))

    def save_docx_export(self,token,name):
        return self._save_staged_file(token,name,'docx-export',('Word 文档 (*.docx)',))

    def save_recording(self,token):
        import tempfile
        import webview
        pending=None
        try:
            if not self._window.get_current_url().startswith(self._origin+'/'):raise ValueError('无效窗口来源')
            with LOCK:source,name=server.recorder.SERVICE.playback(server.DB,token)
            paths=self._window.create_file_dialog(webview.FileDialog.SAVE,save_filename=name,file_types=self._file_types(('WAV 录音 (*.wav)',)))
            if not paths:return {'cancelled':True}
            destination=Path(paths if isinstance(paths,str) else paths[0])
            if not isinstance(source,bytes) and destination.resolve()==source.resolve():raise ValueError('请选择另一个位置下载，录音原件保持不变')
            with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as stream:
                pending=Path(stream.name)
                if isinstance(source,bytes):stream.write(source)
                else:
                    with source.open('rb') as original:shutil.copyfileobj(original,stream,1024*1024)
            pending.replace(destination)
            return {'ok':True,'path':str(destination)}
        except Exception as error:return self._result({'error':str(error)})
        finally:
            if pending:pending.unlink(missing_ok=True)

    def _save_staged_file(self,token,name,kind,file_types):
        import webview
        import language_exchange
        try:
            if not self._window.get_current_url().startswith(self._origin+'/'):raise ValueError('无效窗口来源')
            with LOCK:source=language_exchange.staged(server.DB,token,kind)
            paths=self._window.create_file_dialog(webview.FileDialog.SAVE,save_filename=Path(name).name,file_types=self._file_types(file_types))
            if not paths:return {'cancelled':True}
            dest=Path(paths if isinstance(paths,str) else paths[0])
            # Write beside the selected target, then atomically replace after the native overwrite prompt.
            import tempfile
            pending=None
            try:
                with tempfile.NamedTemporaryFile(dir=dest.parent,delete=False) as f:
                    pending=Path(f.name)
                    with source.open('rb') as src:shutil.copyfileobj(src,f,1024*1024)
                pending.replace(dest)
            finally:
                if pending:pending.unlink(missing_ok=True)
            return {'ok':True,'path':str(dest)}
        except Exception as e:return self._result({'error':str(e)})

    def choose_media(self):
        import webview
        if not self._window.get_current_url().startswith(self._origin+'/'):return self._result({'error':'无效窗口来源'})
        files=self._window.create_file_dialog(webview.FileDialog.OPEN,allow_multiple=False,file_types=self._file_types(('音视频 (*.wav;*.mp3;*.flac;*.m4a;*.mp4;*.mov;*.mkv;*.avi;*.ogg;*.opus;*.webm;*.aac;*.wma;*.wmv;*.aif;*.aiff;*.m4v;*.3gp)',)))
        return {'path':files[0] if files else ''}
    def project_action(self,action,path=None):
        import webview
        try:
            if not self._window.get_current_url().startswith(self._origin+'/'):raise ValueError('无效窗口来源')
            if server.long_tasks.active(server.DB):raise ValueError('请先等待当前任务完成或取消任务，再切换项目')
            if action!='folder' and server.recorder.SERVICE.busy():raise ValueError('请先停止录音，再切换项目')
            if action=='folder':
                if self._projects.current:os.startfile(self._projects.current)
                return {'ok':True}
            backup=None
            if action=='restore':
                files=self._window.create_file_dialog(webview.FileDialog.OPEN,file_types=self._file_types(('Corporium 备份 (*.*)','旧版 JSON 备份 (*.json)','ZIP 备份包 (*.zip)')))
                if not files:return {'cancelled':True}
                backup=files[0]
            if action in ('open','new','restore'):
                paths=self._window.create_file_dialog(webview.FileDialog.FOLDER)
                if not paths:return {'cancelled':True}
                path=paths[0]
            with LOCK:
                if action in ('new','restore'):self._projects.create(path,backup)
                elif action in ('open','recent'):
                    if action=='recent' and path not in self._projects.settings.get('recent',[]):raise ValueError('不在最近项目列表中')
                    self._projects.open(path)
                else:raise ValueError('未知操作')
            return {'ok':True}
        except Exception as exc:
            logging.exception('Project action failed');return self._result({'error':str(exc)})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project');parser.add_argument('--self-test');parser.add_argument('--smoke-test');parser.add_argument('--smoke-start',action='store_true');parser.add_argument('--dev',action='store_true');args=parser.parse_args()
    if args.smoke_start and not args.smoke_test:parser.error('--smoke-start requires --smoke-test')
    app_name='Corporium-dev' if args.dev else 'Corporium'
    window_title='Corporium · 开发版' if args.dev else 'Corporium'
    home=Path(args.self_test or args.smoke_test or os.environ.get('LOCALAPPDATA',str(Path.home())))/app_name
    home.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=home/'desktop.log',level=logging.INFO,encoding='utf-8')
    if args.self_test:
        projects=Projects(home);projects.create(home/'Test project');assert server.DB.exists()
        resumed=Projects(home);assert resumed.restore_last() and resumed.current==projects.current
        assert (ASSETS/'web'/'index.html').exists()
        notices=server.legal_notices.catalog()['items']
        assert {server.legal_notices.APP_LICENSE,server.legal_notices.RUNTIME_LICENSE,server.legal_notices.NOTICES}<={n['id'] for n in notices}
        import webview
        (home/'self-test.json').write_text(json.dumps({'ok':True,'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),'python':sys.version,'project':str(projects.current),'resume':True,'license_documents':len(notices)}),encoding='utf-8');return
    mutex=None
    if not args.smoke_test:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.CreateMutexW.restype=ctypes.c_void_p
        mutex=kernel.CreateMutexW(None,False,'Local\\CorporiumDesktop'+('Dev' if args.dev else ''))
        if ctypes.get_last_error()==183:
            hwnd=ctypes.windll.user32.FindWindowW(None,window_title)
            if hwnd:ctypes.windll.user32.ShowWindow(hwnd,9);ctypes.windll.user32.SetForegroundWindow(hwnd)
            return
    projects=Projects(home)
    smoke_resumed=False
    if args.smoke_test:
        smoke_resumed=projects.restore_last()
        if not smoke_resumed and not args.smoke_start:projects.create(home/'UI test project')
    elif args.project:
        with LOCK:projects.open(args.project)
    else:
        with LOCK:projects.restore_last()
    token=secrets.token_urlsafe(32)
    http=server.ThreadingHTTPServer(('127.0.0.1',0 if args.smoke_test else (18766 if args.dev else 18765)),make_handler(projects,token));http.daemon_threads=True
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    import webview
    webview.settings['ALLOW_DOWNLOADS']=True
    bridge=Bridge(projects);bridge._origin='http://127.0.0.1:'+str(http.server_port)
    window_title=server.ui_localization.message(window_title,bridge._ui_language())
    window=webview.create_window(window_title,bridge._origin+'/desktop-bootstrap?token='+token,js_api=bridge,width=1280,height=860,min_size=MIN_WINDOW_SIZE,background_color='#ffffff',hidden=bool(args.smoke_test),text_select=True)
    bridge._window=window
    def refresh_window_minimum(*args):
        try:bridge._apply_window_minimum()
        except Exception:logging.exception('Window monitor update failed')
    window.events.shown+=refresh_window_minimum
    window.events.moved+=refresh_window_minimum
    close_state={'allowed':False,'pending':False}
    def check_close():
        try:
            if server.recorder.SERVICE.busy():
                window.evaluate_js('corporiumAlert('+json.dumps(server.ui_localization.message('请先停止录音，再关闭程序',bridge._ui_language()),ensure_ascii=False)+')')
                return
            busy=server.long_tasks.active(server.DB)
            dirty=busy or window.evaluate_js("Boolean((typeof inlineDrafts!=='undefined'&&[...inlineDrafts.values()].some(d=>d.dirty||d.saving))||window.corporiumCodesDirty?.()||window.corporiumTimelineDirty?.()||window.corporiumNotesDirty?.()||window.corporiumSurveyDirty?.()||document.querySelector('dialog[open]'))")
            if dirty:
                answer=[];answered=threading.Event()
                def receive(value):
                    answer.append(value);answered.set()
                message='当前任务仍在处理，确认取消任务并关闭？' if busy else '可能有未保存的编辑，确认关闭并放弃这些修改？'
                message=server.ui_localization.message(message,bridge._ui_language())
                window.evaluate_js('corporiumConfirm('+json.dumps(message,ensure_ascii=False)+')',receive)
                answered.wait()
                if not answer or answer[0] is not True:return
            close_state['allowed']=True;window.destroy()
        except Exception:logging.exception('Close check failed')
        finally:close_state['pending']=False
    def closing():
        if close_state['allowed']:return True
        if not close_state['pending']:
            close_state['pending']=True;threading.Thread(target=check_close,daemon=True).start()
        # Never evaluate JavaScript synchronously from the WinForms closing event.
        return False
    window.events.closing+=closing
    if args.smoke_test:
        def smoke():
            try:
                value=json.loads(window.evaluate_js("JSON.stringify({title:document.title,uiLanguage:document.documentElement.lang,interfaceLanguage:document.getElementById('interface-language')?.value,theme:document.documentElement.dataset.theme,background:getComputedStyle(document.body).backgroundColor,startup:!!document.getElementById('startup-language'),languageAtTop:document.getElementById('interface-language')?.getBoundingClientRect().top<100,home:!!document.getElementById('home-enter'),homeVisible:document.documentElement.dataset.home==='true'&&!document.getElementById('homepage').hidden,desktop:!!document.getElementById('desktop-toolbar'),licenses:!!document.getElementById('legal-notices-open'),textSelection:getComputedStyle(document.body).userSelect,buttonSelection:document.getElementById('home-enter')?getComputedStyle(document.getElementById('home-enter')).userSelect:null})"))
                value.update(version=VERSION,project=str(projects.current),resumed=smoke_resumed)
                (home/'ui-test.json').write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
            except Exception:logging.exception('UI smoke test failed')
            finally:window.destroy()
        window.events.loaded+=smoke
    try:webview.start(icon=str(ASSETS/'packaging'/'Corporium.ico'),gui='edgechromium',private_mode=False,storage_path=str(home/'webview'))
    finally:
        server.long_tasks.cancel_all()
        http.shutdown();http.server_close();thread.join(timeout=5)
        if mutex:ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mutex))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        logging.exception('Desktop startup failed')
        locale='zh-CN'
        try:
            app_name='Corporium-dev' if '--dev' in sys.argv else 'Corporium'
            settings=json.loads((Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/app_name/'desktop.json').read_text(encoding='utf-8'))
            locale=settings.get('ui_language','zh-CN')
        except (OSError,ValueError,AttributeError):pass
        message='Corporium 启动失败：\n'+str(exc)+'\n\n请查看 %LOCALAPPDATA%\\Corporium\\desktop.log。若缺少 WebView2，请重新运行安装程序。'
        ctypes.windll.user32.MessageBoxW(None,server.ui_localization.message(message,locale),'Corporium',0x10)
