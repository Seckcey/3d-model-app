# Isolated geometry worker: CadQuery / Open CASCADE. Runs as a non-root user,
# with no database credentials, on a network with no outbound route.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 libxrender1 libxext6 libsm6 libx11-6 libxi6 libxkbcommon0 libfontconfig1 libegl1 \
 && rm -rf /var/lib/apt/lists/*

# Same group as the API user so the API can read and remove staged files.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10002 --gid app --home-dir /worker --shell /usr/sbin/nologin cad

WORKDIR /worker
COPY workers/cad/requirements.txt /tmp/requirements.txt
RUN pip install --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY workers/cad/cadworker /worker/cadworker
COPY packages/feature-spec/schema /worker/cadworker/schema
COPY packages/feature-spec/examples /worker/examples

ENV STAGING_ROOT=/data/staging
USER cad
# Build-time self-test as the runtime user from the installed layout: the worker
# must import and build a reference part, or the image is not produced.
RUN STAGING_ROOT=/tmp/selftest python -c "import json, uuid; from cadworker import tasks; \
r = tasks.run(str(uuid.uuid4()), [json.load(open('/worker/examples/bracket-block.json'))], {}); \
assert r['ok'] and all(p['validation']['passed'] for p in r['parts']), r; \
print('cad self-test passed', r['engine'])" \
 && rm -rf /tmp/selftest
CMD ["celery", "-A", "cadworker.celery_app", "worker", "--queues", "cad", "--concurrency", "1", \
     "--hostname", "cad@%h", "--max-tasks-per-child", "20", "--loglevel", "INFO"]
