@echo off
rem Windows launcher: double-click. First run installs everything, then opens the report.
cd /d "%~dp0"
chcp 65001 >nul

if not exist .env (
  copy .env.example .env >nul
  echo Created the .env file. Paste your keys after SERPAPI_KEY= and ANTHROPIC_API_KEY=, save, close Notepad.
  notepad .env
)

rem A .venv copied from another folder does not work (it points to the old path): rebuild it.
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import requests, bs4, lxml, openpyxl" >nul 2>&1 || rmdir /s /q .venv
)
if not exist .venv\Scripts\python.exe (
  echo Installing, one time only...
  if exist .venv rmdir /s /q .venv
  python -m venv .venv || ( echo Python is not installed. Get it from python.org and tick "Add python.exe to PATH". & pause & exit /b 1 )
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt || ( echo Install failed, check the internet connection. & pause & exit /b 1 )
)

.venv\Scripts\python.exe run.py %*
if exist out\report.html start "" out\report.html
pause
