# Uruchomienie stacku LOKALNIE bez Dockera i bez uprawnień administratora (Windows).
# Używa przenośnego PostgreSQL (binaria EDB w katalogu -PgRoot, domyślnie C:\tmp\pg16 -
# bez usługi, bez admina).
#
# Docker Desktop wymaga administratora + WSL2 + restartu, więc na maszynie bez tych uprawnień
# do developmentu i weryfikacji służy ta ścieżka. Na serwerze użyj deploy/docker-compose.yml.
#
# Użycie:
#   powershell -ExecutionPolicy Bypass -File deploy\run-local.ps1            # baza + migracje + API
#   powershell -ExecutionPolicy Bypass -File deploy\run-local.ps1 -StopDb    # zatrzymaj bazę
#
# Frontend uruchom osobno:  cd frontend; npm install; npm run dev

param(
    [switch]$StopDb,
    [int]$Port = 55432,
    [string]$PgRoot = "C:\tmp\pg16",
    [string]$Db = "polsales"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$repo = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $PgRoot "pgsql\bin"
$data = Join-Path $PgRoot "data"
$log = Join-Path $PgRoot "pg.log"
$env:DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:$Port/$Db"

function Stop-Db {
    if (Test-Path (Join-Path $bin "pg_ctl.exe")) {
        & (Join-Path $bin "pg_ctl.exe") -D $data stop -m fast
    }
}

if ($StopDb) { Stop-Db; return }

# 1. Binaria Postgresa - pobierz, jeśli brak.
if (-not (Test-Path (Join-Path $bin "initdb.exe"))) {
    Write-Host "Pobieram przenośny PostgreSQL 16.9 (~300 MB)..."
    $zip = Join-Path $PgRoot "pg.zip"
    New-Item -ItemType Directory -Force $PgRoot | Out-Null
    curl.exe -L -s -o $zip "https://get.enterprisedb.com/postgresql/postgresql-16.9-1-windows-x64-binaries.zip"
    Expand-Archive -Path $zip -DestinationPath $PgRoot -Force
    Remove-Item $zip
}

# 2. initdb, jeśli brak katalogu danych.
if (-not (Test-Path $data)) {
    Write-Host "Inicjuję bazę danych..."
    & (Join-Path $bin "initdb.exe") -D $data -U postgres -A trust -E UTF8 --locale=C | Out-Null
}

# 3. Start, jeśli nie działa.
$ready = & (Join-Path $bin "pg_isready.exe") -h 127.0.0.1 -p $Port 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Uruchamiam Postgres na porcie $Port..."
    & (Join-Path $bin "pg_ctl.exe") -D $data -l $log -o "-p $Port -c listen_addresses=127.0.0.1" start
    Start-Sleep -Seconds 3
}

# 4. createdb, jeśli brak.
$exists = & (Join-Path $bin "psql.exe") -h 127.0.0.1 -p $Port -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$Db'" postgres
if ($exists -ne "1") {
    & (Join-Path $bin "createdb.exe") -h 127.0.0.1 -p $Port -U postgres $Db
    Write-Host "Utworzono bazę $Db."
}

# 5. Backend venv + zależności.
$venvPy = Join-Path $repo "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Tworzę venv i instaluję zależności backendu..."
    Push-Location (Join-Path $repo "backend")
    py -3 -m venv .venv
    & $venvPy -m pip install -q --upgrade pip
    & $venvPy -m pip install -q -e ".[dev]"
    Pop-Location
}

# 6. Migracje.
Write-Host "Uruchamiam migracje (alembic upgrade head)..."
Push-Location (Join-Path $repo "backend")
& $venvPy -m alembic upgrade head
Pop-Location

# 7. Użytkownik - utwórz, jeśli nie istnieje (login/hasło z env lub domyślne dev).
$hasUser = & (Join-Path $bin "psql.exe") -h 127.0.0.1 -p $Port -U postgres -tAc "SELECT count(*) FROM ops.users" $Db
if ($hasUser -eq "0") {
    if (-not $env:POLSALES_USERNAME) { $env:POLSALES_USERNAME = "wlasciciel" }
    if (-not $env:POLSALES_PASSWORD) { $env:POLSALES_PASSWORD = "zmien-to-haslo" }
    Push-Location (Join-Path $repo "backend")
    & $venvPy -m app.scripts.create_user
    Pop-Location
    Write-Host "Utworzono użytkownika: $($env:POLSALES_USERNAME)"
}

# 8. Start API (na pierwszym planie). Worker uruchom w osobnym oknie: python -m app.scheduler.runner
Write-Host ""
Write-Host "API startuje na http://127.0.0.1:8000  (Ctrl+C aby zatrzymać)"
Write-Host "Frontend: w osobnym oknie  ->  cd frontend; npm install; npm run dev  (http://localhost:5173)"
Write-Host "Worker:   w osobnym oknie  ->  cd backend; .\.venv\Scripts\python.exe -m app.scheduler.runner"
Write-Host ""
Push-Location (Join-Path $repo "backend")
if (-not $env:SESSION_SECRET) { $env:SESSION_SECRET = "dev-secret" }
& $venvPy -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Pop-Location
