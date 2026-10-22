# Development

## Requirements

- Python 3.12 (API and CAD worker), Node 24 LTS (web), Docker with Compose v2 (full stack).

## API

```bash
cd apps/api
python3.12 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements.txt -r requirements-dev.txt
DJANGO_DEBUG=1 python manage.py migrate
DJANGO_DEBUG=1 python manage.py bootstrap --email you@example.test --org "Dev Shop"
DJANGO_DEBUG=1 python manage.py runserver
```

Without `POSTGRES_HOST` the API uses SQLite; without `REDIS_URL` it uses an in-memory cache and broker; without `EMAIL_HOST` mail goes to `var/outbox` (`python manage.py outbox --code`).

Tests and lint (CI runs them against PostgreSQL):

```bash
python -m pytest
ruff check .
```

## Web

```bash
cd apps/web
npm ci
npm run dev        # http://localhost:5173, proxies /api and /_allauth to :8000
npm run typecheck && npm test && npm run build
```

## CAD worker

```bash
cd workers/cad
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest
```

The tests build the three reference parts and compare every result with values computed independently from the specs (`packages/feature-spec/examples`).

## Full stack

```bash
cp .env.example /tmp/bpcad.env   # edit secrets; set DATA_DIR=/tmp/bpcad-data
sudo bash -c '. infra/scripts/common.sh && prepare_data_dir /tmp/bpcad-data'
docker compose --env-file /tmp/bpcad.env -f infra/compose/docker-compose.yml up -d --build
```

The CI `e2e` job does exactly this, then runs `infra/scripts/smoke.py`, restarts the stack, and runs a backup and an isolated restore drill.

## Repository rules

- Customer drawings never go into the repository or test fixtures. Tests generate synthetic drawings (`apps/api/tests/drawings.py`).
- Geometry tests must compare against independently computed expectations, never against the engine's own output.
- Every new API view must filter by organisation membership; add the endpoint to `tests/test_isolation.py`.
