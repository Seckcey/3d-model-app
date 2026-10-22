# Installing Blueprint to CAD on the VM

The whole application runs in Docker on one Linux VM. The proxy listens on **port 9999**; a Cloudflare Tunnel publishes it as **https://3d.8westit.com**.

## What you need

- A 64-bit Linux VM (Ubuntu 22.04/24.04 or Debian 12 tested by the installer; others with Docker work too) with internet access.
- Pilot sizing: 4 vCPU, 16 GB RAM, 150 GB free disk minimum (8 vCPU / 32 GB / 250 GB preferred).
- `sudo` access. Docker Engine and the Compose plugin are installed for you if missing (the script asks first).

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Seckcey/3d-model-app/main/infra/install.sh -o install.sh
```

```bash
sudo bash install.sh
```

The script asks for:

| Prompt | Default | Notes |
|---|---|---|
| Public URL | `https://3d.8westit.com` | What users type in the browser |
| Port | `9999` | The port the Cloudflare tunnel points at |
| Your email | — | Becomes the first administrator and workspace owner |
| Workspace name | `8 West Ventures` | Change to the pilot shop's name if you like |
| SMTP host, user, password, from | empty | Leave empty to start; sign-in codes then go to a server-side outbox |

Then it:

1. Installs `git`, `curl`, `gnupg`, `openssl` and `cron` if missing, and Docker if you agree.
2. Clones the code to `/opt/blueprint-cad/app` and writes settings to `/opt/blueprint-cad/.env` (mode 600) with generated database and session secrets.
3. Creates `/opt/blueprint-cad/data` for the database, drawings, outbox and backups.
4. Downloads prebuilt images from GitHub's registry, or builds them on the VM if they are not available (first build takes several minutes).
5. Starts seven containers: proxy, api, extract-worker, cad-worker, scheduler, postgres and redis.
6. Creates your administrator account and workspace.
7. Installs the `bpcad` command, schedules a nightly encrypted backup (02:30) and a weekly restore drill (Sunday 04:15).
8. Runs a first backup and restores it into a throwaway, isolated stack to prove recovery works.

Unattended install:

```bash
sudo ADMIN_EMAIL=you@8westit.com ORG_NAME="Ralls Precision" bash install.sh --yes
```

## Connect the Cloudflare Tunnel

In Cloudflare Zero Trust → Networks → Tunnels → your tunnel → **Public hostname**:

| Field | Value |
|---|---|
| Subdomain / domain | `3d` / `8westit.com` |
| Service | `http://localhost:9999` if `cloudflared` runs on this VM, otherwise `http://<vm-ip>:9999` |

Users open **https://3d.8westit.com** — without `:9999`. Cloudflare serves HTTPS on 443 and only proxies a fixed set of ports, which does not include 9999; port 9999 is the origin port the tunnel connects to.

Recommended: add a Cloudflare Access application for `3d.8westit.com/admin*` that allows only your email, as a second lock on the Django admin.

## First sign-in

Open https://3d.8westit.com/login and enter your administrator email.

If SMTP is not configured yet, the code is kept on the server:

```bash
sudo bpcad outbox --code --to you@8westit.com
```

Invite your team from **Members** in the web app. Without SMTP, read an invitation link with `sudo bpcad outbox --link --to their@email.com` and send it to them yourself.

## Configure email

Edit `/opt/blueprint-cad/.env`:

```bash
EMAIL_HOST='smtp.office365.com'
EMAIL_PORT=587
EMAIL_HOST_USER='noreply@8westit.com'
EMAIL_HOST_PASSWORD='app-password-here'
DEFAULT_FROM_EMAIL='Blueprint to CAD <noreply@8westit.com>'
```

Then apply it:

```bash
sudo bpcad update
```

Use an authenticated relay with SPF and DKIM set up for the sending domain, and test delivery to Outlook and Gmail. Keep the values in single quotes and avoid single quotes inside them.

## Backups

- Nightly at 02:30 to `/opt/blueprint-cad/data/backups/bpcad-<timestamp>.tar.gpg` (database dump, drawings, generated files, outbox, settings), AES-256 encrypted. The newest 14 are kept.
- The passphrase is in `/root/.bpcad-backup-passphrase`. **Store a copy in your password manager.** Without it, no backup can be restored.
- A backup on the same VM is not a recovery copy. Set `BACKUP_OFFSITE_CMD` in `.env` to copy each backup elsewhere, for example with rclone:
  `BACKUP_OFFSITE_CMD='rclone copy --no-traverse {file} offsite:blueprint-cad'`
- Weekly (Sunday 04:15) the newest backup is restored into an isolated stack and every file hash and row count is checked. Results appear on the **System status** page and in `/var/log/blueprint-cad-backup.log`.

Run either by hand:

```bash
sudo bpcad backup
```

```bash
sudo bpcad restore-drill
```

To recover the live system from a backup (asks for confirmation and keeps the current data aside):

```bash
sudo bpcad restore /opt/blueprint-cad/data/backups/bpcad-<timestamp>.tar.gpg
```

## Updating

```bash
sudo bpcad update
```

This pulls the latest `main`, takes a backup first, then migrates and restarts. Data and settings are kept.

## Everyday commands

| Command | What it does |
|---|---|
| `bpcad status` | Container states, version and readiness |
| `bpcad logs api` | Follow a service's logs (`api`, `extract-worker`, `cad-worker`, `scheduler`, `proxy`, `postgres`) |
| `bpcad restart` | Restart everything (or one service) |
| `bpcad outbox` | Show emails kept on the server when SMTP is off |
| `bpcad selftest you@shop.com` | End-to-end check through the proxy: sign-in, upload, intake, download, geometry benchmark (outbox mode only) |
| `bpcad manage <command>` | Run a Django management command |

## Troubleshooting

| Symptom | Check |
|---|---|
| Cloudflare shows 502 | `bpcad status`; is the proxy healthy and listening on 9999? Is the tunnel service `http://localhost:9999`? |
| "CSRF verification failed" | `PUBLIC_URL` in `.env` must exactly match the address in the browser (`https://3d.8westit.com`) |
| Sign-in works over the tunnel but not on `http://<vm-ip>:9999` | Expected: cookies are HTTPS-only. For LAN testing set `COOKIE_SECURE=false` and add `CSRF_EXTRA_TRUSTED_ORIGINS='http://<vm-ip>:9999'`, then `bpcad update` |
| Jobs stay "Queued" | **System status** → Workers; `bpcad logs extract-worker` and `bpcad logs cad-worker` |
| Disk filling up | **System status** → Disk; old backups in `data/backups` |

## Uninstall

```bash
sudo bpcad compose down
```

Then remove `/etc/cron.d/blueprint-cad` and `/usr/local/bin/bpcad`. Data stays in `/opt/blueprint-cad/data` until you delete it.
