#!/usr/bin/env bash
# Shared helpers for the host scripts. Source this file; do not run it.

INSTALL_DIR="${INSTALL_DIR:-/opt/blueprint-cad}"
ENV_FILE="${ENV_FILE:-$INSTALL_DIR/.env}"
APP_DIR="${APP_DIR:-$INSTALL_DIR/app}"
APP_UID=10001
APP_GID=10001
CAD_UID=10002

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
warn() { log "WARNING: $*" >&2; }
die() { log "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed"; }

load_env() {
  [ -f "$ENV_FILE" ] || die "Missing $ENV_FILE. Run infra/install.sh first."
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
  DATA_DIR="${DATA_DIR:-$INSTALL_DIR/data}"
  BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-bpcad}"
  export DATA_DIR BACKUP_DIR COMPOSE_PROJECT_NAME
}

compose() {
  docker compose --project-name "$COMPOSE_PROJECT_NAME" --env-file "$ENV_FILE" \
    -f "$APP_DIR/infra/compose/docker-compose.yml" "$@"
}

sha256() { sha256sum "$1" | cut -d' ' -f1; }

# Create the data layout with the ownership the containers expect.
prepare_data_dir() {
  local dir="$1"
  mkdir -p "$dir/files/orgs" "$dir/files/tmp" "$dir/files/staging" "$dir/outbox" \
           "$dir/postgres" "$dir/redis" "$dir/backups"
  chown "$APP_UID:$APP_GID" "$dir/files" "$dir/files/orgs" "$dir/files/tmp" "$dir/outbox"
  chown "$CAD_UID:$APP_GID" "$dir/files/staging"
  chmod 2770 "$dir/files" "$dir/files/orgs" "$dir/files/tmp" "$dir/files/staging"
  chmod 0700 "$dir/outbox" "$dir/backups"
}

wait_healthy() {
  local service="$1" timeout="${2:-240}" waited=0 cid status
  while :; do
    cid="$(compose ps -q "$service" 2>/dev/null || true)"
    if [ -n "$cid" ]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
      [ "$status" = "healthy" ] && return 0
    fi
    [ "$waited" -ge "$timeout" ] && return 1
    sleep 3
    waited=$((waited + 3))
  done
}
