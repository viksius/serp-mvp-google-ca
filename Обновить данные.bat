@echo off
rem One-click launcher for managers. ASCII only on purpose: Windows cmd breaks on non-English text inside .bat files.
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
title Update data

if not exist .env (
  copy .env.example .env >nul
  echo Created the .env file. Paste your keys, save, close Notepad.
  notepad .env
)
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import requests, bs4, lxml, openpyxl" >nul 2>&1 || rmdir /s /q .venv
)
if not exist .venv\Scripts\python.exe (
  echo First start: installing what is needed, 1-2 minutes...
  if exist .venv rmdir /s /q .venv
  python -m venv .venv || ( echo Python is not installed. Get it from python.org and tick "Add python.exe to PATH". & pause & exit /b 1 )
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt || ( echo Install failed, check the internet connection. & pause & exit /b 1 )
)

.venv\Scripts\python.exe update.py
echo.
pause
