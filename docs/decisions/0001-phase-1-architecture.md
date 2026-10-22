# ADR 0001: Phase 1 architecture choices

Status: accepted, October 22, 2026

## Decisions

1. **PostgreSQL is the record of truth; Celery/Redis only schedules.** Every job is a database row with an idempotency key, a lease and a fenced completion. Workers must win an atomic claim before doing work; a stale worker cannot overwrite a newer result. A scheduler task re-queues expired leases and re-dispatches lost messages.

2. **The geometry worker is isolated.** It has no database credentials, sits on an internal Docker network with no outbound route, runs as a non-root user on a read-only filesystem, and only sees its staging directory. It returns file hashes; the API verifies them and publishes atomically. Uploaded documents or AI output are data for an allowlisted interpreter, never code.

3. **Geometry is verified independently.** Expected values come from the spec (the drawing's numbers) and closed-form formulas; measured values are read back from the exact B-rep. A solid with a missing or misplaced feature fails. STEP files are reopened and re-checked.

4. **Controlled until cleared.** Every drawing is treated as export controlled until an owner records otherwise. Intake detects ITAR/EAR/CUI/distribution/classification markings in vector text and locks external processing; raster pages are reported "not scanned" rather than "none found". External AI needs the workspace policy, the project opt-in and an owner's clearance.

5. **Email one-time codes via django-allauth headless.** No customer passwords. Signup is closed except through an invitation token held in the session, and only for the invited address. Django admin reuses the same session (no admin password) and should additionally sit behind Cloudflare Access.

6. **Outbox email until SMTP exists.** Codes and invitations are written to a private directory readable only from the server, so the pilot can start before a mail relay is configured. Nothing in the outbox contains drawings.

7. **Authenticated downloads through nginx X-Accel-Redirect.** Django checks membership and role, then nginx streams the file from a read-only mount.

8. **Units are never silently converted.** Geometry is built in millimetres internally; STEP exports default to the drawing's units and every filename and STEP header states units and variant.

9. **Deployment by script, images from CI.** CI tests everything (including a full Compose stack with restart and restore drill) and publishes images to GHCR. The VM installer pulls them, or builds locally when unavailable (or on ARM).

## Consequences

- One CAD job at a time per workspace and one CAD worker process; scale only after measuring.
- Session "last seen" activity is not tracked (it would write on every request); sessions are recorded at sign-in.
- Raster drawings get previews and warnings now but no marking scan or extraction until OCR lands in Phase 2.
