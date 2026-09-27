@echo off
rem ============================================================
rem  py-music-dl 一键启动脚本 (Windows 10 / 11)
rem  注: 脚本依赖 chcp 65001 + UTF-8 编码，Windows 7/8 存在批处理内
rem      切换代码页导致解析错位的已知问题，故仅承诺 Win10/11。
rem  用法: start.bat [选项] [-- 透传给 gui.py 的参数]
rem ============================================================
setlocal enableextensions
chcp 65001 >nul
title py-music-dl 启动器

set "CHECK_ONLY=0"
set "PASS="

rem ---------- 参数解析 ----------
:parse
if "%~1"=="" goto parse_done
if /I "%~1"=="-h" goto showhelp
if /I "%~1"=="--help" goto showhelp
if /I "%~1"=="--check" (
    set "CHECK_ONLY=1"
    shift
    goto parse
)
if /I "%~1"=="--demo" (
    set "PASS=%PASS% --demo"
    shift
    goto parse
)
if /I "%~1"=="--" (
    shift
    goto passthrough
)
echo [x] 未知参数: %~1
echo.
set "PARSE_ERR=1"
goto showhelp

:passthrough
set "PASS=%PASS% %~1"
shift
if not "%~1"=="" goto passthrough

:parse_done
rem ---------- 定位项目根目录（脚本所在目录）----------
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
for %%I in ("%ROOT%") do set "ROOT=%%~fI"

set "ENTRY=%ROOT%\gui.py"
set "REQ_FILE=%ROOT%\requirements.txt"
if not exist "%ENTRY%" (
    echo [x] 未找到主程序 %ENTRY%
    goto fail
)

rem ---------- 环境变量 ----------
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"
if defined PYTHONPATH (
    set "PYTHONPATH=%ROOT%;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%ROOT%"
)

rem ---------- 1. 定位 Python（优先项目虚拟环境）----------
set "PY="
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"

if not defined PY (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%I"
    )
)
if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%I in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%I"
    )
)

if not defined PY (
    echo [x] 未找到 Python（要求 Python 3.10+）。
    echo     请从 https://www.python.org/downloads/ 安装，安装时勾选 "Add python.exe to PATH"。
    echo     Tkinter 已包含在官方安装包中。
    goto fail
)
rem 读取 Python 版本号，与 start.sh 输出保持一致（"Python x.y.z" 取第 2 列）
set "PY_VER="
for /f "tokens=2" %%V in ('"%PY%" --version 2^>^&1') do set "PY_VER=%%V"
echo [*] Python: %PY% (%PY_VER%)

rem ---------- 2. 版本检查 ----------
"%PY%" -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [x] Python 版本过低，需要 3.10 或更高版本。
    echo     当前版本:
    "%PY%" --version
    goto fail
)
echo [OK] Python 版本满足要求（^>= 3.10）

rem ---------- 3. Tkinter 检查 ----------
"%PY%" -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [x] Tkinter 不可用（GUI 必需）。
    echo     请重新安装官方 Python 安装包并勾选 "tcl/tk and IDLE" 组件。
    goto fail
)
echo [OK] Tkinter 可用

rem ---------- 4. 业务依赖检查 ----------
"%PY%" -c "import importlib.util,sys;sys.exit(0 if all(importlib.util.find_spec(m) for m in ('requests','bs4','lxml')) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [!] 缺少运行依赖（requests / beautifulsoup4 / lxml）。
    echo.
    echo     请按以下步骤安装（推荐虚拟环境）:
    echo.
    echo       py -3 -m venv .venv
    echo       .venv\Scripts\activate
    echo       pip install -r "%REQ_FILE%"
    echo.
    echo     安装完成后重新运行 start.bat
    goto fail
)
echo [OK] 依赖检查通过（requests / beautifulsoup4 / lxml）

if "%CHECK_ONLY%"=="1" (
    echo [OK] 环境检查全部通过。
    exit /b 0
)

rem ---------- 5. 启动 ----------
echo [*] 启动 py-music-dl …（Ctrl+C 退出）
pushd "%ROOT%"
"%PY%" "%ENTRY%" %PASS%
set "RC=%errorlevel%"
popd
exit /b %RC%

rem ---------- 帮助 ----------
:showhelp
echo.
echo py-music-dl 启动器 (Windows)
echo.
echo 用法:
echo   start.bat [选项] [-- ^<gui.py 参数^>]
echo.
echo 选项:
echo   -h, --help   显示本帮助信息
echo   --check      仅检查运行环境与依赖，不启动程序
echo   --demo       以设计预览模式启动（演示数据）
echo.
echo 示例:
echo   start.bat               启动 GUI
echo   start.bat --demo        启动设计预览
echo   start.bat --check       检查 Python / Tk / 依赖是否就绪
echo.
echo 透传参数需放在 -- 之后，例如:
echo   start.bat -- --demo
echo.
if defined PARSE_ERR (
    set "PARSE_ERR="
    exit /b 2
)
exit /b 0

:fail
echo.
echo 启动失败，请根据上方提示排查。
pause
exit /b 1
