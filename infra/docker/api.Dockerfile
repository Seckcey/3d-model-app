# API, extraction worker and scheduler image (same code, different command).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY apps/api/ /app/
COPY packages/feature-spec/ /app/feature-spec/
COPY infra/docker/api-entrypoint.sh /usr/local/bin/api-entrypoint
RUN chmod 0755 /usr/local/bin/api-entrypoint \
 && rm -rf /app/tests /app/var

ARG APP_VERSION=0.1.0
ARG GIT_SHA=dev
ENV APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    FEATURE_SPEC_DIR=/app/feature-spec \
    STATIC_ROOT=/app/staticfiles \
    FILES_ROOT=/data/files \
    STAGING_ROOT=/data/files/staging \
    OUTBOX_DIR=/data/outbox

RUN DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput >/dev/null \
 && chown -R app:app /app/staticfiles \
 && chmod -R u+rwX,g+rX,o+rX /app/staticfiles

USER app
EXPOSE 8000
ENTRYPOINT ["api-entrypoint"]
CMD ["web"]
