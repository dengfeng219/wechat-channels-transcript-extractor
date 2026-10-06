@echo off
chcp 65001 >nul
title WeChat Channels Transcript Extractor - CLI
cd /d %~dp0
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if %~1==" (
    echo Usage:
    echo   Drag a video file onto this .bat, or run:
    echo     %~nx0 https://weixin.qq.com/sph/xxxxxxxx
    echo.
    echo Advanced options:
    echo     .venv\Scripts\python.exe -m app.cli --help
    pause
    exit /b 0
)

.venv\Scripts\python.exe -m app.cli %~1
pause
