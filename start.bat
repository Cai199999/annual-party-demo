@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo ================================================
echo   星光年会 - 启动器
echo ================================================
echo.

if not exist "requirements.txt" (
    echo [错误] 未找到 requirements.txt，请确认文件完整。
    pause
    exit /b 1
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    if exist ".venv" (
        echo [提示] 检测到不可用的 .venv，正在重新创建...
        rmdir /s /q ".venv"
    )

    echo [1/3] 正在创建 Python 虚拟环境...
    python -m venv .venv
    if not exist "%VENV_PY%" (
        echo [提示] 使用 py 启动器重试...
        py -3 -m venv .venv
    )
    if not exist "%VENV_PY%" (
        echo [错误] 虚拟环境创建失败，请先安装 Python 3.10 或更高版本。
        pause
        exit /b 1
    )

    echo [2/3] 正在安装项目依赖，首次运行可能需要几分钟...
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重新运行 start.bat。
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

if not exist ".venv\Scripts\uvicorn.exe" (
    echo [提示] 检测到依赖不完整，正在补齐...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重新运行 start.bat。
        pause
        exit /b 1
    )
)

echo [3/3] 正在启动星光年会服务...
echo.
echo 本机大屏:   http://127.0.0.1:8000/screen
echo 手机签到:   http://电脑局域网IP:8000/register
echo 控制台:     http://127.0.0.1:8000/control
echo.
echo 提示: 手机和电脑需要连接同一个 Wi-Fi 或热点。
echo 关闭此窗口即可停止服务，也可以运行 stop.bat。
echo.

start "" /min cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000/screen"

uvicorn main:app --host 0.0.0.0 --port 8000

echo.
echo 服务已停止。
pause
