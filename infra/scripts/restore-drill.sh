#!/usr/bin/env bash
# Restore a backup into an isolated, throwaway stack (its own containers,
# networks and data directory, no published ports), verify every file hash and
# row count, record the result, and tear it all down. The live stack is untouched.
#   restore-drill.sh [backup-file]      (default: newest backup)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "$here/common.sh"
load_env
need gpg
need docker

PASSFILE="${BACKUP_PASSPHRASE_FILE:-/root/.bpcad-backup-passphrase}"
file="${1:-$(ls -1t "$BACKUP_DIR"/bpcad-*.tar.gpg 2>/dev/null | head -1 || true)}"
[ -n "$file" ] && [ -f "$file" ] || die "No backup file found (looked in $BACKUP_DIR)"

drill="$(mktemp -d "$BACKUP_DIR/.drill-XXXXXX")"
project="bpcad-drill-$$"
drill_env="$drill/drill.env"
LIVE_ENV_FILE="$ENV_FILE"
LIVE_PROJECT="$COMPOSE_PROJECT_NAME"

drill_compose() {
  docker compose --project-name "$project" --env-file "$drill_env" \
    -f "$APP_DIR/infra/compose/docker-compose.yml" "$@"
}
live_compose() {
  docker compose --project-name "$LIVE_PROJECT" --env-file "$LIVE_ENV_FILE" \
    -f "$APP_DIR/infra/compose/docker-compose.yml" "$@"
}
result="failed"
detail="unknown error"
finish() {
  drill_compose down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$drill"
  live_compose exec -T api python manage.py record_backup --kind restore_drill --status "$result" \
    --location "$file" --details "{\"detail\": \"$detail\"}" >/dev/null 2>&1 || true
  if [ "$result" = "succeeded" ]; then log "RESTORE DRILL PASSED: $detail"; else log "RESTORE DRILL FAILED: $detail"; exit 1; fi
}
trap finish EXIT

log "Decrypting $(basename "$file")"
mkdir -p "$drill/backup"
gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$PASSFILE" --decrypt "$file" \
  | tar -C "$drill/backup" -xf -

log "Verifying archive checksums"
while read -r name digest; do
  case "$name" in format|created_at|git_sha) continue ;; esac
  actual="$(sha256 "$drill/backup/$name")"
  if [ "$actual" != "$digest" ]; then detail="checksum mismatch for $name"; exit 1; fi
done < "$drill/backup/manifest.txt"

log "Preparing isolated data directory"
prepare_data_dir "$drill/data"
tar -C "$drill/data" -xf "$drill/backup/files.tar"
chown -R "$APP_UID:$APP_GID" "$drill/data/files" "$drill/data/outbox"
chown "$CAD_UID:$APP_GID" "$drill/data/files/staging"

# Fresh secrets and a different project name: nothing is shared with the live stack.
grep -v -E '^(DATA_DIR|COMPOSE_PROJECT_NAME|HTTP_PORT|POSTGRES_PASSWORD|DJANGO_SECRET_KEY)=' "$LIVE_ENV_FILE" > "$drill_env"
{
  echo "DATA_DIR=$drill/data"
  echo "COMPOSE_PROJECT_NAME=$project"
  echo "HTTP_PORT=0"
  echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
  echo "DJANGO_SECRET_KEY=$(openssl rand -hex 32)"
} >> "$drill_env"

log "Starting isolated database"
drill_compose up -d postgres redis >/dev/null
for _ in $(seq 1 60); do
  if drill_compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then break; fi
  sleep 2
done

log "Restoring database"
if ! drill_compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error \
     < "$drill/backup/db.dump"; then
  detail="pg_restore failed"; exit 1
fi

log "Verifying every stored file hash and row count"
expected="$(cat "$drill/backup/counts.json")"
if output="$(drill_compose run --rm --no-deps -T api manage verify_storage --expect "$expected" 2>&1)"; then
  result="succeeded"
  detail="$(basename "$file") restored and verified"
else
  detail="verification failed: $(echo "$output" | tr '\n"' ' ' | tail -c 400)"
  exit 1
fi
