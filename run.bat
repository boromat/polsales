@echo off
setlocal
title PolSales - launcher
cd /d "%~dp0"

rem === Sciezki przenosnego PostgreSQL (bez Dockera, bez admina) ===
set "PGBIN=C:\tmp\pg16\pgsql\bin"
set "PGDATA=C:\tmp\pg16\data"
set "PGLOG=C:\tmp\pg16\pg.log"
set "PGPORT=55432"

echo ==========================================================
echo   PolSales - uruchamianie
echo ==========================================================

if not exist "%PGBIN%\pg_ctl.exe" goto :nopg
if not exist "%~dp0backend\.venv\Scripts\python.exe" goto :novenv

echo [1/4] PostgreSQL (port %PGPORT%)...
"%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p %PGPORT% >nul 2>&1
if errorlevel 1 (
  "%PGBIN%\pg_ctl.exe" -D "%PGDATA%" -l "%PGLOG%" -o "-p %PGPORT% -c listen_addresses=127.0.0.1" start
  timeout /t 3 /nobreak >nul
) else (
  echo       juz dziala.
)

echo [2/4] Backend API - nowe okno  http://127.0.0.1:8000
start "API - PolSales" /D "%~dp0deploy" cmd /k run-api.bat

echo [3/4] Frontend - nowe okno  http://localhost:5173
start "Frontend - PolSales" /D "%~dp0deploy" cmd /k run-web.bat

echo [4/4] Worker - nowe okno  (kolejka ops.sync_commands)
start "Worker - PolSales" /D "%~dp0deploy" cmd /k run-worker.bat

echo.
echo Otwieram przegladarke za chwile...
timeout /t 6 /nobreak >nul
start "" "http://localhost:5173"

echo.
echo Gotowe.  Frontend: http://localhost:5173    API: http://127.0.0.1:8000
echo Worker: przetwarza kolejke ops.sync_commands (Synchronizuj/Generuj teraz).
echo Login: wlasciciel   (haslo ustawione przy pierwszej konfiguracji)
echo Zatrzymanie bazy: deploy\stop-db.bat
echo To okno mozna teraz zamknac.
echo.
pause
exit /b 0

:nopg
echo.
echo [BLAD] Nie znaleziono PostgreSQL w "%PGBIN%".
echo Uruchom najpierw pelna konfiguracje (pobiera baze + instaluje zaleznosci + migracje):
echo   powershell -ExecutionPolicy Bypass -File deploy\run-local.ps1
echo.
pause
exit /b 1

:novenv
echo.
echo [BLAD] Nie znaleziono srodowiska Pythona: backend\.venv
echo Uruchom najpierw:  powershell -ExecutionPolicy Bypass -File deploy\run-local.ps1
echo.
pause
exit /b 1
