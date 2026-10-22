# Phase 1 report: foundation, access and intake

October 22, 2026 · plan reference: [BUILD_PLAN.md](BUILD_PLAN.md), Phase 1 (plus the automatable part of Phase 0)

## Exit gate

| Gate | Result | Evidence |
|---|---|---|
| Two test shops cannot access each other's files or jobs | Pass (automated) | `apps/api/tests/test_isolation.py` tries every read and write path with another shop's IDs (all 404 or refused); the CI end-to-end test repeats it through nginx with two real accounts |
| Login expiry and replay checks pass | Pass (automated) | `apps/api/tests/test_auth.py`: code expires at 10 minutes, valid at 9; a used code cannot be replayed; 3 wrong codes end the attempt; resend replaces the code with a 60-second cooldown; per-address rate limit; enumeration-neutral responses; logout and session revocation are immediate |
| Restarting the stack preserves uploaded files and job history | Pass in CI | `e2e` job: `docker compose down` / `up`, then the same file downloads with the same SHA-256 and both jobs keep their history |
| Backup restored into an isolated environment | Pass in CI; runs again on the VM at install and weekly | `backup.sh` then `restore-drill.sh`: a separate Compose project with its own data directory restores the encrypted backup, and every stored file hash and row count is verified |

## Delivered

- Email one-time-code sign-in, invitation-gated signup, workspaces, four roles (several per person), session management, admin user controls.
- Customers, projects (PO/RFQ), parts, revisions with the customer's revision letter, repeat-part search.
- Private storage with content sniffing, limits, hashing, read-only originals and authenticated downloads; append-only audit log with CSV export.
- Durable jobs (idempotency, leases, fencing, reconciliation, retries, cancellation, unsupported state); queue and worker health; disk, backlog and backup alerts.
- Intake check with page previews, scan-quality warnings, export-control markings (controlled until cleared, owner review), drawing hints and revision-mismatch warning.
- Shop modelling preferences (tapped-hole representation, tap-drill basis, mid-tolerance export, origin, STEP units defaulting to the drawing's, naming).
- Geometry benchmark in an isolated CAD worker: three reference parts × nominal/mid-tolerance, 142 independent checks, STEP with hole-type colours and declared units, 3D preview.
- VM installer, `bpcad` operations command, encrypted nightly backups, weekly restore drills, CI with a full-stack end-to-end test and image publishing.

## Tests

| Suite | Count | Where |
|---|---|---|
| API (PostgreSQL in CI) | 75 | `apps/api/tests` |
| Geometry engine | 36 | `workers/cad/tests` (inside the production CAD image in CI) |
| Web | 10 | `apps/web/src/test` + type-check + production build |
| End-to-end | 1 flow | `infra/scripts/smoke.py` through nginx, then restart, backup and restore drill |

## Known limitations

- Raster pages (scans, photos) get previews and quality warnings, but no OCR, marking scan or extraction until Phase 2.
- Drawing hints are regular-expression matches on vector text, labelled unverified.
- Viewers currently see all projects in their workspace; per-project access lists arrive with the US-person attribute in Phase 2.
- Admin MFA is not yet enforced; protect `/admin/` with Cloudflare Access until it is.
- One CAD worker; the CAD worker can reach Redis (for its queue), so Redis ACLs are a hardening item.
- The geometry engine builds the benchmark feature set only; countersinks, patterns and generation from real drawings are Phase 3.

## Your Phase 0 actions

1. Run **Geometry benchmark** in the web app and download the six STEP files.
2. Open them in the Fusion and Mastercam versions the pilot shop uses. Confirm inch units, sizes (plate 6.000 × 4.000 × .500), origin on the datum corner, hole colours, and that hole recognition finds every hole. Note the CAD versions in **Settings → CAM software**.
3. Collect 20–30 customer-authorised drawings (keep 10 untouched) and have a machinist record reference dimensions and manual modelling time.
4. Configure SMTP and verify delivery to Outlook and Gmail before inviting customers.
