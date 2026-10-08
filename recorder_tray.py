"""Native Windows notification-area controls, available while the panel is hidden."""
import ctypes as C
from ctypes import wintypes as W
import threading

LRESULT=C.c_ssize_t
WNDPROC=C.WINFUNCTYPE(LRESULT,W.HWND,W.UINT,W.WPARAM,W.LPARAM)

class WNDCLASS(C.Structure):
    _fields_=[('style',W.UINT),('lpfnWndProc',WNDPROC),('cbClsExtra',C.c_int),('cbWndExtra',C.c_int),
              ('hInstance',W.HINSTANCE),('hIcon',W.HICON),('hCursor',W.HANDLE),('hbrBackground',W.HBRUSH),
              ('lpszMenuName',W.LPCWSTR),('lpszClassName',W.LPCWSTR)]

class GUID(C.Structure):
    _fields_=[('a',W.DWORD),('b',W.WORD),('c',W.WORD),('d',C.c_ubyte*8)]

class NOTIFYICONDATA(C.Structure):
    _fields_=[('cbSize',W.DWORD),('hWnd',W.HWND),('uID',W.UINT),('uFlags',W.UINT),
              ('uCallbackMessage',W.UINT),('hIcon',W.HICON),('szTip',W.WCHAR*128),
              ('dwState',W.DWORD),('dwStateMask',W.DWORD),('szInfo',W.WCHAR*256),
              ('uTimeout',W.UINT),('szInfoTitle',W.WCHAR*64),('dwInfoFlags',W.DWORD),
              ('guidItem',GUID),('hBalloonIcon',W.HICON)]

class Tray:
    def __init__(self, icon, events):
        self.icon=str(icon);self.events=events;self.hwnd=None;self.ready=threading.Event();self.ok=False
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start();self.ready.wait(3)

    def run(self):
        u=C.windll.user32;s=C.windll.shell32;k=C.windll.kernel32
        u.DefWindowProcW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];u.DefWindowProcW.restype=LRESULT
        u.CreateWindowExW.argtypes=[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]
        u.CreateWindowExW.restype=W.HWND
        u.LoadImageW.argtypes=[W.HINSTANCE,W.LPCWSTR,W.UINT,C.c_int,C.c_int,W.UINT];u.LoadImageW.restype=W.HANDLE
        u.CreatePopupMenu.restype=W.HMENU
        u.AppendMenuW.argtypes=[W.HMENU,W.UINT,C.c_size_t,W.LPCWSTR]
        u.TrackPopupMenu.argtypes=[W.HMENU,W.UINT,C.c_int,C.c_int,C.c_int,W.HWND,C.c_void_p]
        u.DestroyMenu.argtypes=[W.HMENU]
        u.DestroyIcon.argtypes=[W.HICON]
        u.DestroyWindow.argtypes=[W.HWND]
        u.SetForegroundWindow.argtypes=[W.HWND]
        k.GetModuleHandleW.restype=W.HMODULE
        nid=NOTIFYICONDATA();nid.cbSize=C.sizeof(nid)
        @WNDPROC
        def proc(hwnd,msg,wp,lp):
            if msg==0x8001:
                if lp==0x0203:
                    self.events.put(('tray_show',None,None))
                elif lp==0x0205:
                    menu=u.CreatePopupMenu()
                    for ident,label in ((1,'显示面板'),(2,'暂停 / 继续（F8）'),(3,'停止并保存（F9）'),(4,'退出应用')):
                        u.AppendMenuW(menu,0,ident,label)
                    point=W.POINT();u.GetCursorPos(C.byref(point));u.SetForegroundWindow(hwnd)
                    chosen=u.TrackPopupMenu(menu,0x0102,point.x,point.y,0,hwnd,None)
                    u.DestroyMenu(menu)
                    if chosen:self.events.put(({1:'tray_show',2:'tray_pause',3:'tray_stop',4:'tray_exit'}[chosen],None,None))
                return 0
            if msg==0x0010:
                s.Shell_NotifyIconW(2,C.byref(nid));u.DestroyWindow(hwnd);return 0
            if msg==0x0002:
                u.PostQuitMessage(0);return 0
            return u.DefWindowProcW(hwnd,msg,wp,lp)
        self.callback=proc
        wc=WNDCLASS();wc.lpfnWndProc=proc;wc.hInstance=k.GetModuleHandleW(None)
        wc.lpszClassName=f'QingLuTray_{id(self)}'
        try:
            if not u.RegisterClassW(C.byref(wc)):return
            self.hwnd=u.CreateWindowExW(0,wc.lpszClassName,'轻录托盘',0,0,0,0,0,None,None,wc.hInstance,None)
            if not self.hwnd:return
            nid.hWnd=self.hwnd;nid.uID=1;nid.uFlags=7;nid.uCallbackMessage=0x8001
            nid.hIcon=u.LoadImageW(None,self.icon,1,32,32,0x0010)
            nid.szTip='轻录 · 双击显示面板 · 右键更多操作'
            self.ok=bool(s.Shell_NotifyIconW(0,C.byref(nid)))
            self.ready.set()
            msg=W.MSG()
            while u.GetMessageW(C.byref(msg),None,0,0)>0:
                u.TranslateMessage(C.byref(msg));u.DispatchMessageW(C.byref(msg))
            if nid.hIcon:u.DestroyIcon(nid.hIcon)
        finally:self.ready.set()

    def close(self):
        if self.hwnd:
            C.windll.user32.PostMessageW(W.HWND(self.hwnd),0x0010,0,0)
