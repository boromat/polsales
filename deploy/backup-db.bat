@echo off
rem =============================================================================
rem  Kopia zapasowa bazy - tryb lokalny (przenosny PostgreSQL, bez Dockera).
rem  Tworzy plik backup\polsales_RRRR-MM-DD_GG-MM.dump w formacie custom (-Fc),
rem  ktory przywraca sie skryptem restore-db.bat.
rem
rem  Uruchamiaj przy zamknietym panelu albo w trakcie pracy - pg_dump robi
rem  spojny zrzut (snapshot transakcyjny), wiec nie trzeba zatrzymywac bazy.
rem =============================================================================
setlocal
title Backup bazy - PolSales
cd /d "%~dp0"

set "PGBIN=C:\tmp\pg16\pgsql\bin"
set "PGPORT=55432"
set "PGUSER=postgres"
set "PGDB=polsales"
set "OUTDIR=%~dp0backup"

rem Ile ostatnich kopii zachowac (starsze sa kasowane).
set "KEEP=14"

if not exist "%PGBIN%\pg_dump.exe" (
  echo [BLAD] Nie znaleziono pg_dump w "%PGBIN%".
  echo Uruchom najpierw: powershell -ExecutionPolicy Bypass -File deploy\run-local.ps1
  pause
  exit /b 1
)

"%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p %PGPORT% >nul 2>&1
if errorlevel 1 (
  echo [BLAD] Baza nie odpowiada na porcie %PGPORT%.
  echo Uruchom panel ^(run.bat^) albo sama baze, po czym powtorz backup.
  pause
  exit /b 1
)

if not exist "%OUTDIR%" mkdir "%OUTDIR%"

rem Data w formacie RRRR-MM-DD_GG-MM (niezalezna od ustawien regionalnych).
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm"') do set "STAMP=%%i"
set "OUTFILE=%OUTDIR%\polsales_%STAMP%.dump"

echo Tworze kopie: %OUTFILE%
"%PGBIN%\pg_dump.exe" -h 127.0.0.1 -p %PGPORT% -U %PGUSER% -d %PGDB% -Fc -f "%OUTFILE%"
if errorlevel 1 (
  echo.
  echo [BLAD] pg_dump zwrocil blad - kopia NIE powstala.
  if exist "%OUTFILE%" del "%OUTFILE%"
  pause
  exit /b 1
)

echo Gotowe.
for %%A in ("%OUTFILE%") do echo Rozmiar: %%~zA bajtow

rem --- Rotacja: zostaw %KEEP% najnowszych kopii ---
powershell -NoProfile -Command ^
  "Get-ChildItem '%OUTDIR%\polsales_*.dump' | Sort-Object LastWriteTime -Descending | Select-Object -Skip %KEEP% | Remove-Item -Force"

echo Zachowane kopie (max %KEEP%):
dir /b /o-d "%OUTDIR%\polsales_*.dump"
echo.
echo WAZNE: trzymaj kopie takze POZA tym komputerem (dysk zewnetrzny / chmura).
pause
