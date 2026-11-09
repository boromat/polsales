@echo off
title Worker - PolSales
cd /d "%~dp0..\backend"
set "DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/polsales"
set "SESSION_SECRET=dev-secret"
rem Polskie znaki w logach musza przezyc przekierowanie do pliku (bez tego cp1252 psuje tekst).
set "PYTHONIOENCODING=utf-8"
echo ==========================================================
echo   Worker - kolejka ops.sync_commands + joby cykliczne
echo   Obsluguje przyciski Synchronizuj teraz / Generuj teraz
echo   Ctrl+C aby zatrzymac
echo ==========================================================
".venv\Scripts\python.exe" -m app.scheduler.runner
echo.
echo Worker zatrzymany. Zamknij okno.
pause
