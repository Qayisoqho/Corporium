"""Early Windows startup feedback, before importing the application or WebView.

Progress counts completed phases, never an estimate of seconds remaining. The
main window is handed over only after the page explicitly reports readiness.
"""
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import re
import sys
import threading
import time

STAGES=(('正在启动运行环境','Starting the runtime'),('正在检查项目','Checking the project'),
        ('正在保存安全快照','Saving a safety snapshot'),('正在准备项目数据','Preparing project data'),
        ('正在启动本地服务','Starting the local service'),('正在打开主窗口','Opening the main window'),
        ('正在准备页面与字体','Preparing the page and fonts'))
PROJECT_STEPS=(('核对项目版本','Checking project version'),('准备语言与历史记录','Preparing languages and history'),
               ('准备词典与句子','Preparing dictionary and sentences'),('准备标注、媒体与研究工作区','Preparing annotations, media and workspaces'),
               ('准备检索与关联','Preparing search and associations'),('核对旧格式迁移','Checking format migration'))


def settings_home(argv):
    def argument(name):
        try:return argv[argv.index(name)+1]
        except (ValueError,IndexError):return None
    base=argument('--self-test') or argument('--smoke-test') or os.environ.get('LOCALAPPDATA',str(Path.home()))
    return Path(base)/('Corporium-dev' if '--dev' in argv else 'Corporium')


def preferences(value):
    value=value if isinstance(value,dict) else {}
    size=value.get('scale',1)
    size=float(size) if isinstance(size,(int,float)) and .5<=size<=3 else 1
    font=value.get('font','Segoe UI')
    if not isinstance(font,str) or len(font)>120:font='Segoe UI'
    weight=value.get('weight',400)
    weight=int(weight) if isinstance(weight,(int,float)) and 100<=weight<=900 else 400
    return dict(scale=size,font=font,weight=weight,italic=value.get('italic') is True)


