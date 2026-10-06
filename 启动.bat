@echo off
chcp 65001 >nul
title WeChat Channels Transcript Extractor
cd /d %~dp0
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if not exist .venv\Scripts\python.exe (
    echo.
    echo [First run] Installing environment, this takes a few minutes...
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -File %~dp0setup_env.ps1
    if errorlevel 1 (
        echo.
        echo Environment setup FAILED. Please check the messages above.
        pause
        exit /b 1
    )
)

.venv\Scripts\python.exe main.py
if errorlevel 1 pause
