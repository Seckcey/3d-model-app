#!/bin/sh
# Roles: web (migrate + gunicorn), worker (Celery extract/default queues),
# scheduler (Celery beat), manage <command...>, or any other command.
set -eu

role="${1:-web}"
[ "$#" -gt 0 ] && shift

case "$role" in
  web)
    python manage.py wait_for_db --timeout 180
    python manage.py migrate --noinput
    exec gunicorn config.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-3}" \
      --threads "${GUNICORN_THREADS:-4}" \
      --timeout 120 \
      --worker-tmp-dir /dev/shm \
      --forwarded-allow-ips "*" \
      --access-logfile - \
      --access-logformat '%(t)s %(m)s %(U)s %(s)s %(b)s %(L)ss'
    ;;
  worker)
    python manage.py wait_for_db --timeout 180
    exec celery -A config worker \
      --queues "${WORKER_QUEUES:-extract,default}" \
      --concurrency "${WORKER_CONCURRENCY:-2}" \
      --hostname "extract@%h" \
      --max-tasks-per-child 50 \
      --loglevel INFO
    ;;
  scheduler)
    python manage.py wait_for_db --timeout 180
    exec celery -A config beat --schedule /tmp/celerybeat-schedule --loglevel INFO
    ;;
  manage)
    exec python manage.py "$@"
    ;;
  *)
    exec "$role" "$@"
    ;;
esac
