import runpy
from pathlib import Path
import traceback
import ctypes
try:
    runpy.run_path(str(Path(__file__).with_name('recorder.py')), run_name='__main__')
except Exception:
    ctypes.windll.user32.MessageBoxW(None, traceback.format_exc(), '轻录启动失败', 0x10)
