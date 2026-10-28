# 🎉 Smart Annual Party Lottery (星光年会大屏互动抽奖系统)

> 一个基于 **FastAPI + WebSocket + 原生前端** 构建的高性能、多端实时同步的年会大屏互动抽奖 Demo。
> 本项目不仅是传统 Web 开发，更是 **Vibe Coding (AI 辅助编程)** 的一次深度实践。

## 📸 核心预览
*(💡 建议：在这里放一张你之前录制的 GIF 动图，或者放两张大屏和手机端的截图)*

## ✨ 功能特性 (Features)

- **📱 三端分离架构**：签到端 (手机)、大屏展示端 (投影)、控制台 (管理员)，多端数据实时互通。
- **⚡ WebSocket 实时同步**：基于 WebSocket 实现毫秒级的签到新增、弹幕飘屏、抽奖指令广播。
- **🖼️ 前端 Canvas 头像压缩**：上传头像时自动等比缩放至 200x200 像素，确保上百人头像同屏渲染不卡顿。
- **🚫 防断线资格剥夺**：结合 WebSocket 生命周期，签到用户一旦关闭手机页面（断开连接），系统会实时将其从数据库和大屏剔除，防止“人不在现场却被抽中”的乌龙。
- **🛡️ 核心抽奖算法**：支持控制台配置“排除抽奖”与“内定必中”名单；支持大屏端 6 秒超长悬念滚动动画。
- **🤖 智能暖场机制**：如果现场无人发弹幕，大屏会自动读取已签到用户昵称，定期生成暖场弹幕，防止冷场。

## 🛠️ 技术栈 (Tech Stack)

- **后端**：Python 3.10+, FastAPI, Uvicorn
- **数据库**：SQLite (轻量级零配置，适合单机活动部署)
- **前端**：原生 HTML5, CSS3, Vanilla JavaScript, WebSocket API
- **部署打包**：PyInstaller (支持一键打包为 Windows 可执行文件 `.exe`)
- **开发模式**：Claude Code + DeepSeek API (Vibe Coding 辅助开发)

## 🚀 快速开始 (Quick Start)

### 1. 环境准备
确保已安装 Python 3.10 或更高版本。

### 2. 安装依赖
```bash
git clone https://github.com/你的用户名/annual-party-demo.git
cd annual-party-demo
python -m venv .venv
# Windows 激活方式: .venv\Scripts\activate
# Linux/Mac 激活方式: source .venv/bin/activate
pip install -r requirements.txt
3. 启动服务
bash

# 启动 FastAPI，监听 8000 端口
python main.py
# 或者使用 uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000

4. 访问页面

    大屏端：http://127.0.0.1:8000/screen

    控制台：http://127.0.0.1:8000/control

    签到端：手机扫描大屏二维码（请确保手机与电脑在同一局域网下）。

📦 Windows 一键打包 (Deployment)

本项目内置了打包脚本，可在 Windows 上直接打包为绿色免安装的 .exe 文件：

    双击运行 build_exe.bat。

    等待 PyInstaller 打包完成。

    在生成的 dist 目录中获取 main.exe。双击即可启动服务并自动打开大屏。

⚠️ 注意事项 (Disclaimer)

    局域网限制：Demo 默认使用局域网进行通信，请确保投屏电脑与手机处于同一 Wi-Fi 下。如果是公司内网，请确保未开启 AP 隔离。

    数据重置：为了演示纯净度，系统默认在每次启动时清空数据库（签到名单）。若需保留，请在 main.py 中修改。

    安全说明：本项目仅作为内部互动 Demo，未接入复杂的鉴权体系。请勿将控制台地址公开发布。
