#!/usr/bin/env bash
# Nocny backup bazy (pg_dump -Fc) + katalogu /data (załączniki maili), rotacja i kopia offsite.
#
# HARMONOGRAM (uruchamiać z crona hosta). Zainstaluj wpis jednorazowo:
#   ( crontab -l 2>/dev/null; \
#     echo '0 2 * * * /opt/polsales/deploy/backup/backup.sh >> /var/log/polsales-backup.log 2>&1' \
#   ) | crontab -
# (dostosuj ścieżkę do repo). Podgląd: `crontab -l`. Test ręczny: `./backup.sh`.
# Alternatywnie systemd timer: unit ExecStart=/opt/polsales/deploy/backup/backup.sh
# z OnCalendar=*-*-* 02:00:00.
set -euo pipefail

# Katalog compose (deploy/) - `docker compose` musi widzieć plik i sieć projektu,
# a cron startuje z pustym cwd/środowiskiem.
COMPOSE_DIR="${COMPOSE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$COMPOSE_DIR"

# Wczytaj POSTGRES_USER / POSTGRES_DB z .env obok compose - cron ich nie eksportuje.
#
# Czytamy WYŁĄCZNIE te dwa klucze i bez `source`. Plik .env jest formatem docker-compose,
# nie skryptem powłoki: `COMPANY_NAME=Twoja Firma` jest w nim całkowicie poprawne, a `source`
# widzi w tym polecenie `Firma` i przewraca backup. Ta sama pułapka dotyczy każdego hasła
# ze znakiem `$`, spacją albo apostrofem - a hasła generuje się losowo.
if [ -f "$COMPOSE_DIR/.env" ]; then
	_z_env() { sed -n "s/^$1=//p" "$COMPOSE_DIR/.env" | tail -1 | sed 's/^"\(.*\)"$/\1/'; }
	POSTGRES_USER="${POSTGRES_USER:-$(_z_env POSTGRES_USER)}"
	POSTGRES_DB="${POSTGRES_DB:-$(_z_env POSTGRES_DB)}"
fi

: "${POSTGRES_USER:?Brak POSTGRES_USER (ani w środowisku, ani w $COMPOSE_DIR/.env)}"
: "${POSTGRES_DB:?Brak POSTGRES_DB (ani w środowisku, ani w $COMPOSE_DIR/.env)}"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/polsales}"
KEEP_DAYS="${KEEP_DAYS:-14}"
APPDATA_VOLUME="${APPDATA_VOLUME:-polsales_appdata}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

# Zrzut bazy z kontenera db
docker compose exec -T db pg_dump -U "${POSTGRES_USER}" -Fc "${POSTGRES_DB}" \
	> "$BACKUP_DIR/db-$STAMP.dump"

# Archiwum katalogu danych (załączniki) z woluminu
docker run --rm -v "$APPDATA_VOLUME":/data -v "$BACKUP_DIR":/backup alpine \
	tar czf "/backup/data-$STAMP.tar.gz" -C /data .

# Rotacja lokalna
find "$BACKUP_DIR" -name 'db-*.dump' -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'data-*.tar.gz' -mtime +"$KEEP_DAYS" -delete

# Kopia offsite (skonfiguruj remote 'offsite' w rclone: rclone config)
if command -v rclone >/dev/null 2>&1; then
	rclone copy "$BACKUP_DIR" offsite:polsales-backups --max-age 25h
fi

echo "Backup zakończony: $STAMP"
