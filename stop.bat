@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "PORT=8000"
set "KILLED="

echo ================================================
echo   星光年会 - 停止服务
echo ================================================
echo.
echo 正在查找占用 %PORT% 端口的进程...

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    if not "%%P"=="0" (
        echo 正在强制结束 PID %%P ...
        taskkill /F /T /PID %%P >nul 2>&1
        if not errorlevel 1 set "KILLED=1"
    )
)

if defined KILLED (
    echo.
    echo [完成] 星光年会服务已停止。
) else (
    echo.
    echo [提示] 未发现占用 %PORT% 端口的服务，可能已经停止。
)

echo.
pause
