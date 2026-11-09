@echo off
title Frontend - PolSales
cd /d "%~dp0..\frontend"
if not exist "node_modules" (
  echo Instaluje zaleznosci frontendu - pierwsze uruchomienie...
  call npm install
)
echo ==========================================================
echo   Frontend   http://localhost:5173    Ctrl+C aby zatrzymac
echo ==========================================================
call npm run dev
echo.
echo Frontend zatrzymany. Zamknij okno.
pause
