@echo off
setlocal
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer, then run this file again.
  pause
  exit /b 1
)

if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

if not exist .env (
  copy .env.example .env
  echo Created .env. Add your API keys to .env, then restart this script.
)

streamlit run app.py
pause
