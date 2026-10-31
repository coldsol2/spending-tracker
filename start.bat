@echo off
rem Run from anywhere (or double-click): always start the server in this file's folder.
cd /d "%~dp0"
echo Starting spending tracker at http://127.0.0.1:8000  (press Ctrl+C to stop)
start "" http://127.0.0.1:8000
python -m uvicorn app.main:app --reload
