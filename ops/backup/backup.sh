#!/bin/sh
set -eu
export PGPASSWORD="$(cat /run/secrets/postgres_password)"
umask 077
backup() {
  exec 9>/tmp/backup.lock
  flock -n 9 || { printf 'Backup já em execução.\n' >&2; return 1; }
  if [ ! -f "$RESTIC_REPOSITORY/config" ]; then restic init; fi
  pg_dump --format=custom --serializable-deferrable --file=/tmp/tuya.dump
  restic backup /tmp/tuya.dump --host tuya-server --tag database
  restic forget --host tuya-server --tag database --keep-daily 7 --keep-weekly 4 --prune
  restic check
  rm -f /tmp/tuya.dump
  printf '{"event":"backup_completed","utc":"%s"}\n' "$(date -u +%FT%TZ)"
}
if [ "${1:-}" = once ]; then backup; exit 0; fi
if [ "$#" -gt 0 ]; then exec "$@"; fi
while true; do
  if ! (backup); then printf '{"event":"backup_failed"}\n' >&2; fi
  # Daily schedule in UTC; service start establishes the first run.
  sleep 86400 & wait $!
done
