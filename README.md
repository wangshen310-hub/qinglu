# 轻录 QingLu

一个简洁的 Windows 桌面录屏工具。圆角浮窗、电脑声音与麦克风独立控制，支持全屏、框选区域和指定窗口。

## 功能

- 全屏、确认后录制框选区域、指定窗口录制。
- 暂停/继续、MP4 保存、PNG 截图。
- 电脑声音与麦克风独立音量、独立静音，可选择麦克风设备。
- 开始录制后收缩为左上角小浮窗，红色呼吸灯表示录制，黄色表示暂停。
- 控制浮窗在桌面可见，在本工具捕获的视频和截图中排除。
- 原始分辨率、720p、1080p、1440p、4K；15/30/60 fps。
- F8 暂停/继续，F9 停止并保存；系统托盘操作。
- 设置关闭按钮行为：**退出应用**（默认）或**隐藏到托盘**。隐藏不停止录制，双击托盘图标恢复；托盘右键始终提供退出入口。

## 运行

需要 Windows 10 2004 / Windows 11、64 位 Python（本机验证为 Python 3.14）。其他系统不支持。Windows 必须允许桌面应用访问麦克风才能录入人声。

在 PowerShell 中：

```powershell
git clone https://github.com/wangshen310-hub/qinglu.git
cd qinglu
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe .\启动录屏.pyw
```

无需激活虚拟环境。首次安装需要联网下载依赖；正常录屏在本机处理，不上传录制内容。

`requirements-lock.txt` 记录 Windows / Python 3.14 下验证过的精确依赖版本，需要复现此环境时可改用该文件安装。

开始前在齿轮设置选择保存位置。默认输出到当前用户的 `Videos/轻录`，麦克风默认关闭，需勾选开启。设置写入项目目录 `settings.json`，不随源码提交。

详细操作见 [使用说明](使用说明.md)。图标为 AI 生成图像。

## 录制范围与声音

指定窗口通过 Windows Graphics Capture 捕获目标本身，被其他窗口遮挡不会把遮挡内容录进去。最小化时可能停留在最后一帧，窗口关闭时自动保存；受系统保护的窗口可能无法捕获。窗口缩放保持开始录制时的输出尺寸，按比例补边。

电脑声音来自默认播放设备的全局回录，不局限于指定窗口。麦克风与电脑声音保存为一条混合音轨。录制期间请勿切换音频设备。

输出为 H.264/AAC 有损 MP4；截图为 PNG。浮窗排除依赖 Windows 捕获排除接口，不能保证其他录屏软件或摄像机也看不到它。

## 源码结构

| 文件 | 用途 |
| --- | --- |
| `recorder_ui.py` | Tk 界面、区域/窗口选择、动画、快捷键 |
| `recorder.py` | 录制生命周期、编码、暂停分段合并 |
| `audio_inputs.py` | 双音源、独立增益与静音、混音 |
| `audio_timeline.py` | 按采集时间戳补齐静默区间 |
| `window_capture.py` | 指定 HWND 捕获和帧传输 |
| `recorder_tray.py` | Windows 系统托盘 |

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

本地还实测过窗口遮挡/移动/缩放、窗口关闭保存、麦克风及电脑声音录制、音量与静音、浮窗排除、截图和暂停继续。结果取决于设备和驱动，不代表所有机器的保证。测试录制和个人桌面素材未发布。

## 许可证与依赖

本项目源码采用 [MIT License](LICENSE)。第三方依赖保留各自的许可证，见 [THIRD_PARTY.md](THIRD_PARTY.md)。仓库不打包 Python、FFmpeg、音频驱动或第三方二进制。
