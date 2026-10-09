<p align="center">
  <img src="assets/qinglu-icon.png" alt="轻录 QingLu 应用图标" width="112" height="112">
</p>

<h1 align="center">轻录 QingLu</h1>

<p align="center">
  简洁、轻巧的 Windows 录屏工具。<br>
  全屏 · 框选区域 · 指定窗口 · 电脑声音与麦克风独立控制
</p>

<p align="center">
  <a href="https://github.com/wangshen310-hub/qinglu/archive/refs/heads/main.zip">下载安装包</a> ·
  <a href="#功能">功能介绍</a> ·
  <a href="#运行">快速开始</a> ·
  <a href="使用说明.md">使用说明</a>
</p>

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

### 双击安装（推荐）

1. 点击上方 **下载安装包**（或 **Code → Download ZIP**），完整解压到一个文件夹。
2. 双击 **Install.bat**。首次安装需要联网，请等待完成。
3. 安装后自动启动，桌面会生成 **QingLu** 快捷方式。

安装器自动检测 64 位 Python 3.14；若缺少，会从 python.org 下载最新的 3.14 正式补丁版本、校验发布者签名后安装。工具安装到当前用户的 `%LOCALAPPDATA%\Programs\QingLu`，使用独立环境，不需要手动输入命令。不修改系统 PATH 或麦克风权限。当前支持 Windows x64；不支持 ARM64 安装。

已有安装重复运行会更新程序和依赖，保留 `settings.json`。更新前请先保存录制并退出应用。若安装报错，请保留窗口中的错误信息。

### 手动运行

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
