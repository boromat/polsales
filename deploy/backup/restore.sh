#!/usr/bin/env bash
# Odtworzenie bazy z pliku pg_dump ORAZ (opcjonalnie) załączników /data z archiwum tar.gz.
#
# Użycie:
#   ./restore.sh /var/backups/polsales/db-STAMP.dump
#     -> odtwarza bazę; archiwum załączników szukane automatycznie jako data-STAMP.tar.gz obok dumpu
#   ./restore.sh db-STAMP.dump data-STAMP.tar.gz
#     -> jawnie wskazane archiwum załączników
#   ./restore.sh db-STAMP.dump none
#     -> pomija odtwarzanie załączników (tylko baza)
set -euo pipefail

DUMP="${1:?Podaj ścieżkę do pliku .dump}"
DATA_ARCHIVE_ARG="${2:-}"

# Katalog compose (deploy/) - potrzebny dla `docker compose` (cron/pusty cwd).
COMPOSE_DIR="${COMPOSE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$COMPOSE_DIR"

# Wczytaj POSTGRES_USER / POSTGRES_DB z .env obok compose - bez `source`, patrz backup.sh:
# .env to format docker-compose, a nie skrypt powłoki (`COMPANY_NAME=Twoja Firma` jest w nim
# poprawne i wywraca `source`). Tu boli to podwójnie: odtwarzanie odpala się wtedy, gdy coś
# już poszło nie tak, i to najgorszy moment na zagadkowy błąd składni.
if [ -f "$COMPOSE_DIR/.env" ]; then
	_z_env() { sed -n "s/^$1=//p" "$COMPOSE_DIR/.env" | tail -1 | sed 's/^"\(.*\)"$/\1/'; }
	POSTGRES_USER="${POSTGRES_USER:-$(_z_env POSTGRES_USER)}"
	POSTGRES_DB="${POSTGRES_DB:-$(_z_env POSTGRES_DB)}"
fi

: "${POSTGRES_USER:?Brak POSTGRES_USER (ani w środowisku, ani w $COMPOSE_DIR/.env)}"
: "${POSTGRES_DB:?Brak POSTGRES_DB (ani w środowisku, ani w $COMPOSE_DIR/.env)}"

APPDATA_VOLUME="${APPDATA_VOLUME:-polsales_appdata}"

# Ustal archiwum załączników: jawny argument lub auto (db-STAMP.dump -> data-STAMP.tar.gz).
if [ "$DATA_ARCHIVE_ARG" = "none" ]; then
	DATA_ARCHIVE=""
elif [ -n "$DATA_ARCHIVE_ARG" ]; then
	DATA_ARCHIVE="$DATA_ARCHIVE_ARG"
else
	DATA_ARCHIVE="$(dirname "$DUMP")/$(basename "$DUMP" | sed 's/^db-/data-/; s/\.dump$/.tar.gz/')"
	[ -f "$DATA_ARCHIVE" ] || DATA_ARCHIVE=""
fi

# --- Baza ---
echo "UWAGA: to nadpisze bazę ${POSTGRES_DB}. Ctrl+C aby przerwać, Enter aby kontynuować."
read -r

docker compose exec -T db pg_restore -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
	--clean --if-exists < "$DUMP"

echo "Baza odtworzona z: $DUMP"

# --- Załączniki /data (opcjonalnie) ---
if [ -n "$DATA_ARCHIVE" ] && [ -f "$DATA_ARCHIVE" ]; then
	echo
	echo "UWAGA: to NADPISZE załączniki w woluminie ${APPDATA_VOLUME} zawartością:"
	echo "       $DATA_ARCHIVE"
	echo "Ctrl+C aby pominąć/przerwać, Enter aby kontynuować."
	read -r
	# Czyścimy katalog i rozpakowujemy archiwum do woluminu danych.
	docker run --rm \
		-v "$APPDATA_VOLUME":/data \
		-v "$(cd "$(dirname "$DATA_ARCHIVE")" && pwd)":/backup:ro \
		alpine sh -c "rm -rf /data/* /data/..?* /data/.[!.]* 2>/dev/null; tar xzf \"/backup/$(basename "$DATA_ARCHIVE")\" -C /data"
	echo "Załączniki odtworzone z: $DATA_ARCHIVE"
else
	echo "Pominięto załączniki (brak archiwum data-*.tar.gz lub wskazano 'none')."
fi

echo "Odtworzenie zakończone."
