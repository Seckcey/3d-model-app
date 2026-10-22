#!/usr/bin/env bash
# Encrypted backup of everything needed to recover: a consistent PostgreSQL dump,
# original drawings, generated files, the outbox and the deployment config.
# The database is dumped first so every file it references is in the archive.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
. "$here/common.sh"
load_env
need gpg
need docker

PASSFILE="${BACKUP_PASSPHRASE_FILE:-/root/.bpcad-backup-passphrase}"
[ -s "$PASSFILE" ] || die "Backup passphrase file $PASSFILE is missing or empty"
KEEP="${BACKUP_KEEP:-14}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BACKUP_DIR/bpcad-$stamp.tar.gpg"
work="$(mktemp -d "$BACKUP_DIR/.work-XXXXXX")"
trap 'rm -rf "$work" "$out.partial"' EXIT

record_failure() {
  compose exec -T api python manage.py record_backup --kind backup --status failed \
    --details "{\"error\": \"$1\"}" >/dev/null 2>&1 || true
  die "$1"
}
trap 'record_failure "backup failed near line $LINENO"' ERR

# Counts first: the restore drill requires every restored count to be at least these.
log "Recording file and row counts"
compose exec -T api python manage.py verify_storage --counts-only --compact > "$work/counts.json"

log "Dumping PostgreSQL"
compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner \
  > "$work/db.dump"
[ -s "$work/db.dump" ] || record_failure "database dump is empty"

log "Archiving drawings, generated files and outbox"
tar -C "$DATA_DIR" --exclude=files/tmp --exclude=files/staging -cf "$work/files.tar" files outbox
cp "$ENV_FILE" "$work/env"

cat > "$work/manifest.txt" <<EOF
format 1
created_at $stamp
git_sha ${GIT_SHA:-unknown}
db.dump $(sha256 "$work/db.dump")
files.tar $(sha256 "$work/files.tar")
counts.json $(sha256 "$work/counts.json")
env $(sha256 "$work/env")
EOF

log "Encrypting (AES-256)"
tar -C "$work" -cf - manifest.txt db.dump files.tar counts.json env \
  | gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file "$PASSFILE" \
        --symmetric --cipher-algo AES256 --compress-algo zlib -o "$out.partial"
mv "$out.partial" "$out"
chmod 600 "$out"
size="$(stat -c %s "$out")"
digest="$(sha256 "$out")"
printf '%s  %s\n' "$digest" "$(basename "$out")" > "$out.sha256"

if [ -n "${BACKUP_OFFSITE_CMD:-}" ]; then
  log "Copying off the VM"
  offsite="${BACKUP_OFFSITE_CMD//\{file\}/$out}"
  if ! bash -c "$offsite"; then
    warn "Off-site copy failed; the local backup is still valid"
  fi
fi

log "Applying retention (keep $KEEP)"
ls -1t "$BACKUP_DIR"/bpcad-*.tar.gpg 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f "$old" "$old.sha256"
done

trap - ERR
compose exec -T api python manage.py record_backup --kind backup --status succeeded \
  --location "$out" --size "$size" --sha256 "$digest" \
  --details "{\"counts\": $(cat "$work/counts.json"), \"git_sha\": \"${GIT_SHA:-unknown}\"}" >/dev/null
log "Backup complete: $out ($size bytes)"
echo "$out"
