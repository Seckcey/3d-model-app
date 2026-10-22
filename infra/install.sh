#!/usr/bin/env bash
# Blueprint to CAD: install or update on a Linux VM with Docker.
#
#   curl -fsSL https://raw.githubusercontent.com/Seckcey/3d-model-app/main/infra/install.sh -o install.sh
#   sudo bash install.sh
#
# Re-running updates to the latest code and keeps your data and settings.
# Non-interactive example:
#   sudo ADMIN_EMAIL=you@shop.com ORG_NAME="Ralls Precision" bash install.sh --yes
#
# Options: --yes (accept defaults, no prompts), --build (build images on this VM),
#          --pull (only use prebuilt images), --skip-drill (skip the first backup and
#          restore drill), --branch NAME.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Seckcey/3d-model-app.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/blueprint-cad}"
APP_DIR="$INSTALL_DIR/app"
ENV_FILE="$INSTALL_DIR/.env"
PASSFILE_DEFAULT="/root/.bpcad-backup-passphrase"
ASSUME_YES=0
SKIP_DRILL=0
IMAGE_MODE="${IMAGE_MODE:-auto}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --yes|-y) ASSUME_YES=1 ;;
    --skip-drill) SKIP_DRILL=1 ;;
    --build) IMAGE_MODE=build ;;
    --pull) IMAGE_MODE=pull ;;
    --branch) BRANCH="$2"; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

blue() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
green() { printf '\033[1;32m✔\033[0m %s\n' "$*"; }
yellow() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

# A terminal must actually open (the device node exists even without one).
can_prompt() { [ "$ASSUME_YES" -eq 0 ] && { : > /dev/tty; } 2>/dev/null; }
ask() {  # ask "Question" "default" -> echoes answer
  local question="$1" default="${2:-}" reply=""
  if can_prompt; then
    printf '%s [%s]: ' "$question" "$default" > /dev/tty
    IFS= read -r reply < /dev/tty || true
  fi
  printf '%s' "${reply:-$default}"
}
ask_secret() {
  local question="$1" reply=""
  if can_prompt; then
    printf '%s: ' "$question" > /dev/tty
    IFS= read -rs reply < /dev/tty || true
    printf '\n' > /dev/tty
  fi
  printf '%s' "$reply"
}
confirm() {  # confirm "Question" (default yes)
  [ "$ASSUME_YES" -eq 1 ] && return 0
  can_prompt || return 0
  local reply
  printf '%s [Y/n]: ' "$1" > /dev/tty
  IFS= read -r reply < /dev/tty || true
  case "$reply" in n|N|no|NO) return 1 ;; *) return 0 ;; esac
}
quote() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

[ "$(id -u)" -eq 0 ] || fail "Run this script with sudo (it installs packages and writes to $INSTALL_DIR)."
[ "$(uname -s)" = "Linux" ] || fail "This installer is for Linux."

# ---------------------------------------------------------------- packages
blue "Checking system packages"
if command -v apt-get >/dev/null 2>&1; then
  missing=""
  for pkg in git curl ca-certificates gnupg openssl cron; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing="$missing $pkg"
  done
  if [ -n "$missing" ]; then
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    # shellcheck disable=SC2086
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $missing >/dev/null
  fi
  systemctl enable --now cron >/dev/null 2>&1 || true
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y -q git curl ca-certificates gnupg2 openssl cronie >/dev/null
  systemctl enable --now crond >/dev/null 2>&1 || true
else
  for cmd in git curl gpg openssl; do command -v "$cmd" >/dev/null 2>&1 || fail "Please install $cmd"; done
fi
green "git, curl, gnupg, openssl and cron are present"

if ! command -v docker >/dev/null 2>&1; then
  yellow "Docker is not installed."
  if confirm "Install Docker Engine now using Docker's official script (https://get.docker.com)?"; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
  else
    fail "Install Docker Engine and the Compose plugin, then run this script again."
  fi
