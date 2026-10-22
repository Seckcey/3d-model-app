# Blueprint to CAD

Self-hosted web application for machine shops: upload a customer part drawing, review what the system read, and download a **checked** solid model (STEP), cut-ready DXF and a check report that ties every modeled feature to a drawing callout.

- **Plan:** [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) (Version 2, with the machinist research in [docs/research/machinist-needs.md](docs/research/machinist-needs.md))
- **Status:** Phase 1 (foundation, access and intake) plus the automated Phase 0 geometry benchmark
- **Pilot URL:** https://3d.8westit.com (Cloudflare Tunnel to port 9999 on the VM)

## Repository layout

| Path | What |
|---|---|
| `apps/api` | Django + DRF API, email-code auth (django-allauth headless), jobs, intake, Celery tasks |
| `apps/web` | React + TypeScript (Vite) interface |
| `workers/cad` | Isolated CadQuery/Open CASCADE geometry worker (no database, no outbound network) |
| `packages/feature-spec` | FeatureSpec JSON schema and the benchmark reference parts |
| `infra` | Dockerfiles, Compose, nginx, VM installer, backup and restore scripts |
| `adapters` | Placeholders for the Fusion, AutoCAD and Mastercam adapters (Phases 6–7) |
| `docs` | Plan, research, decisions and operations guides |

## Install on the VM

See [docs/operations/install.md](docs/operations/install.md). In short, on an Ubuntu/Debian VM with internet access:

```bash
curl -fsSL https://raw.githubusercontent.com/Seckcey/3d-model-app/main/infra/install.sh -o install.sh && sudo bash install.sh
```

## Development

See [docs/operations/development.md](docs/operations/development.md).
