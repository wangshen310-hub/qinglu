"""Compact native desktop interface for QingLu. All recording stays local."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageDraw, ImageTk
from recorder import Recorder, ROOT, screen_rect
from recorder_tray import Tray

PAPER = '#fcfcfe'
INK = '#242b38'
MUTED = '#7f8797'
RED = '#fa5d61'
CONFIG = ROOT / 'settings.json'
ICON = ROOT / 'assets' / 'qinglu.ico'
DEFAULTS = dict(output=str(Path.home() / 'Videos' / '轻录'), fps=30, resolution='原始分辨率',
                sound=True, microphone=False, microphone_device='自动选择麦克风', system_volume=100, microphone_volume=100, cursor=True, countdown=3, open_after_save=False, topmost=False, close_action='退出应用')
RESOLUTIONS = ['原始分辨率', '720p', '1080p', '1440p', '2160p / 4K']


def load_settings(path=CONFIG):
    settings = DEFAULTS.copy()
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(saved, dict): return settings
        for key in settings:
            if key in saved and type(saved[key]) is type(settings[key]): settings[key] = saved[key]
        for key in ('system_volume','microphone_volume'):settings[key]=max(0,min(100,settings[key]))
        if settings['fps'] not in (15, 30, 60): settings['fps'] = 30
        if settings['resolution'] not in RESOLUTIONS: settings['resolution'] = '原始分辨率'
        if settings['countdown'] not in (0, 3, 5): settings['countdown'] = 3
        if settings['close_action'] not in ('退出应用','隐藏到托盘'):settings['close_action']='退出应用'
        if not settings['output'].strip(): settings['output'] = DEFAULTS['output']
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings, path=CONFIG):
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    pending.replace(path)


def glyph(name, size=32, color=INK):
    """Small antialiased native-control symbols; no external font dependency."""
    scale = 4
    im = Image.new('RGBA', (size*scale, size*scale))
    d = ImageDraw.Draw(im)
    unit = size*scale/32
    def pts(seq): return [(x*unit, y*unit) for x,y in seq]
    def line(seq, width=2.1): d.line(pts(seq), fill=color, width=max(1, round(width*unit)), joint='curve')
    def ellipse(box, fill=None, outline=None, width=2):
        d.ellipse(tuple(v*unit for v in box), fill=fill, outline=outline, width=round(width*unit))
    if name == 'capture':
        for seq in ([(4,12),(4,5),(11,5)],[(21,5),(28,5),(28,12)],
                    [(4,20),(4,27),(11,27)],[(21,27),(28,27),(28,20)]): line(seq)
    elif name == 'region':
        for a,b in [(5,10),(14,18),(22,27)]:
            line([(a,5),(b,5)]); line([(a,27),(b,27)])
            line([(5,a),(5,b)]); line([(27,a),(27,b)])
    elif name in ('speaker', 'muted'):
        line([(3,12),(8,12),(15,6),(15,26),(8,20),(3,20),(3,12)])
        if name == 'speaker':
            d.arc(tuple(v*unit for v in (12,7,27,25)), -55,55,fill=color,width=round(2*unit))
            d.arc(tuple(v*unit for v in (12,2,33,30)), -52,52,fill=color,width=round(2*unit))
        else:
            line([(21,12),(29,20)]); line([(29,12),(21,20)])
    elif name in ('mic','mic_off'):
        d.rounded_rectangle(tuple(v*unit for v in (11,3,21,20)),radius=5*unit,outline=color,width=round(2*unit))
        d.arc(tuple(v*unit for v in (6,9,26,25)),0,180,fill=color,width=round(2*unit))
        line([(16,25),(16,29)]);line([(10,29),(22,29)])
        if name=='mic_off':line([(3,3),(29,29)],2.5)
    elif name == 'camera':
        line([(4,10),(10,10),(12,6),(20,6),(22,10),(28,10),(28,26),(4,26),(4,10)])
        ellipse((11,12,21,22),outline=color)
    elif name == 'gear':
        points=[]
        for i in range(64):
            angle=math.tau*i/64
            radius=13 if i%8 in (1,2,3,4) else 10.2
            points.append((16+radius*math.cos(angle),16+radius*math.sin(angle)))
        line(points+[points[0]],1.8)
        ellipse((11,11,21,21),outline=color,width=1.8)
    elif name == 'pause':
        for x in (10,19): d.rounded_rectangle(tuple(v*unit for v in (x,7,x+3,25)),radius=1.5*unit,fill=color)
    elif name == 'play': d.polygon(pts([(10,6),(25,16),(10,26)]),fill=color)
    elif name == 'stop': d.rounded_rectangle(tuple(v*unit for v in (7,7,25,25)),radius=3*unit,fill=color)
    elif name == 'record': ellipse((7,7,25,25),fill=color)
    elif name == 'close':
        line([(8,8),(24,24)]); line([(24,8),(8,24)])
    elif name == 'minus': line([(7,16),(25,16)])
    elif name == 'down': line([(10,13),(16,19),(22,13)],1.8)
    return ImageTk.PhotoImage(im.resize((size,size),Image.Resampling.LANCZOS))


class RecorderApp:
    WIDTH, HEIGHT = 960, 198
    MINI_WIDTH, MINI_HEIGHT = 398, 82
    def __init__(self, root):
        self.root = root
        self.settings = load_settings()
        self.phase = 'idle'
        self.busy = False
        self.rec = None
        self.window_hwnd=None
        self.window_title=''
        self.mode = '全屏'
        self.rect = None
        self.last = None
        self.notice = '准备就绪'
        self.events = queue.Queue()
        self.elapsed = '00:00:00'
        self.hover = None
        self.dialog = None
        self.menu = None
        self.count_token = 0
        self.close_after_save = False
        self.closed = False
        self.hotkey_ids = []
        self.drag_origin = None
        self.icons = {}
        self.compact = False
        self.animating = False
        self.panel_size = (self.WIDTH,self.HEIGHT)
        self.full_position = None
        self.last_pulse = 0
        self.render_alpha = 1.0
        self.animation_token = 0
        self.screenshot_busy = False
        self.last_screenshot = None
        self.mini_hint = ''
        self.mini_hint_until = 0
        root.title('轻录 · 屏幕录制')
        root.configure(bg=PAPER)
        root.overrideredirect(True)
        root.resizable(False, False)
        sw,sh = root.winfo_screenwidth(),root.winfo_screenheight()
        root.geometry(f'{self.WIDTH}x{self.HEIGHT}+{max(0,(sw-self.WIDTH)//2)}+{max(0,(sh-self.HEIGHT)//2)}')
        if ICON.exists(): root.iconbitmap(str(ICON))
        self.canvas = tk.Canvas(root, width=self.WIDTH, height=self.HEIGHT, bg=PAPER, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.hitboxes = dict(mode=(374,68,469,166), sound=(494,68,599,166),
                             pause=(635,77,705,147), primary=(735,77,930,147),
                             settings=(789,10,833,53), minimize=(847,10,891,53), close=(902,10,946,53),
                             status=(75,147,349,180))
        self.canvas.bind('<Motion>', self.motion)
        self.canvas.bind('<Leave>', lambda e:self.set_hover(None))
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        root.bind('<Alt-F4>', lambda e:self.close())
        root.bind('<Escape>', lambda e:self.cancel_countdown())
        root.bind('<Control-comma>', lambda e:self.open_settings())
        root.bind('<Map>', lambda e:root.after(20,self.native_frame) if e.widget is root and not self.animating else None)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.update_idletasks()
        self.native_frame()
        root.attributes('-topmost', self.settings['topmost'])
        self.register_hotkeys()
        self.tray = Tray(ICON, self.events)
        self.draw()
        self.tick()

    def hwnd(self):
        u=ctypes.windll.user32
        u.GetParent.restype=wintypes.HWND
        return u.GetParent(self.root.winfo_id()) or self.root.winfo_id()

    def native_frame(self):
        if not self.root.winfo_exists(): return
        u=ctypes.windll.user32
        hwnd=self.hwnd()
        # Borderless panel still has its own taskbar button and supports restore.
        get_style=u.GetWindowLongPtrW; get_style.restype=ctypes.c_ssize_t
        get_style.argtypes=[wintypes.HWND,ctypes.c_int]
        set_style=u.SetWindowLongPtrW; set_style.restype=ctypes.c_ssize_t
        set_style.argtypes=[wintypes.HWND,ctypes.c_int,ctypes.c_ssize_t]
        set_style(hwnd,-20,(get_style(hwnd,-20)|0x00040000)&~0x00000080)
        width,height=self.panel_size
        region=ctypes.windll.gdi32.CreateRoundRectRgn(0,0,width+1,height+1,44,44)
        u.SetWindowRgn(hwnd,region,True)

    def protect_capture(self):
        u=ctypes.windll.user32
        u.SetWindowDisplayAffinity.argtypes=[wintypes.HWND,wintypes.DWORD]
        u.GetWindowDisplayAffinity.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        value=wintypes.DWORD()
        ok=u.SetWindowDisplayAffinity(self.hwnd(),0x11)
        return bool(ok and u.GetWindowDisplayAffinity(self.hwnd(),ctypes.byref(value)) and value.value==0x11)

    def transition(self,compact,done=None):
        """Fade source controls, morph the shell, then reveal destination controls.

        A single animation owns geometry; no SW_RESTORE or late full-layout swap.
        """
        self.animation_token+=1
        token=self.animation_token
        self.animating=True
        bounds=wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(self.hwnd(),ctypes.byref(bounds))
        sx,sy,sw,sh=bounds.left,bounds.top,bounds.right-bounds.left,bounds.bottom-bounds.top
        source_compact=self.compact
        tw,th=(self.MINI_WIDTH,self.MINI_HEIGHT) if compact else (self.WIDTH,self.HEIGHT)
        if compact:
            self.full_position=(sx,sy)
            area=wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x0030,0,ctypes.byref(area),0)
            tx,ty=area.left+16,area.top+16
        else:
            tx,ty=self.full_position or (sx,sy)
        tx=max(0,min(tx,self.root.winfo_screenwidth()-tw))
        ty=max(0,min(ty,self.root.winfo_screenheight()-th))
        if compact:self.root.attributes('-topmost',True)
        start=time.perf_counter()
        self.last_animation=[]
        def frame():
            if token!=self.animation_token:return
            t=min(1,(time.perf_counter()-start)/.62)
            motion=max(0,min(1,(t-.14)/.72))
            progress=1+1.5*(motion-1)**3+.5*(motion-1)**2 if motion<1 else 1
            w=max(180,round(sw+(tw-sw)*progress));h=max(64,round(sh+(th-sh)*progress))
            x=round(sx+(tx-sx)*progress);y=round(sy+(ty-sy)*progress)
            self.panel_size=(w,h)
            self.last_animation.append((time.perf_counter()-start,w,h,x,y))
            self.root.geometry(f'{w}x{h}{x:+d}{y:+d}')
            self.root.update_idletasks()
            self.native_frame()
            ctypes.windll.user32.SetWindowPos(self.hwnd(),0,x,y,w,h,0x0014)
            if t<.14:
                self.compact=source_compact
                self.render_alpha=max(0,1-t/.14)
                self.draw(force=True)
            elif t>.86:
                self.compact=compact
                self.render_alpha=min(1,(t-.86)/.14)
                self.draw(force=True)
            else:
                self.canvas.delete('all')
                self.roundbox((0,0,w,h),22,PAPER,'#e3e6ed')
            if t<1:self.root.after(12,frame)
            else:
                self.animating=False
                self.compact=compact
                self.render_alpha=1.0
                if not compact:
                    self.root.attributes('-topmost',self.settings['topmost'])
                    if not self.screenshot_busy:ctypes.windll.user32.SetWindowDisplayAffinity(self.hwnd(),0)
                self.draw()
                if done:done()
        frame()

    def draw_mini(self,w=398,h=82):
        c=self.canvas;c.delete('all')
        self.roundbox((0,0,w,h),22,PAPER,'#e3e6ed')
        # Drawing primitives for the breathing glow avoid retaining frame images.
        pulse=(math.sin(time.monotonic()*math.tau/2.1)+1)/2
        morph=0
        dotx=27+20*morph
        timerx=48+32*morph
        color='#e7ad32' if self.phase=='paused' else RED
        if self.phase not in ('recording','paused'):color='#aab2c0'
        r=11+3*pulse
        r+=8*morph
        c.create_oval(dotx-r,h/2-r,dotx+r,h/2+r,fill=self.fade('#fff0d1' if self.phase=='paused' else '#ffe8e9'),outline='')
        bright=0.62+.38*pulse
        rgb=[int(color[i:i+2],16) for i in (1,3,5)]
        shade='#'+''.join(f'{round(255+(v-255)*bright):02x}' for v in rgb)
        inner=6+8*morph
        c.create_oval(dotx-inner,h/2-inner,dotx+inner,h/2+inner,fill=self.fade(shade),outline='')
        self.text(timerx,h/2-9,self.elapsed,round(18+25*morph),INK,'w','Consolas','bold')
        label='已暂停' if self.phase=='paused' else ('录制中' if self.phase=='recording' else ('保存中' if self.phase=='saving' else '准备录制'))
        if self.rec and self.rec.muted.is_set() and self.phase=='recording':label='电脑声音已静音'
        if time.monotonic()<self.mini_hint_until:label=self.mini_hint
        elif self.hover=='mic_mute':
            label='开启麦克风' if self.rec and self.rec.mic_muted.is_set() else '麦克风静音'
        elif self.hover in ('snapshot','mute'):
            label='截图' if self.hover=='snapshot' else ('取消静音' if self.rec and self.rec.muted.is_set() else '电脑声音静音')
        self.text(timerx+1,h/2+14+25*morph,label,round(11+4*morph),MUTED,'w')
        x=178;stopx=362
        self.roundbox((x-18,round(h/2)-18,x+18,round(h/2)+18),18,'#eef1f6')
        c.create_image(x,h/2,image=self.icon('play' if self.phase=='paused' else 'pause',20,INK if not self.busy else '#b8bfca'))
        self.roundbox((stopx-18,round(h/2)-18,stopx+18,round(h/2)+18),18,'#ffe8e9')
        c.create_image(stopx,h/2,image=self.icon('stop',21,RED if not self.busy else '#efa9ac'))

        for name,x in [('snapshot',224),('mute',270),('mic_mute',316)]:
            selected=self.rec and ((name=='mute' and self.rec.muted.is_set()) or (name=='mic_mute' and (self.rec.mic_muted.is_set() or not self.rec.microphone)))
            fill='#fff0d1' if selected else ('#e5eaf2' if self.hover==name else '#eef1f6')
            self.roundbox((x-18,round(h/2)-18,x+18,round(h/2)+18),18,fill)
            icon='camera' if name=='snapshot' else ('muted' if selected or not self.settings['sound'] else 'speaker')
            if name=='mic_mute':icon='mic_off' if selected else 'mic'
            c.create_image(x,h/2,image=self.icon(icon,20,INK if not (name=='snapshot' and self.screenshot_busy) else MUTED))

    def fade(self,color):
        if self.render_alpha>=.999:return color
        rgb=self.root.winfo_rgb(color);base=self.root.winfo_rgb(PAPER)
        return '#'+''.join(f'{round((b+(v-b)*self.render_alpha)/257):02x}' for v,b in zip(rgb,base))

    def icon(self,name,size=32,color=INK):
        color=self.fade(color)
        key=(name,size,color)
        if key not in self.icons: self.icons[key]=glyph(*key)
        return self.icons[key]

    def roundbox(self,box,r,fill,outline=None):
        # Supersampled capsule/background is cached and rendered without jagged edges.
        x,y,x2,y2=box
        if x or y:
            fill=self.fade(fill)
            if outline:outline=self.fade(outline)
        if self.animating:
            self.canvas.create_polygon(x+r,y,x2-r,y,x2,y,x2,y+r,x2,y2-r,x2,y2,
                x2-r,y2,x+r,y2,x,y2,x,y2-r,x,y+r,x,y,
                smooth=True,splinesteps=20,fill=fill,outline=outline or fill)
            return
        key=('box',x2-x,y2-y,r,fill,outline)
        if key not in self.icons:
            im=Image.new('RGBA',((x2-x)*3,(y2-y)*3))
            ImageDraw.Draw(im).rounded_rectangle((1,1,im.width-2,im.height-2),radius=r*3,fill=fill,outline=outline,width=3)
            self.icons[key]=ImageTk.PhotoImage(im.resize((x2-x,y2-y),Image.Resampling.LANCZOS))
        self.canvas.create_image(x,y,image=self.icons[key],anchor='nw')

    def text(self,x,y,value,size=16,color=INK,anchor='center',font='Microsoft YaHei UI',weight='normal'):
        return self.canvas.create_text(x,y,text=value,font=(font,-size,weight),fill=self.fade(color),anchor=anchor)

    def draw(self,force=False):
        if self.animating and not force:return
        if self.compact:
            self.draw_mini();return
        c=self.canvas;c.delete('all')
        self.roundbox((0,0,960,198),25,PAPER,'#e3e6ed')
        self.text(32,31,'轻录',23,'#505969','w')
        for name,x in [('settings',811),('minimize',869),('close',924)]:
            if self.hover==name: self.roundbox(self.hitboxes[name],12,'#f1f2f6')
            icon={'settings':'gear','minimize':'minus','close':'close'}[name]
            c.create_image(x,31,image=self.icon(icon,23,MUTED))
        active=self.phase in ('recording','paused','countdown','starting','saving')
        dot=RED if self.phase=='recording' else ('#eba859' if self.phase=='paused' else '#d8dde6')
        c.create_oval(33,96,61,124,fill=self.fade(dot),outline='')
        self.text(80,108,self.elapsed,43,'#111725','w','Consolas','bold')
        msg=self.notice
        if len(msg)>24: msg=msg[:23]+'…'
        self.text(80,156,msg,15,MUTED,'w')
        for x in (361,481,617): c.create_line(x,82,x,145,fill=self.fade('#e5e8ef'),width=1)
        for name,x in [('mode',422),('sound',547)]:
            if self.hover==name and self.phase=='idle': self.roundbox(self.hitboxes[name],13,'#f0f2f6')
            color=INK if self.phase=='idle' else '#838a97'
            glyphname=('capture' if self.mode=='全屏' else 'region') if name=='mode' else ('speaker' if self.settings['sound'] else 'muted')
            c.create_image(x,101,image=self.icon(glyphname,34,color))
            label=self.mode if name=='mode' else ('电脑声音' if self.settings['sound'] else '声音关闭')
            self.text(x-5 if name=='mode' else x,146,label,16,color)
            if name=='mode': c.create_image(462,146,image=self.icon('down',15,color))
        pause_enabled=self.phase in ('recording','paused') and not self.busy
        self.roundbox((635,77,705,147),35,'#e9edf3' if self.hover=='pause' and pause_enabled else '#f0f2f6','#e1e5ed')
        c.create_image(670,112,image=self.icon('play' if self.phase=='paused' else 'pause',31,INK if pause_enabled else '#c4cad4'))
        primary_label='停止' if self.phase in ('recording','paused') else ('取消' if self.phase=='countdown' else ('保存中' if self.phase=='saving' else ('启动中' if self.phase=='starting' else '开始')))
        self.roundbox((735,77,930,147),35,'#de5056' if self.hover=='primary' and not self.busy else ('#f4a0a3' if self.busy else RED))
        c.create_image(783,112,image=self.icon('stop' if active else 'record',30,'white'))
        self.text(849,112,primary_label,23,'white')
        self.text(931,173,'F8 暂停  ·  F9 保存',14,MUTED,'e')

    def target(self,x,y):
        if self.animating:return None
        if self.compact:
            for name,cx in [('pause',178),('snapshot',224),('mute',270),('mic_mute',316),('primary',362)]:
                if cx-20<=x<=cx+20 and 20<=y<=63:return name
            return None
        for name,(x1,y1,x2,y2) in self.hitboxes.items():
            if x1<=x<=x2 and y1<=y<=y2:return name
        return None

    def set_hover(self,name):
        if self.hover!=name:
            self.hover=name
            self.canvas.configure(cursor='hand2' if name else '')
            self.draw()

    def motion(self,event): self.set_hover(self.target(event.x,event.y))

    def press(self,event):
        if self.animating:return
        self.pressed=self.target(event.x,event.y)
        if self.pressed is None:
            self.drag_origin=(event.x_root-self.root.winfo_x(),event.y_root-self.root.winfo_y())

    def drag(self,event):
        if self.animating:return
        if self.drag_origin:
            ctypes.windll.user32.SetWindowPos(self.hwnd(),0,event.x_root-self.drag_origin[0],event.y_root-self.drag_origin[1],0,0,0x0015)

    def release(self,event):
        if self.animating:return
        if self.drag_origin:
            self.drag_origin=None;return
        name=self.target(event.x,event.y)
        if name!=getattr(self,'pressed',None):return
        action={'mode':self.open_mode,'sound':self.toggle_sound,'pause':self.pause_resume,
                'snapshot':self.take_screenshot,'mute':self.toggle_recording_mute,'mic_mute':self.toggle_microphone_mute,
                'primary':self.primary,'settings':self.open_settings,'minimize':self.minimize,
                'close':self.close,'status':self.open_last}
        if name in action: action[name]()

    def minimize(self): ctypes.windll.user32.ShowWindow(self.hwnd(),6)

    def restore(self):
        self.root.deiconify()
        if ctypes.windll.user32.IsIconic(self.hwnd()):ctypes.windll.user32.ShowWindow(self.hwnd(),9)
        self.root.lift()

    def toggle_recording_mute(self):
        if not self.rec or self.phase not in ('recording','paused'):return
        if not self.rec.sound:
            self.mini_hint='未开启电脑声音';self.mini_hint_until=time.monotonic()+2
        else:self.rec.set_muted(not self.rec.muted.is_set())
        self.draw()

    def toggle_microphone_mute(self):
        if not self.rec or self.phase not in ('recording','paused'):return
        if not self.rec.microphone:
            self.mini_hint='未开启麦克风';self.mini_hint_until=time.monotonic()+2
        else:self.rec.set_mic_muted(not self.rec.mic_muted.is_set())
        self.draw()

    def take_screenshot(self):
        if not self.rec or self.phase not in ('recording','paused') or self.screenshot_busy:return
        if not self.protect_capture():return
        self.screenshot_busy=True
        self.mini_hint='正在截图';self.mini_hint_until=time.monotonic()+5
        self.draw()
        recorder=self.rec
        def worker():
            try:self.events.put(('screenshot',recorder.screenshot(),None))
            except Exception as exc:self.events.put(('screenshot',None,str(exc)))
        threading.Thread(target=worker,daemon=False).start()

    def open_mode(self):
        if self.phase!='idle': return
        menu=tk.Menu(self.root,tearoff=False,font=('Microsoft YaHei UI',11),bg='white',fg=INK,
                     activebackground='#f0f2f6',activeforeground=INK,bd=1)
        self.mode_var=tk.StringVar(value=self.mode)
        menu.add_radiobutton(label='全屏',value='全屏',variable=self.mode_var,command=self.select_full)
        menu.add_radiobutton(label='框选区域',value='框选区域',variable=self.mode_var,command=lambda:self.root.after(50,self.choose_region))
        menu.add_radiobutton(label='指定窗口',value='指定窗口',variable=self.mode_var,command=lambda:self.root.after(50,self.choose_window))
        if self.rect:
            menu.add_separator()
            menu.add_command(label=f'重新框选（{self.rect[2]} × {self.rect[3]}）',command=lambda:self.root.after(50,self.choose_region))
        self.menu=menu
        try: menu.tk_popup(self.root.winfo_rootx()+373,self.root.winfo_rooty()+163)
        finally:menu.grab_release()

    def select_full(self):
        self.mode='全屏';self.notice='准备就绪';self.draw()

    def choose_window(self):
        if self.phase!='idle':return
        from window_capture import list_windows,window_rect
        win=tk.Toplevel(self.root);self.dialog=win
        win.title('轻录 · 选择窗口');win.configure(bg=PAPER);win.transient(self.root)
        win.geometry('620x420');win.resizable(True,True)
        win.columnconfigure(0,weight=1);win.rowconfigure(1,weight=1)
        # Only the list absorbs resizing. Reserve the footer's requested height
        # even after Settings increases the shared ttk button padding.
        ttk.Label(win,text='选择要录制的窗口',font=('Microsoft YaHei UI',15,'bold')).grid(row=0,column=0,sticky='w',padx=20,pady=14)
        listing=tk.Listbox(win,font=('Microsoft YaHei UI',10),exportselection=False,height=8)
        listing.grid(row=1,column=0,sticky='nsew',padx=20)
        choices=[]
        def refresh():
            choices[:]=list_windows();listing.delete(0,'end')
            for hwnd,title in choices:listing.insert('end',f'{title}  ·  {hwnd:X}')
        def confirm():
            selected=listing.curselection()
            if not selected:return
            hwnd,title=choices[selected[0]]
            try:window_rect(hwnd)
            except Exception as exc:messagebox.showerror('窗口不可用',str(exc),parent=win);return
            self.window_hwnd=hwnd;self.window_title=title;self.mode='指定窗口'
            self.notice='窗口 · '+title;self.draw();win.destroy()
        row=ttk.Frame(win);row.grid(row=2,column=0,sticky='ew',padx=20,pady=(14,18))
        style=ttk.Style(win)
        style.configure('WindowPicker.TButton',font=('Microsoft YaHei UI',10),padding=(14,8))
        ttk.Button(row,text='刷新列表',command=refresh,style='WindowPicker.TButton').pack(side='left')
        ttk.Button(row,text='确认窗口',command=confirm,style='WindowPicker.TButton').pack(side='right')
        listing.bind('<Double-Button-1>',lambda e:confirm());win.bind('<Escape>',lambda e:win.destroy())
        refresh();win.update_idletasks()
        win.minsize(max(620,win.winfo_reqwidth()),max(360,win.winfo_reqheight()))
        win.grab_set()

    def choose_region(self):
        if self.phase!='idle':return
        self.root.withdraw()
        overlay=tk.Toplevel(self.root)
        overlay.title('轻录 · 框选区域')
        overlay.overrideredirect(True)
        u=ctypes.windll.user32
        vx,vy,vw,vh=[u.GetSystemMetrics(i) for i in (76,77,78,79)]
        overlay.geometry(f'{vw}x{vh}+0+0')
        overlay.attributes('-alpha',0.32)
        overlay.attributes('-topmost',True)
        canvas=tk.Canvas(overlay,bg='#101827',cursor='crosshair',highlightthickness=0)
        canvas.pack(fill='both',expand=True)
        canvas.create_text(vw//2,70,text='拖动框选区域，再点击确认  ·  Esc 取消',fill='white',font=('Microsoft YaHei UI',-24))
        overlay.update_idletasks()
        overlay_hwnd=u.GetParent(overlay.winfo_id())
        get_style=u.GetWindowLongPtrW;set_style=u.SetWindowLongPtrW
        set_style(overlay_hwnd,-20,(get_style(overlay_hwnd,-20)|0x00040000)&~0x00000080)
        u.SetWindowPos(overlay_hwnd,-1,vx,vy,vw,vh,0x0040)
        origin=[];box=[None];label=[None];pending=[None];toolbar=[None]
        self.region_overlay=overlay
        self.region_canvas=canvas
        def clear_toolbar():
            if toolbar[0] and toolbar[0].winfo_exists():toolbar[0].destroy()
            toolbar[0]=None
        def cancel(event=None):
            clear_toolbar()
            overlay.destroy();self.restore();self.draw()
        def confirm(event=None):
            if pending[0]:
                self.rect=pending[0];self.mode='框选区域'
                self.notice=f'已确认 {self.rect[2]} × {self.rect[3]}'
                cancel()
        def reselect():
            pending[0]=None;origin.clear();clear_toolbar()
            if box[0]:canvas.delete(box[0]);box[0]=None
            if label[0]:canvas.delete(label[0]);label[0]=None
            overlay.focus_force()
        def down(event):
            clear_toolbar();pending[0]=None
            origin[:]=[event.x,event.y]
            if box[0]:canvas.delete(box[0])
            if label[0]:canvas.delete(label[0])
            box[0]=canvas.create_rectangle(event.x,event.y,event.x,event.y,outline='white',width=3)
            label[0]=canvas.create_text(event.x,event.y-20,text='',fill='white',font=('Consolas',-20))
        def move(event):
            if origin:
                canvas.coords(box[0],*origin,event.x,event.y)
                canvas.itemconfigure(label[0],text=f'{abs(event.x-origin[0])} × {abs(event.y-origin[1])}')
        def up(event):
            if not origin:return
            x,y=min(origin[0],event.x),min(origin[1],event.y)
            w,h=abs(event.x-origin[0]),abs(event.y-origin[1])
            if w>=32 and h>=32:
                pending[0]=(vx+x,vy+y,w,h)
                bar=tk.Toplevel(overlay);toolbar[0]=bar
                bar.transient(overlay)
                bar.title('确认录制区域');bar.overrideredirect(True);bar.attributes('-topmost',True)
                bar.configure(bg=PAPER)
                bar.geometry('420x62+0+0')
                tk.Label(bar,text=f'{w} × {h}',bg=PAPER,fg=INK,font=('Consolas',12)).pack(side='left',padx=(14,8))
                for text,command,bg,fg in [('确认',confirm,RED,'white'),('重选',reselect,'#eef1f6',INK),('取消',cancel,'#eef1f6',INK)]:
                    tk.Button(bar,text=text,command=command,bg=bg,fg=fg,activebackground=bg,bd=0,font=('Microsoft YaHei UI',11),padx=14,pady=7).pack(side='left',padx=4)
                bar.bind('<Return>',confirm);bar.bind('<Escape>',cancel)
                bar.update_idletasks()
                bx=max(vx,min(vx+x+w-420,vx+vw-420));by=min(vy+y+h+12,vy+vh-70)
                u.SetWindowPos(u.GetParent(bar.winfo_id()),-1,bx,by,420,62,0x0040)
                bar.focus_force()
        canvas.bind('<ButtonPress-1>',down)
        canvas.bind('<B1-Motion>',move)
        canvas.bind('<ButtonRelease-1>',up)
        overlay.bind('<Escape>',cancel)
        overlay.bind('<Return>',confirm)
        overlay.focus_force()

    def toggle_sound(self):
        if self.phase!='idle':return
        proposed=dict(self.settings,sound=not self.settings['sound'])
        try:save_settings(proposed)
        except OSError as exc:
            messagebox.showerror('无法保存设置',str(exc),parent=self.root);return
        self.settings=proposed;self.draw()

    def open_settings(self):
        if self.compact:return
        if self.dialog and self.dialog.winfo_exists():self.dialog.lift();return
        win=tk.Toplevel(self.root);self.dialog=win
        win.title('轻录 · 设置');win.configure(bg=PAPER)
        win.resizable(False,False)
        if ICON.exists():win.iconbitmap(str(ICON))
        win.geometry(f'600x860+{max(0,self.root.winfo_x()+200)}+{max(0,self.root.winfo_y()-180)}')
        win.transient(self.root)
        style=ttk.Style(win);style.theme_use('clam')
        style.configure('TFrame',background=PAPER)
        style.configure('TLabel',background=PAPER,foreground=INK,font=('Microsoft YaHei UI',10))
        style.configure('TCheckbutton',background=PAPER,foreground=INK,font=('Microsoft YaHei UI',10))
        style.map('TCheckbutton',background=[('active',PAPER)])
        if not hasattr(self,'check_images'):
            self.check_images=[]
            for checked in (False,True):
                im=Image.new('RGBA',(80,80));d=ImageDraw.Draw(im)
                d.rounded_rectangle((8,8,68,68),radius=14,fill=RED if checked else PAPER,outline=RED if checked else '#b5bdcb',width=5)
                if checked:d.line([(22,38),(33,49),(55,26)],fill='white',width=8,joint='curve')
                self.check_images.append(ImageTk.PhotoImage(im.resize((20,20),Image.Resampling.LANCZOS)))
            style.element_create('QingCheck.indicator','image',self.check_images[0],('selected',self.check_images[1]),width=25,sticky='w')
        style.layout('QingCheck.TCheckbutton',[('Checkbutton.padding',{'sticky':'nswe','children':[('QingCheck.indicator',{'side':'left','sticky':'w'}),('Checkbutton.label',{'side':'left','sticky':'nswe'})]})])
        style.configure('TButton',font=('Microsoft YaHei UI',10),padding=(12,7))
        style.configure('TCombobox',padding=5)
        frame=ttk.Frame(win,padding=26);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='录制设置',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        ttk.Label(frame,text='按你的习惯录制，设置会自动保留。',foreground=MUTED).pack(anchor='w',pady=(5,20))
        vals={k:(tk.BooleanVar(value=v) if type(v)is bool else tk.StringVar(value=str(v))) for k,v in self.settings.items()}
        widgets=[]
        def field(label,key,options):
            row=ttk.Frame(frame);row.pack(fill='x',pady=6)
            ttk.Label(row,text=label,width=14).pack(side='left')
            control=ttk.Combobox(row,textvariable=vals[key],values=options,state='readonly',width=24)
            control.pack(side='right');widgets.append(control)
        field('录制帧率','fps',['15','30','60'])
        field('分辨率','resolution',RESOLUTIONS)
        field('开始倒计时（秒）','countdown',['0','3','5'])
        field('点击关闭按钮时','close_action',['退出应用','隐藏到托盘'])
        from recorder import pa
        from audio_inputs import microphone_devices
        devices=['自动选择麦克风'];audio=None
        try:
            audio=pa.PyAudio();devices += [d['name'] for d in microphone_devices(audio)]
        except Exception:pass
        finally:
            if audio:audio.terminate()
        field('麦克风设备','microphone_device',devices)
        options=ttk.Frame(frame);options.pack(fill='x',pady=(10,8))
        for index,(label,key) in enumerate([('录制电脑声音','sound'),('显示鼠标指针','cursor'),('保存后打开文件夹','open_after_save'),('主面板置顶','topmost'),('录制麦克风','microphone')]):
            control=ttk.Checkbutton(options,text=label,variable=vals[key],style='QingCheck.TCheckbutton');control.grid(row=index//2,column=index%2,sticky='w',padx=(0,40),pady=5);widgets.append(control)
        for label,key in [('电脑声音音量','system_volume'),('麦克风音量','microphone_volume')]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=4)
            ttk.Label(row,text=label,width=14).pack(side='left')
            number=ttk.Label(row,text=vals[key].get()+'%',width=5);number.pack(side='right')
            def change(value,k=key,n=number):
                value=round(float(value));vals[k].set(str(value));n.configure(text=f'{value}%')
            slider=ttk.Scale(row,from_=0,to=100,command=change);slider.set(int(vals[key].get()))
            slider.pack(side='left',fill='x',expand=True,padx=8);widgets.append(slider)
        ttk.Label(frame,text='两路音量独立；静音按钮只影响录制，不改变电脑音量。',foreground=MUTED,font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(4,8))
        ttk.Label(frame,text='保存位置').pack(anchor='w',pady=(9,5))
        pathrow=ttk.Frame(frame);pathrow.pack(fill='x')
        entry=ttk.Entry(pathrow,textvariable=vals['output']);entry.pack(side='left',fill='x',expand=True);widgets.append(entry)
        def browse():
            folder=filedialog.askdirectory(parent=win,initialdir=vals['output'].get() if Path(vals['output'].get()).exists() else str(Path.home()))
            if folder:vals['output'].set(folder)
        browse_button=ttk.Button(pathrow,text='选择…',command=browse);browse_button.pack(side='right',padx=(8,0));widgets.append(browse_button)
        ttk.Label(frame,text='MP4 · H.264 / AAC  |  F8 暂停或继续 · F9 保存',foreground=MUTED,font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(16,4))
        ttk.Label(frame,text='固定分辨率保持比例并补边；竖屏自动使用竖向尺寸。',foreground=MUTED,font=('Microsoft YaHei UI',9)).pack(anchor='w')
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x',pady=(14,0))
        def apply():
            data={k:v.get() for k,v in vals.items()}
            data['output']=data['output'].strip()
            if not data['output']:
                messagebox.showerror('保存位置为空','请选择视频保存文件夹。',parent=win);return
            if not Path(data['output']).is_absolute():
                messagebox.showerror('保存位置无效','请输入完整文件夹路径。',parent=win);return
            for k in ('fps','countdown','system_volume','microphone_volume'):data[k]=int(data[k])
            try:
                Path(data['output']).mkdir(parents=True,exist_ok=True)
                save_settings(data)
            except OSError as exc:
                messagebox.showerror('无法保存设置',str(exc),parent=win);return
            self.settings=data;self.root.attributes('-topmost',data['topmost'])
            self.draw();win.destroy()
        def open_folder():
            try:
                path=Path(vals['output'].get());path.mkdir(parents=True,exist_ok=True);os.startfile(str(path))
            except OSError as exc:messagebox.showerror('无法打开文件夹',str(exc),parent=win)
        ttk.Button(footer,text='打开保存文件夹',command=open_folder).pack(side='left')
        apply_button=ttk.Button(footer,text='保存设置',command=apply);apply_button.pack(side='right')
        if self.phase!='idle':
            for control in widgets:control.configure(state='disabled')
            apply_button.configure(state='disabled')
            ttk.Label(frame,text='录制结束后可修改设置',foreground=RED).pack(anchor='w',pady=6)
        win.bind('<Escape>',lambda e:win.destroy())
        win.grab_set();win.focus_force()

    def background(self,fn,action):
        self.busy=True;self.draw()
        def worker():
            try:self.events.put((action,fn(),None))
            except Exception as exc:self.events.put((action,None,str(exc)))
        threading.Thread(target=worker,daemon=False).start()

    def primary(self):
        if self.busy or self.animating or self.screenshot_busy:return
        if self.phase=='idle':self.begin()
        elif self.phase=='countdown':self.cancel_countdown()
        elif self.phase in ('recording','paused'):self.stop()

    def begin(self):
        if len(self.hotkey_ids)<2 and not self.tray.ok:
            messagebox.showerror('录制控制不可用','快捷键被其他程序占用，托盘也不可用。请关闭占用 F8 / F9 的程序后重启轻录。',parent=self.root)
            return
        if self.mode=='框选区域' and not self.rect:self.choose_region();return
        if self.mode=='指定窗口' and not self.window_hwnd:self.choose_window();return
        self.last=None;self.elapsed='00:00:00'
        self.rec=None
        self.phase='countdown';self.count_token+=1
        token=self.count_token
        def countdown(n):
            if token!=self.count_token or self.phase!='countdown':return
            if n:
                self.notice=f'{n} 秒后开始录制';self.draw()
                self.root.after(1000,countdown,n-1)
            else:
                try:
                    capture_rect=self.rect if self.mode=='框选区域' else screen_rect()
                    if self.mode=='指定窗口':
                        from window_capture import window_rect
                        capture_rect=window_rect(self.window_hwnd)
                    self.rec=Recorder(Path(self.settings['output']),capture_rect,
                                      self.settings['fps'],self.settings['sound'],20,self.settings['cursor'],self.settings['resolution'],
                                      microphone=self.settings['microphone'],system_volume=self.settings['system_volume'],
                                      microphone_volume=self.settings['microphone_volume'],
                                      microphone_device=self.settings['microphone_device'],
                                      window_hwnd=self.window_hwnd if self.mode=='指定窗口' else None)
                except Exception as exc:
                    self.phase='idle';self.notice='无法开始录制';self.draw()
                    messagebox.showerror('无法开始录制',str(exc),parent=self.root);return
                self.phase='starting';self.notice='正在启动录制'
                self.hide_and_start()
        countdown(self.settings['countdown'])

    def cancel_countdown(self):
        if self.phase=='countdown':
            self.count_token+=1;self.phase='idle';self.notice='已取消';self.draw()

    def pause_resume(self):
        if self.busy or self.animating:return
        if self.phase=='recording':
            self.notice='正在暂停';self.background(self.rec.pause,'pause')
        elif self.phase=='paused':
            self.phase='starting';self.notice='正在继续';self.hide_and_start()

    def hide_and_start(self):
        # Keep controls visible to the user, while DWM excludes this HWND from capture.
        if self.dialog and self.dialog.winfo_exists():self.dialog.destroy()
        if self.menu:
            try:self.menu.unpost()
            except tk.TclError:pass
        if not self.protect_capture():
            self.phase='idle';self.busy=False;self.notice='系统未能排除录制浮窗';self.draw()
            messagebox.showerror('无法排除浮窗','Windows 未能启用浮窗录制排除，已取消开始，避免把控制面板录进去。',parent=self.root)
            return
        self.busy=True
        if not self.compact:self.transition(True,lambda:self.background(self.rec.start,'start'))
        else:self.background(self.rec.start,'start')

    def stop(self):
        if self.busy or self.animating or self.phase not in ('recording','paused'):return
        self.phase='saving';self.notice='正在保存视频'
        self.background(self.rec.finish,'finish')

    def open_last(self):
        if self.last:
            try:os.startfile(str(self.last.parent))
            except OSError as exc:messagebox.showerror('无法打开文件夹',str(exc),parent=self.root)

    def register_hotkeys(self):
        u=ctypes.windll.user32
        for ident,key in ((81,0x77),(82,0x78)):
            if u.RegisterHotKey(None,ident,0x4000,key):self.hotkey_ids.append(ident)
        if len(self.hotkey_ids)<2:self.notice='快捷键被占用，请用面板按钮'

    def tick(self):
        msg=wintypes.MSG();u=ctypes.windll.user32
        while u.PeekMessageW(ctypes.byref(msg),None,0x0312,0x0312,1):
            if msg.wParam==81:self.pause_resume()
            elif msg.wParam==82:self.stop()
        changed=False
        while not self.events.empty():
            action,value,error=self.events.get_nowait()
            if action=='screenshot':
                self.screenshot_busy=False;changed=True
                self.last_screenshot=value
                self.mini_hint='截图失败' if error else '截图已保存'
                self.mini_hint_until=time.monotonic()+2
                if self.phase=='idle' and not self.animating:
                    ctypes.windll.user32.SetWindowDisplayAffinity(self.hwnd(),0)
                continue
            if action.startswith('tray_'):
                if action=='tray_stop':self.stop()
                elif action=='tray_pause':self.pause_resume()
                elif action=='tray_exit':
                    self.exit_app()
                    if self.closed:return
                elif action=='tray_show':self.restore()
                continue
            self.busy=False;changed=True
            if error:
                self.phase='idle';self.notice='录制异常，原始文件已保留';self.close_after_save=False;self.restore()
                if self.compact:self.transition(False)
                messagebox.showerror('录制遇到问题',f'{error}\n\n原始文件：{self.rec.work}',parent=self.root)
            elif action=='start':self.phase='recording';self.notice='正在录制'
            elif action=='pause':self.phase='paused';self.notice='已暂停'
            elif action=='finish':
                self.phase='idle';self.last=value;self.notice='已保存 · 点击打开文件夹';self.restore()
                def after_save():
                    if self.settings['open_after_save']:self.open_last()
                    if self.close_after_save:self.destroy()
                self.transition(False,after_save)
        if self.rec:
            seconds=int(self.rec.duration+(time.monotonic()-self.rec.started if self.rec.started is not None else 0))
            elapsed=f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}'
            if elapsed!=self.elapsed:self.elapsed=elapsed;changed=True
            if self.phase=='recording' and not self.busy and (self.rec.proc.poll() is not None or self.rec.audio_error or self.rec.capture_closed or (self.rec.window_frames and self.rec.window_frames.error)):self.stop()
        if changed or (self.compact and time.monotonic()-self.last_pulse>.03):
            self.last_pulse=time.monotonic();self.draw()
        self.root.after(30 if self.compact else 100,self.tick)

    def close(self):
        if self.settings['close_action']=='隐藏到托盘':
            if self.busy or self.animating or self.screenshot_busy:return
            if not self.tray.ok:
                messagebox.showerror('无法隐藏窗口','托盘图标不可用，已保留窗口。可在设置中选择退出应用。',parent=self.root);return
            if self.phase=='countdown':self.cancel_countdown()
            self.root.withdraw()
            return
        self.exit_app()

    def exit_app(self):
        if self.busy or self.animating or self.screenshot_busy:
            messagebox.showinfo('正在处理录制','请等待当前操作完成后再关闭。',parent=self.root);return
        if self.phase=='countdown':self.cancel_countdown()
        if self.phase in ('recording','paused'):
            if messagebox.askyesno('保存录制','停止并保存当前录制，然后退出？',parent=self.root):
                self.close_after_save=True;self.stop()
            return
        self.destroy()

    def destroy(self):
        self.closed=True
        self.tray.close()
        for ident in self.hotkey_ids:ctypes.windll.user32.UnregisterHotKey(None,ident)
        self.root.destroy()


def create_root():
    u=ctypes.windll.user32
    u.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    u.SetWindowPos.restype=wintypes.BOOL
    u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    try:ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:pass
    try:ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('QingLu.ScreenRecorder')
    except Exception:pass
    root=tk.Tk(useTk=False)
    if not root.tk.call('info','commands','tcl_findLibrary'):
        helper=Path(root.tk.call('info','library'))/'auto.tcl'
        if helper.exists():root.tk.call('source',str(helper))
    root.loadtk()
    return root


def launch():
    root=create_root()
    RecorderApp(root)
    root.mainloop()


if __name__=='__main__':launch()
