#!/bin/sh
# Restore latest encrypted backup into a disposable database, never the live one.
set -eu
name="restore_check_$(date +%s)"
cleanup() { docker compose exec -T db dropdb -U tuya --if-exists "$name"; }
trap cleanup EXIT INT TERM
docker compose exec -T db createdb -U tuya "$name"
docker compose exec -T backup restic dump latest /tmp/tuya.dump | docker compose exec -T db pg_restore -U tuya --exit-on-error --dbname="$name"
docker compose exec -T db psql -U tuya -d "$name" -v ON_ERROR_STOP=1 -c 'SELECT version FROM schema_migrations; SELECT count(*) AS devices FROM devices; SELECT count(*) AS measurements FROM measurements;'
printf 'Restauração em banco vazio concluída.\n'
