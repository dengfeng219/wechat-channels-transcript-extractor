@echo off
chcp 65001 >nul
title Organize Episode Files
cd /d %~dp0
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem Prefer the project venv, then PATH python, then the py launcher.
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY="
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    echo.
    echo [ERROR] Python not found. Run setup_env.ps1 first.
    echo.
    pause
    exit /b 1
)

rem A folder dropped onto this .bat arrives in %* and is passed through.
"%PY%" "%~dp0tools\organize_episodes.py" %*

pause
