#!/usr/bin/env bash
# Disaster recovery: replace the LIVE database and files with a backup.
# Current data is moved aside (not deleted) so the restore can be undone.
#   restore.sh <backup-file> [--yes]
# Practise with restore-drill.sh first; it never touches the live stack.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "$here/common.sh"
load_env
need gpg
need docker

file="${1:-}"
[ -n "$file" ] && [ -f "$file" ] || die "Usage: restore.sh <backup-file> [--yes]"
if [ "${2:-}" != "--yes" ]; then
  echo "This replaces the live database and files with $(basename "$file")."
  echo "Current data will be moved to $DATA_DIR/pre-restore-<timestamp>."
  read -r -p "Type RESTORE to continue: " answer
  [ "$answer" = "RESTORE" ] || die "Cancelled"
fi

PASSFILE="${BACKUP_PASSPHRASE_FILE:-/root/.bpcad-backup-passphrase}"
work="$(mktemp -d "$BACKUP_DIR/.restore-XXXXXX")"
trap 'rm -rf "$work"' EXIT

log "Decrypting and verifying"
gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$PASSFILE" --decrypt "$file" \
  | tar -C "$work" -xf -
while read -r name digest; do
  case "$name" in format|created_at|git_sha) continue ;; esac
  [ "$(sha256 "$work/$name")" = "$digest" ] || die "Checksum mismatch for $name; backup is damaged"
done < "$work/manifest.txt"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
aside="$DATA_DIR/pre-restore-$stamp"
log "Stopping application services"
compose stop proxy api extract-worker scheduler cad-worker

log "Moving current files to $aside"
mkdir -p "$aside"
for part in files outbox; do
  if [ -e "$DATA_DIR/$part" ]; then
    mv "$DATA_DIR/$part" "$aside/$part"
  fi
done
log "Saving a dump of the current database to $aside/db-before-restore.dump"
compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner \
  > "$aside/db-before-restore.dump"

log "Restoring files"
tar -C "$DATA_DIR" -xf "$work/files.tar"
prepare_data_dir "$DATA_DIR"
chown -R "$APP_UID:$APP_GID" "$DATA_DIR/files" "$DATA_DIR/outbox"
chown "$CAD_UID:$APP_GID" "$DATA_DIR/files/staging"

log "Restoring database"
compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid();" \
  -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";" -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";" >/dev/null
compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error \
  < "$work/db.dump"

log "Starting application services"
compose up -d
wait_healthy api 300 || die "API did not become healthy; check: bpcad logs api"
compose exec -T api python manage.py verify_storage --compact
log "Restore complete. Previous data kept in $aside"
