@echo off
rem =============================================================================
rem  Przywrocenie bazy z kopii (tryb lokalny, przenosny PostgreSQL).
rem
rem  UWAGA: operacja NADPISUJE biezaca zawartosc bazy "polsales".
rem  Uzycie:  restore-db.bat backup\polsales_2026-07-21_16-30.dump
rem  Bez argumentu skrypt pokaze liste dostepnych kopii.
rem =============================================================================
setlocal
title Restore bazy - PolSales
cd /d "%~dp0"

set "PGBIN=C:\tmp\pg16\pgsql\bin"
set "PGPORT=55432"
set "PGUSER=postgres"
set "PGDB=polsales"
set "OUTDIR=%~dp0backup"
set "DUMP=%~1"

if not exist "%PGBIN%\pg_restore.exe" (
  echo [BLAD] Nie znaleziono pg_restore w "%PGBIN%".
  pause
  exit /b 1
)

if "%DUMP%"=="" (
  echo Podaj plik kopii jako argument, np.:
  echo    restore-db.bat backup\polsales_2026-07-21_16-30.dump
  echo.
  echo Dostepne kopie:
  if exist "%OUTDIR%" (dir /b /o-d "%OUTDIR%\polsales_*.dump") else (echo   ^(brak katalogu backup^))
  echo.
  pause
  exit /b 1
)

if not exist "%DUMP%" (
  echo [BLAD] Nie znaleziono pliku: %DUMP%
  pause
  exit /b 1
)

"%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p %PGPORT% >nul 2>&1
if errorlevel 1 (
  echo [BLAD] Baza nie odpowiada na porcie %PGPORT%. Uruchom ja najpierw.
  pause
  exit /b 1
)

echo.
echo ==========================================================
echo   UWAGA: przywrocenie NADPISZE obecne dane w bazie "%PGDB%".
echo   Plik: %DUMP%
echo ==========================================================
set /p CONFIRM="Wpisz TAK aby kontynuowac: "
if /i not "%CONFIRM%"=="TAK" (
  echo Przerwano - nic nie zmieniono.
  pause
  exit /b 0
)

echo.
echo Zamknij panel (API/worker), zeby zwolnic polaczenia do bazy.
echo Przywracam...

rem --clean --if-exists usuwa istniejace obiekty przed odtworzeniem.
"%PGBIN%\pg_restore.exe" -h 127.0.0.1 -p %PGPORT% -U %PGUSER% -d %PGDB% --clean --if-exists --no-owner "%DUMP%"
if errorlevel 1 (
  echo.
  echo [UWAGA] pg_restore zglosil bledy. Czesc komunikatow o brakujacych obiektach
  echo jest normalna przy --clean; sprawdz jednak, czy panel dziala poprawnie.
  pause
  exit /b 1
)

echo.
echo Gotowe - baza przywrocona z: %DUMP%
pause
