@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo ================================================
echo   星光年会 - 打包 EXE
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

    echo [1/4] 正在创建 Python 虚拟环境...
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
)

call ".venv\Scripts\activate.bat"

echo [2/4] 正在安装项目依赖...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 项目依赖安装失败。
    pause
    exit /b 1
)

echo [3/4] 正在安装 PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [错误] PyInstaller 安装失败。
    pause
    exit /b 1
)

echo [4/4] 正在打包星光年会.exe，请稍候...
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --console ^
    --name "星光年会" ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --collect-submodules uvicorn ^
    --collect-submodules websockets ^
    main.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方的 PyInstaller 日志。
    pause
    exit /b 1
)

echo.
echo ================================================
echo [完成] 程序已生成:
echo   %~dp0dist\星光年会.exe
echo.
echo 将此 exe 复制到任意可写目录后双击运行即可。
echo 首次启动时如弹出防火墙提示，请选择“允许访问”。
echo ================================================
echo.

if exist "%~dp0dist\星光年会.exe" (
    start "" explorer "%~dp0dist"
)

pause