fi
docker info >/dev/null 2>&1 || fail "Docker is installed but not running (try: systemctl start docker)."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is missing (install the docker-compose-plugin package)."
green "$(docker --version | cut -d, -f1) with $(docker compose version --short 2>/dev/null || echo compose v2)"

# ---------------------------------------------------------------- code
mkdir -p "$INSTALL_DIR"
if [ -d "$APP_DIR/.git" ]; then
  blue "Updating code ($BRANCH)"
  git -C "$APP_DIR" fetch --quiet --depth 50 origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet -B "$BRANCH" "origin/$BRANCH"
  git -C "$APP_DIR" reset --quiet --hard "origin/$BRANCH"
else
  blue "Downloading code from $REPO_URL"
  git clone --quiet --depth 50 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
GIT_SHA="$(git -C "$APP_DIR" rev-parse --short=12 HEAD)"
green "Code at $GIT_SHA"
chmod +x "$APP_DIR/infra/bpcad" "$APP_DIR/infra/scripts/"*.sh "$APP_DIR/infra/install.sh"

# shellcheck source=scripts/common.sh
. "$APP_DIR/infra/scripts/common.sh"

# ---------------------------------------------------------------- settings
FIRST_INSTALL=0
if [ ! -f "$ENV_FILE" ]; then
  FIRST_INSTALL=1
  blue "First-time setup"
  PUBLIC_URL="$(ask "Public URL users will open" "${PUBLIC_URL:-https://3d.8westit.com}")"
  HTTP_PORT="$(ask "Port on this VM for the Cloudflare tunnel" "${HTTP_PORT:-9999}")"
  ADMIN_EMAIL="$(ask "Your email address (first administrator)" "${ADMIN_EMAIL:-}")"
  ORG_NAME="$(ask "Shop / workspace name" "${ORG_NAME:-8 West Ventures}")"
  [ -n "$ADMIN_EMAIL" ] || fail "An administrator email is required (set ADMIN_EMAIL=...)."
  echo
  yellow "Email: sign-in codes need an SMTP relay (Microsoft 365, Google Workspace, SES, Postmark...)."
  yellow "Leave the host empty to start without one; codes then go to a local outbox (sudo bpcad outbox)."
  EMAIL_HOST="$(ask "SMTP host (empty = configure later)" "${EMAIL_HOST:-}")"
  EMAIL_PORT="587"; EMAIL_HOST_USER=""; EMAIL_HOST_PASSWORD=""; DEFAULT_FROM_EMAIL=""
  if [ -n "$EMAIL_HOST" ]; then
    EMAIL_PORT="$(ask "SMTP port" "587")"
    EMAIL_HOST_USER="$(ask "SMTP username" "")"
    EMAIL_HOST_PASSWORD="${EMAIL_HOST_PASSWORD:-$(ask_secret "SMTP password (hidden)")}"
    DEFAULT_FROM_EMAIL="$(ask "From address" "Blueprint to CAD <${EMAIL_HOST_USER:-no-reply@8westit.com}>")"
  fi
  public_host="$(printf '%s' "$PUBLIC_URL" | sed -E 's#^[a-z]+://##; s#[:/].*$##')"
  vm_ips="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9.]+$' | head -3 | paste -sd, - || true)"
  allowed="$public_host,localhost,127.0.0.1${vm_ips:+,$vm_ips}"
  {
    echo "# Blueprint to CAD settings, created $(date -u +%FT%TZ). Keep this file private."
    echo "PUBLIC_URL=$(quote "$PUBLIC_URL")"
    echo "HTTP_PORT=$HTTP_PORT"
    echo "HTTP_BIND=0.0.0.0"
    echo "DJANGO_ALLOWED_HOSTS=$(quote "$allowed")"
    echo "CSRF_EXTRA_TRUSTED_ORIGINS="
    echo "COOKIE_SECURE="
    echo "DJANGO_SECRET_KEY=$(openssl rand -hex 32)"
    echo "POSTGRES_DB=bpcad"
    echo "POSTGRES_USER=bpcad"
    echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
    echo "SIGNUP_MODE=invite_only"
    echo "EMAIL_HOST=$(quote "$EMAIL_HOST")"
    echo "EMAIL_PORT=$EMAIL_PORT"
    echo "EMAIL_HOST_USER=$(quote "$EMAIL_HOST_USER")"
    echo "EMAIL_HOST_PASSWORD=$(quote "$EMAIL_HOST_PASSWORD")"
    echo "EMAIL_USE_TLS="
    echo "EMAIL_USE_SSL="
    echo "DEFAULT_FROM_EMAIL=$(quote "$DEFAULT_FROM_EMAIL")"
    echo "TIME_ZONE=$(quote "$(cat /etc/timezone 2>/dev/null || echo America/Chicago)")"
    echo "MAX_UPLOAD_MB=25"
    echo "MAX_PDF_PAGES=20"
    echo "DATA_DIR=$INSTALL_DIR/data"
    echo "IMAGE_REGISTRY=ghcr.io/seckcey/3d-model-app"
    echo "IMAGE_TAG=$GIT_SHA"
    echo "GIT_SHA=$GIT_SHA"
    echo "BACKUP_KEEP=14"
    echo "BACKUP_PASSPHRASE_FILE=$PASSFILE_DEFAULT"
    echo "BACKUP_OFFSITE_CMD="
    echo "ADMIN_EMAIL=$(quote "$ADMIN_EMAIL")"
    echo "ORG_NAME=$(quote "$ORG_NAME")"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  green "Settings written to $ENV_FILE"
else
  blue "Keeping existing settings in $ENV_FILE"
  sed -i -E "s/^IMAGE_TAG=.*/IMAGE_TAG=$GIT_SHA/; s/^GIT_SHA=.*/GIT_SHA=$GIT_SHA/" "$ENV_FILE"
fi
load_env

# ---------------------------------------------------------------- data
blue "Preparing data directory $DATA_DIR"
prepare_data_dir "$DATA_DIR"
green "Data directory ready (database, drawings, outbox, backups)"

# ---------------------------------------------------------------- images
arch="$(uname -m)"
use_pull=0
if [ "$IMAGE_MODE" = "pull" ]; then
  use_pull=1
elif [ "$IMAGE_MODE" = "auto" ] && [ "$arch" = "x86_64" ]; then
  use_pull=1
fi
built=0
if [ "$use_pull" -eq 1 ]; then
  blue "Downloading prebuilt images for $GIT_SHA"
  if compose pull --quiet proxy api cad-worker 2>/dev/null; then
    green "Images downloaded"
  elif [ "$IMAGE_MODE" = "pull" ]; then
    fail "Prebuilt images for $GIT_SHA are not available yet (CI may still be publishing)."
  else
    yellow "Prebuilt images not available; building on this VM instead (several minutes)"
    use_pull=0
  fi
fi
if [ "$use_pull" -eq 0 ]; then
  blue "Building images on this VM (first build takes several minutes)"
  APP_VERSION=0.1.0 compose build --pull
  built=1
  green "Images built"
fi
compose pull --quiet postgres redis >/dev/null 2>&1 || true

# ---------------------------------------------------------------- start
if [ "$FIRST_INSTALL" -eq 0 ] && [ -n "$(compose ps -q api 2>/dev/null)" ] \
   && [ -s "${BACKUP_PASSPHRASE_FILE:-$PASSFILE_DEFAULT}" ]; then
  blue "Backing up before applying the update (database migrations may run)"
  if "$APP_DIR/infra/scripts/backup.sh" >/tmp/bpcad-pre-update-backup.log 2>&1; then
    green "Pre-update backup written"
  else
    yellow "Pre-update backup failed (see /tmp/bpcad-pre-update-backup.log)"
    confirm "Continue the update without a fresh backup?" || fail "Update stopped; nothing was changed."
  fi
fi
blue "Starting services"
compose up -d --remove-orphans
wait_healthy api 420 || { compose logs --tail=80 api; fail "The API did not become healthy."; }
wait_healthy proxy 120 || { compose logs --tail=40 proxy; fail "The proxy did not become healthy."; }
green "All services are up"

if [ -n "${ADMIN_EMAIL:-}" ]; then
  compose exec -T api python manage.py bootstrap --email "$ADMIN_EMAIL" --org "${ORG_NAME:-8 West Ventures}" >/dev/null
  green "Administrator $ADMIN_EMAIL is an owner of '${ORG_NAME:-8 West Ventures}'"
fi

# ---------------------------------------------------------------- operations
ln -sf "$APP_DIR/infra/bpcad" /usr/local/bin/bpcad
PASSFILE="${BACKUP_PASSPHRASE_FILE:-$PASSFILE_DEFAULT}"
if [ ! -s "$PASSFILE" ]; then
  umask 077
  openssl rand -base64 48 > "$PASSFILE"
  chmod 400 "$PASSFILE"
  NEW_PASSPHRASE=1
fi
cat > /etc/cron.d/blueprint-cad <<EOF
# Blueprint to CAD: nightly encrypted backup, weekly restore drill into an isolated stack
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
INSTALL_DIR=$INSTALL_DIR
30 2 * * * root $APP_DIR/infra/scripts/backup.sh >> /var/log/blueprint-cad-backup.log 2>&1
15 4 * * 0 root $APP_DIR/infra/scripts/restore-drill.sh >> /var/log/blueprint-cad-backup.log 2>&1
EOF
chmod 644 /etc/cron.d/blueprint-cad
green "Nightly backups (02:30) and weekly restore drills (Sunday 04:15) scheduled"

if [ "$SKIP_DRILL" -eq 0 ] && [ "$FIRST_INSTALL" -eq 1 ]; then
  blue "Running the first backup and an isolated restore drill"
  if "$APP_DIR/infra/scripts/backup.sh" >/tmp/bpcad-first-backup.log 2>&1 \
     && "$APP_DIR/infra/scripts/restore-drill.sh" >>/tmp/bpcad-first-backup.log 2>&1; then
    green "Backup restored into an isolated stack and every file hash verified"
  else
    yellow "Backup or restore drill failed; see /tmp/bpcad-first-backup.log"
  fi
fi

ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<EOF

$(green "Blueprint to CAD is running ($GIT_SHA)")

  On this network:  http://${ip:-<vm-ip>}:${HTTP_PORT}
  Public address:   ${PUBLIC_URL}

  Cloudflare Tunnel: add a public hostname
      ${PUBLIC_URL#https://}  ->  http://localhost:${HTTP_PORT}
  (use http://${ip:-<vm-ip>}:${HTTP_PORT} if cloudflared runs on another machine).
  Cloudflare serves the site on 443, so users open ${PUBLIC_URL} without :${HTTP_PORT}.
  Recommended: protect ${PUBLIC_URL}/admin/ with a Cloudflare Access policy.

  Sign in at ${PUBLIC_URL}/login with ${ADMIN_EMAIL:-your administrator email}.
EOF
if [ -z "${EMAIL_HOST:-}" ]; then
cat <<EOF
  Email is not configured yet, so sign-in codes are kept on this server. Get yours with:
      sudo bpcad outbox --code --to ${ADMIN_EMAIL:-you@example.com}
  To send real email, set EMAIL_* in $ENV_FILE and run: sudo bpcad update
EOF
fi
if [ "${NEW_PASSPHRASE:-0}" -eq 1 ]; then
cat <<EOF

  IMPORTANT: backups are encrypted with the passphrase in $PASSFILE.
  Copy it to your password manager now; without it no backup can be restored.
      sudo cat $PASSFILE
  Backups are written to $DATA_DIR/backups. Copy them off this VM too
  (set BACKUP_OFFSITE_CMD in $ENV_FILE, e.g. an rclone command).
EOF
fi
cat <<EOF

  Useful commands: bpcad status | bpcad logs api | bpcad update | bpcad backup
                   bpcad restore-drill | bpcad outbox | bpcad selftest you@shop.com
EOF
