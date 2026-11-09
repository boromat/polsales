@echo off
title Stop PostgreSQL
echo Zatrzymuje PostgreSQL (port 55432)...
"C:\tmp\pg16\pgsql\bin\pg_ctl.exe" -D "C:\tmp\pg16\data" stop -m fast
echo.
pause
