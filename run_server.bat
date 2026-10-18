@echo off
chcp 65001 >nul
echo ===================================================
echo   ForteBank Datathon 26 - Cash Compliance AI
echo   UI + Jury API Server: http://localhost:8000
echo   Default X-API-Key:    forte-datathon-2026-key
echo ===================================================
cd /d "%~dp0backend"
"..\venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