class Startup:
    def __init__(self,argv):
        self.home=settings_home(argv)
        try:self.settings=json.loads((self.home/'desktop.json').read_text('utf-8'))
        except (OSError,ValueError):self.settings={}
        if not isinstance(self.settings,dict):self.settings={}
        self.english=self.settings.get('ui_language')=='en'
        self.style=preferences(self.settings.get('startup_ui'))
        self.number=1;self.detail='';self.hwnd=None;self.closed=False;self.error=False
        self.ready=threading.Event();self.started=time.perf_counter();self.events=[]
        self.mutex=None;self.thread=None
        self.title=('Corporium · Development' if self.english else 'Corporium · 开发版') if '--dev' in argv else 'Corporium'
        self.splash_title=self.title+(' — Starting' if self.english else ' — 正在启动')
        self.smoke='--smoke-test' in argv
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateMutexW.restype=W.HANDLE
        self.kernel.CreateMutexW.argtypes=(W.LPVOID,W.BOOL,W.LPCWSTR)
        if not self.smoke:
            self.mutex=self.kernel.CreateMutexW(None,False,'Local\\CorporiumDesktop'+('Dev' if '--dev' in argv else ''))
            if ctypes.get_last_error()==183:
                user=ctypes.WinDLL('user32',use_last_error=True)
                user.FindWindowW.restype=W.HWND;user.FindWindowW.argtypes=(W.LPCWSTR,W.LPCWSTR)
                user.ShowWindow.argtypes=(W.HWND,ctypes.c_int);user.SetForegroundWindow.argtypes=(W.HWND,)
                for title in (self.splash_title,self.title,'Corporium · Development','Corporium · 开发版'):
                    hwnd=user.FindWindowW(None,title)
                    if hwnd:user.ShowWindow(hwnd,9);user.SetForegroundWindow(hwnd);break
                self.release();raise SystemExit(0)
        self.thread=threading.Thread(target=self.run,name='startup-window',daemon=True)
        self.thread.start();self.ready.wait(2)

    def stage(self,number,detail=''):
        if self.closed:return
        self.number=max(self.number,min(len(STAGES),number));self.detail=str(detail)
        self.events.append(dict(stage=self.number,detail=self.detail,ms=round((time.perf_counter()-self.started)*1000)))
        if self.hwnd:self.user.PostMessageW(self.hwnd,0x8001,0,0)

    def finish(self,state='ready'):
        if self.closed:return
        self.events.append(dict(stage=state,ms=round((time.perf_counter()-self.started)*1000)))
        self.closed=True
        if self.hwnd:self.user.PostMessageW(self.hwnd,0x8002,0,0)

    def project_progress(self,step,total):
        self.stage(4,f'{PROJECT_STEPS[step-1][self.english]} ({step}/{total})')

    def backup_progress(self,done,total):
        percent=round(100*done/max(1,total))
        self.stage(3,(f'Safety snapshot: {percent}% copied' if self.english else f'安全快照：已复制 {percent}%'))

    def release(self):
        if self.mutex:
            self.kernel.CloseHandle.argtypes=(W.HANDLE,)
            self.kernel.CloseHandle(self.mutex);self.mutex=None

    def run(self):
        try:self._window()
        except Exception:
            import logging
            logging.exception('Startup progress window failed')
        finally:self.ready.set()

    def _window(self):
        user=self.user=ctypes.WinDLL('user32',use_last_error=True)
        gdi=ctypes.WinDLL('gdi32',use_last_error=True)
        # WinForms changes process DPI awareness later. Give the early window
        # its own per-monitor context so that handoff cannot shrink its text.
        user.SetThreadDpiAwarenessContext.argtypes=(ctypes.c_void_p,)
        user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
        previous_dpi=user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        dpi=user.GetDpiForSystem()/96
        LRESULT=ctypes.c_ssize_t
        proc_type=ctypes.WINFUNCTYPE(LRESULT,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
        class Class(ctypes.Structure):
            _fields_=[('style',W.UINT),('proc',proc_type),('cls',ctypes.c_int),('win',ctypes.c_int),
                      ('instance',W.HINSTANCE),('icon',W.HICON),('cursor',W.HANDLE),('brush',W.HBRUSH),
                      ('menu',W.LPCWSTR),('name',W.LPCWSTR)]
        user.DefWindowProcW.restype=LRESULT;user.DefWindowProcW.argtypes=(W.HWND,W.UINT,W.WPARAM,W.LPARAM)
        user.CreateWindowExW.restype=W.HWND
        user.CreateWindowExW.argtypes=(W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.HWND,W.HMENU,W.HINSTANCE,W.LPVOID)
        user.SendMessageW.restype=LRESULT;user.SendMessageW.argtypes=(W.HWND,W.UINT,W.WPARAM,W.LPARAM)
        user.PostMessageW.argtypes=(W.HWND,W.UINT,W.WPARAM,W.LPARAM)
        user.SetWindowTextW.argtypes=(W.HWND,W.LPCWSTR)
        user.ShowWindow.argtypes=(W.HWND,ctypes.c_int);user.UpdateWindow.argtypes=(W.HWND,)
        user.DestroyWindow.argtypes=(W.HWND,);user.GetClientRect.argtypes=(W.HWND,ctypes.POINTER(W.RECT))
        user.MoveWindow.argtypes=(W.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.BOOL)
        user.RegisterClassW.argtypes=(ctypes.POINTER(Class),)
        user.GetSysColorBrush.argtypes=(ctypes.c_int,);user.GetSysColorBrush.restype=W.HBRUSH
        self.kernel.GetModuleHandleW.restype=W.HMODULE;self.kernel.GetModuleHandleW.argtypes=(W.LPCWSTR,)
        gdi.CreateFontW.restype=W.HFONT
        gdi.CreateFontW.argtypes=(ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.LPCWSTR)
        gdi.DeleteObject.argtypes=(W.HGDIOBJ,)
        gdi.SetBkMode.argtypes=(W.HDC,ctypes.c_int)
        controls=[];fonts=[]
        scale=self.style['scale']*dpi
        # The native bootstrap uses the shared role sizes, before CSS can load.
        css=(Path(__file__).parent/'web/ui-standards.css').read_text('utf-8')
        def role(name,fallback):
            match=re.search(r'--ui-'+name+r'-size:\s*([.\d]+)rem',css)
            return float(match[1])*16 if match else fallback
        text_px=role('text',15)*scale;help_px=role('help',14)*scale;heading_px=role('heading',18)*scale
        def layout():
            if not controls:return
            area=W.RECT();user.GetClientRect(self.hwnd,ctypes.byref(area))
            pad=round(24*dpi);w=max(1,area.right-2*pad);y=22*dpi
            for hwnd,height in zip(controls,(heading_px*1.5,text_px*3,help_px*2.5,12,help_px*3)):
                user.MoveWindow(hwnd,pad,int(y),w,int(height),True);y+=height+12*dpi
        def refresh():
            n=self.number;total=len(STAGES)
            user.SetWindowTextW(controls[1],STAGES[n-1][self.english])
            user.SetWindowTextW(controls[2],f'{n-1} of {total} phases completed · {total-n+1} remaining' if self.english else f'已完成 {n-1}/{total} 个阶段 · 剩余 {total-n+1} 个阶段')
            user.SendMessageW(controls[3],0x402,n-1,0)
            message=self.detail or ('Corporium is starting. This window will close when the page is ready.' if self.english else 'Corporium 已启动，页面准备好后会自动打开。')
            user.SetWindowTextW(controls[4],message)
        @proc_type
        def procedure(hwnd,msg,wp,lp):
            if msg==0x138:
                gdi.SetBkMode(wp,1)
                return user.GetSysColorBrush(5)
            if msg==0x8001:refresh();return 0
            if msg==0x8002:user.DestroyWindow(hwnd);return 0
            if msg==5:layout();return 0
            if msg==0x10:return 0  # Do not interrupt a project migration.
            if msg==2:user.PostQuitMessage(0);return 0
            return user.DefWindowProcW(hwnd,msg,wp,lp)
        instance=self.kernel.GetModuleHandleW(None)
        name='CorporiumStartup'+str(os.getpid())
        wc=Class(0,procedure,0,0,instance,None,None,ctypes.cast(ctypes.c_void_p(6),W.HBRUSH),None,name)
        if not user.RegisterClassW(ctypes.byref(wc)):raise ctypes.WinError(ctypes.get_last_error())
        width=int(560*dpi*min(self.style['scale'],1.3));height=int(140*dpi+heading_px*1.5+text_px*3+help_px*5.5)
        area=W.RECT()
        user.SystemParametersInfoW(48,0,ctypes.byref(area),0)
        if area.right>area.left:width=min(width,area.right-area.left)
        x=max(area.left,area.left+(area.right-area.left-width)//2);y=max(area.top,area.top+(area.bottom-area.top-height)//2)
        self.hwnd=user.CreateWindowExW(0,name,self.splash_title,0x00CA0000,x,y,width,height,None,None,instance,None)
        if not self.hwnd:raise ctypes.WinError(ctypes.get_last_error())
        user.GetSystemMenu.argtypes=(W.HWND,W.BOOL);user.GetSystemMenu.restype=W.HMENU
        user.EnableMenuItem.argtypes=(W.HMENU,W.UINT,W.UINT)
        user.EnableMenuItem(user.GetSystemMenu(self.hwnd,False),0xF060,1)
        ctypes.WinDLL('comctl32').InitCommonControls()
        for i,(caption,pixels) in enumerate((('Corporium',heading_px),('',text_px),('',help_px),('',help_px),('',help_px))):
            hwnd=user.CreateWindowExW(0,'msctls_progress32' if i==3 else 'STATIC',caption,0x50000000,0,0,1,1,self.hwnd,None,instance,None)
            controls.append(hwnd)
            font=gdi.CreateFontW(-round(pixels),0,0,0,400 if i==0 else self.style['weight'],int(i!=0 and self.style['italic']),0,0,1,0,0,5,0,'Junicode' if i==0 else self.style['font'])
            fonts.append(font);user.SendMessageW(hwnd,0x30,font,1)
        user.SendMessageW(controls[3],0x406,0,len(STAGES))
        layout();refresh();user.ShowWindow(self.hwnd,5);user.UpdateWindow(self.hwnd)
        self.events.append(dict(stage='visible',ms=round((time.perf_counter()-self.started)*1000)))
        self.ready.set()
        message=W.MSG()
        while user.GetMessageW(ctypes.byref(message),None,0,0)>0:
            user.TranslateMessage(ctypes.byref(message));user.DispatchMessageW(ctypes.byref(message))
        for font in fonts:gdi.DeleteObject(font)
        self.hwnd=None
        user.SetThreadDpiAwarenessContext(previous_dpi)


def begin(argv):
    if sys.platform!='win32' or '--self-test' in argv:return None
    return Startup(argv)
