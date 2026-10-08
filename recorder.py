"""Windows screen recorder with WASAPI output loopback. Python 3.14."""
from __future__ import annotations
import ctypes
import datetime as dt
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import wave

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
import pyaudiowpatch as pa
import imageio_ffmpeg
from audio_timeline import AudioTimeline
from audio_inputs import AudioInputs

CREATE_NO_WINDOW = 0x08000000
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args):
    result = subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-y', *args],
                            stdin=subprocess.DEVNULL, capture_output=True, creationflags=CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[-2400:])


def screen_rect():
    u = ctypes.windll.user32
    return (0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1))


class Recorder:
    def __init__(self, output: Path, rect, fps=30, sound=True, crf=20, cursor=True, resolution='原始分辨率',
                 microphone=False, system_volume=100, microphone_volume=100, window_hwnd=None,
                 microphone_device='自动选择麦克风'):
        output.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.destination = output / f'录屏_{stamp}.mp4'
        self.work = output / f'.录屏缓存_{stamp}'
        self.work.mkdir()
        self.rect, self.fps, self.sound = rect, fps, sound
        self.crf, self.cursor = int(crf), bool(cursor)
        self.resolution = resolution
        targets = {'720p': (1280,720), '1080p': (1920,1080), '1440p': (2560,1440), '2160p / 4K': (3840,2160)}
        self.video_filter = 'pad=ceil(iw/2)*2:ceil(ih/2)*2'
        if resolution in targets:
            tw,th = targets[resolution]
            if rect[3] > rect[2]: tw,th = th,tw
            self.video_filter = (f'scale={tw}:{th}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                                 f'pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2')
        self.parts = []
        self.proc = None
        self.audio = self.stream = self.wav = None
        self.audio_timeline = None
        self.sync_segments = []
        self.audio_error = None
        self.device_name = ''
        self.duration = 0.0
        self.started = None
        self.muted = threading.Event()
        self.mic_muted = threading.Event()
        self.microphone = bool(microphone)
        self.microphone_device=microphone_device
        self.system_volume = max(0,min(100,int(system_volume)))
        self.microphone_volume = max(0,min(100,int(microphone_volume)))
        self.window_hwnd = window_hwnd
        self.window_frames = None
        self.inputs = None
        if window_hwnd:
            from window_capture import window_identity
            self.window_pid = window_identity(window_hwnd)

    @property
    def capture_closed(self):
        return bool(self.window_frames and self.window_frames.ended.is_set())

    def set_mic_muted(self, muted):
        if muted:self.mic_muted.set()
        else:self.mic_muted.clear()

    def set_muted(self, muted):
        if muted: self.muted.set()
        else: self.muted.clear()

    def screenshot(self):
        stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        path = self.destination.parent / f'截图_{stamp}.png'
        if self.window_frames:
            self.window_frames.screenshot(path)
        elif self.window_hwnd:
            from window_capture import WindowFrames
            frames=WindowFrames(self.window_hwnd,self.cursor,self.fps)
            try:frames.open();frames.screenshot(path)
            finally:frames.close()
        else:run_ffmpeg([*self.capture_input(),'-frames:v','1','-update','1',str(path)])
        return path

    def capture_input(self):
        # Desktop Duplication keeps pointer shape/visibility with the captured
        # desktop frame, instead of GDI's separate per-frame CopyCursor/DrawIcon.
        # Wall-clock packet timestamps preserve the WASAPI synchronization path.
        x,y,w,h = self.rect
        if self.window_hwnd:
            return ['-use_wallclock_as_timestamps','1','-f','rawvideo','-pixel_format','bgra',
                    '-video_size',f'{w}x{h}','-framerate',str(self.fps),'-i','pipe:0']
        source = (f'ddagrab=output_idx=0:draw_mouse={int(self.cursor)}:'
                  f'framerate={self.fps}:offset_x={x}:offset_y={y}:'
                  f'video_size={w}x{h}:dup_frames=1,hwdownload,format=bgra')
        return ['-use_wallclock_as_timestamps','1','-f','lavfi','-i',source]

    def start(self):
        self.index = len(self.parts)
        self.video = self.work / f'video{self.index}.mkv'
        self.audio_path = self.work / f'audio{self.index}.wav'
        self.log = open(self.work / f'capture{self.index}.log', 'wb')
        try:
            self.audio_error=None
            if self.window_hwnd:
                from window_capture import WindowFrames,window_identity
                if window_identity(self.window_hwnd)!=self.window_pid:
                    raise RuntimeError('所选窗口已关闭，请重新选择。')
                self.window_frames=WindowFrames(self.window_hwnd,self.cursor,self.fps)
                self.window_frames.open()
            if self.sound or self.microphone:self.inputs=AudioInputs(self)
            args = [FFMPEG, '-hide_banner', '-y', *self.capture_input(),
                    '-vf', self.video_filter, '-c:v', 'libx264',
                    '-preset', 'ultrafast', '-crf', str(self.crf), '-pix_fmt', 'yuv420p',
                    '-r', str(self.fps), str(self.video)]
            self.capture_wall = time.time()
            self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=self.log, creationflags=CREATE_NO_WINDOW)
            if self.window_frames:self.window_frames.write_to(self.proc,self.rect[2],self.rect[3])
            if self.inputs:self.inputs.start(self.capture_wall)
            self.started = time.monotonic()
            time.sleep(0.5)
            if self.proc.poll() is not None:
                raise RuntimeError((self.work / f'capture{self.index}.log').read_text(errors='replace')[-1800:])
        except Exception:
            if self.window_frames:self.window_frames.close(self.proc);self.window_frames=None
            self._close_audio()
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                self.proc.wait()
            self.log.close()
            raise

    def _close_audio(self):
        if self.inputs:
            self.inputs.close()
            self.audio_gap_seconds=sum(t.get('gap',0) for t in self.inputs.tracks)

    def pause(self):
        if not self.proc:
            return
        proc, self.proc = self.proc, None
        try:
            if self.window_frames:
                self.window_frames.close(proc)
                if self.window_frames.error:self.audio_error=self.window_frames.error
                self.window_frames=None
            elif proc.poll() is None:
                proc.stdin.write(b'q\n')
                proc.stdin.flush()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait()
                raise RuntimeError('录制进程未正常停止；原始文件已保留在缓存文件夹。')
        finally:
            if proc.stdin:
                proc.stdin.close()
            self._close_audio()
            self.log.close()
            self.duration += time.monotonic() - self.started
            self.started = None
        if proc.returncode or self.audio_error:
            raise RuntimeError(self.audio_error or '画面捕获异常，请查看缓存中的 capture 日志。')
        segment = self.work / f'part{self.index}.mkv'
        if self.sound or self.microphone:
            info = subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-i', str(self.video)],
                                  stdin=subprocess.DEVNULL, capture_output=True,
                                  creationflags=CREATE_NO_WINDOW, timeout=15)
            match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', info.stderr.decode(errors='replace'))
            if not match:
                raise RuntimeError('无法读取录制时长，原始片段已保留。')
            hours, minutes, seconds = map(float, match.groups())
            length = hours * 3600 + minutes * 60 + seconds
            capture_log = (self.work / f'capture{self.index}.log').read_text(errors='replace')
            start_match = re.search(r'Duration: N/A, start: ([0-9.]+)', capture_log)
            if not start_match:
                raise RuntimeError('无法读取画面采集起点，原始片段已保留。')
            video_start = float(start_match.group(1))
            offset = video_start-self.capture_wall
            self.sync_segments.append(dict(segment=self.index, video_start=video_start,
                audio_origin=self.capture_wall, video_audio_offset_seconds=offset,
                inserted_silence_seconds=self.audio_gap_seconds, duration=length))
            run_ffmpeg(['-i', str(self.video), *self.inputs.mix_args(offset), '-c:v','copy',
                        '-c:a', 'pcm_s16le', '-t', str(length), str(segment)])
        else:
            self.video.replace(segment)
        self.parts.append(segment)

    def finish(self):
        if self.proc:
            self.pause()
        if not self.parts:
            raise RuntimeError('没有可保存的录制片段。')
        manifest = self.work / 'concat.txt'
        manifest.write_text(''.join(f"file '{p.name}'\n" for p in self.parts), encoding='utf-8')
        pending = self.work / 'final.mp4'
        run_ffmpeg(['-f', 'concat', '-safe', '0', '-i', str(manifest),
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                    '-movflags', '+faststart', str(pending)])
        pending.replace(self.destination)
        # Remove only the exact temporary files created by this recording session.
        for p in self.work.iterdir():
            if p.is_file():
                p.unlink()
        self.work.rmdir()
        return self.destination


if __name__ == '__main__':
    from recorder_ui import launch
    launch()
