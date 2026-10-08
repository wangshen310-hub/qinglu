"""HWND-targeted Windows Graphics Capture; never crop the desktop."""
import ctypes
from ctypes import wintypes as W
import threading
import time
import numpy as np
import cv2
from PIL import Image
from windows_capture import WindowsCapture

u=ctypes.windll.user32
u.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
u.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
u.IsWindow.argtypes=[W.HWND];u.IsIconic.argtypes=[W.HWND]
u.IsWindowVisible.argtypes=[W.HWND]
u.GetWindowTextLengthW.argtypes=[W.HWND]
u.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int]
u.GetWindowLongPtrW.argtypes=[W.HWND,ctypes.c_int];u.GetWindowLongPtrW.restype=ctypes.c_ssize_t

def window_identity(hwnd):
    if not u.IsWindow(hwnd):raise RuntimeError('所选窗口已关闭，请重新选择。')
    pid=W.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    return pid.value

def window_rect(hwnd):
    window_identity(hwnd)
    if u.IsIconic(hwnd):raise RuntimeError('请先恢复所选窗口，再开始录制。')
    rect=W.RECT();u.GetWindowRect(hwnd,ctypes.byref(rect))
    return rect.left,rect.top,max(2,rect.right-rect.left),max(2,rect.bottom-rect.top)

def list_windows():
    import os
    result=[]
    callback=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    @callback
    def visit(hwnd,_):
        if not u.IsWindowVisible(hwnd):return True
        if u.GetWindowLongPtrW(hwnd,-20)&0x80:return True
        n=u.GetWindowTextLengthW(hwnd)
        if not n:return True
        title=ctypes.create_unicode_buffer(n+1);u.GetWindowTextW(hwnd,title,n+1)
        pid=W.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        cloaked=W.DWORD()
        ctypes.windll.dwmapi.DwmGetWindowAttribute(W.HWND(hwnd),14,ctypes.byref(cloaked),4)
        if pid.value!=os.getpid() and not cloaked.value and not title.value.startswith('轻录 ·'):
            result.append((int(hwnd),title.value))
        return True
    u.EnumWindows(visit,0)
    return result

class WindowFrames:
    def __init__(self,hwnd,cursor,fps):
        self.hwnd=hwnd;self.fps=fps;self.latest=None;self.lock=threading.Lock()
        self.ready=threading.Event();self.ended=threading.Event();self.stop_event=threading.Event()
        self.error=None;self.writer=None;self.control=None
        self.capture=WindowsCapture(window_hwnd=hwnd,cursor_capture=cursor,draw_border=False,
                                    minimum_update_interval=max(1,1000//fps))
        @self.capture.event
        def on_frame_arrived(frame,control):
            try:
                pixels=frame.frame_buffer.copy()
                with self.lock:self.latest=pixels
                self.ready.set()
            except Exception as exc:self.error=str(exc);self.ready.set();control.stop()
        @self.capture.event
        def on_closed():self.ended.set();self.ready.set()

    def open(self):
        window_rect(self.hwnd)
        self.control=self.capture.start_free_threaded()
        if not self.ready.wait(8) or self.latest is None:
            self.close();raise RuntimeError(self.error or '无法获取所选窗口画面，请恢复窗口或选择其他窗口。')

    def write_to(self,proc,width,height):
        def write():
            start=time.monotonic();index=0
            try:
                while not self.stop_event.is_set():
                    with self.lock:frame=self.latest
                    if frame.shape[:2]!=(height,width):
                        h,w=frame.shape[:2];ratio=min(width/w,height/h)
                        nw,nh=max(1,round(w*ratio)),max(1,round(h*ratio))
                        canvas=np.zeros((height,width,4),np.uint8)
                        canvas[(height-nh)//2:(height-nh)//2+nh,(width-nw)//2:(width-nw)//2+nw]=cv2.resize(frame,(nw,nh))
                        frame=canvas
                    proc.stdin.write(frame.tobytes());proc.stdin.flush()
                    index+=1
                    # Wall-clock timestamps let the encoder fill gaps if a write
                    # stalls; never accelerate a backlog of stale frames.
                    now=time.monotonic();index=max(index,int((now-start)*self.fps))
                    self.stop_event.wait(max(0,start+index/self.fps-now))
            except Exception as exc:
                if not self.stop_event.is_set():self.error=str(exc)
            finally:
                try:proc.stdin.close()
                except OSError:pass
        self.writer=threading.Thread(target=write,name='Window video writer',daemon=False);self.writer.start()

    def screenshot(self,path):
        with self.lock:frame=self.latest.copy()
        Image.fromarray(frame[:,:,[2,1,0]]).save(path)

    def close(self,proc=None):
        self.stop_event.set()
        if self.writer:
            self.writer.join(8)
            if self.writer.is_alive() and proc:
                proc.terminate();self.writer.join(3)
        if self.control:
            self.control.stop();self.control=None
