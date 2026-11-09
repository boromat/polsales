@echo off
title API - PolSales
cd /d "%~dp0..\backend"
set "DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/polsales"
set "SESSION_SECRET=dev-secret"
rem Polskie znaki w logach musza przezyc przekierowanie do pliku (bez tego cp1252 psuje tekst).
set "PYTHONIOENCODING=utf-8"
echo ==========================================================
echo   Backend API   http://127.0.0.1:8000    Ctrl+C aby zatrzymac
echo ==========================================================
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
echo.
echo API zatrzymane. Zamknij okno.
pause
