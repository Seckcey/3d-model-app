"""System health for administrators: database, cache, queues, workers, disk,
backups and email delivery."""

from __future__ import annotations

import shutil
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Min
from django.utils import timezone

from core.models import BackupRecord

from .models import Job

QUEUES = ("default", "extract", "cad")
PRIORITY_SEPARATOR = "\x06\x16"


def _check_db() -> dict:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return {"ok": True, "engine": connection.vendor}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}


def _check_cache() -> dict:
    try:
        cache.set("bpcad:health", "ok", 10)
        return {"ok": cache.get("bpcad:health") == "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}


def _queue_depths() -> dict:
    url = settings.CELERY_BROKER_URL
    if not url.startswith("redis"):
        return {"available": False}
    try:
        import redis

        client = redis.Redis.from_url(url, socket_timeout=2)
        depths = {}
        for queue in QUEUES:
            keys = [queue] + [f"{queue}{PRIORITY_SEPARATOR}{p}" for p in (3, 6, 9)]
            depths[queue] = sum(client.llen(k) for k in keys)
        return {"available": True, "depths": depths}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": type(exc).__name__}


def _workers() -> dict:
    from config.celery import app

    try:
        inspector = app.control.inspect(timeout=1.5)
        active_queues = inspector.active_queues() or {}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__, "workers": []}
    workers = [
        {"name": name, "queues": sorted(q["name"] for q in queues)}
        for name, queues in sorted(active_queues.items())
    ]
    consuming = {q for w in workers for q in w["queues"]}
    return {"ok": all(q in consuming for q in QUEUES), "workers": workers,
            "missing_queues": [q for q in QUEUES if q not in consuming]}


def _disk() -> dict:
    try:
        usage = shutil.disk_usage(settings.FILES_ROOT)
    except FileNotFoundError:
        return {"ok": False, "error": "FILES_ROOT missing"}
    percent = round(usage.used / usage.total * 100, 1) if usage.total else 0
    return {
        "ok": percent < settings.DISK_ALERT_PERCENT,
        "total_gb": round(usage.total / 1e9, 1),
        "free_gb": round(usage.free / 1e9, 1),
        "used_percent": percent,
        "alert_percent": settings.DISK_ALERT_PERCENT,
    }


def _jobs() -> dict:
    since = timezone.now() - timedelta(hours=24)
    by_state = dict(
        Job.objects.filter(created_at__gte=since)
        .order_by()
        .values_list("state")
        .annotate(n=Count("id"))
    )
    oldest = Job.objects.filter(state=Job.State.QUEUED).aggregate(oldest=Min("queued_at"))["oldest"]
    oldest_minutes = round((timezone.now() - oldest).total_seconds() / 60, 1) if oldest else 0
    return {
        "last_24h": by_state,
        "running": Job.objects.filter(state=Job.State.RUNNING).count(),
        "queued": Job.objects.filter(state=Job.State.QUEUED).count(),
        "oldest_queued_minutes": oldest_minutes,
        "alert_minutes": settings.QUEUE_ALERT_MINUTES,
    }


def _backups() -> dict:
    def describe(record):
        if record is None:
            return None
        return {"at": record.created_at.isoformat(), "status": record.status,
                "size_bytes": record.size_bytes, "location": record.location}

    last_ok = BackupRecord.objects.filter(kind=BackupRecord.Kind.BACKUP,
                                          status=BackupRecord.Status.SUCCEEDED).first()
    last_drill = BackupRecord.objects.filter(kind=BackupRecord.Kind.RESTORE_DRILL).first()
    age_hours = None
    if last_ok:
        age_hours = round((timezone.now() - last_ok.created_at).total_seconds() / 3600, 1)
    return {
        "ok": age_hours is not None and age_hours <= settings.BACKUP_ALERT_HOURS,
        "last_backup": describe(last_ok),
        "last_backup_age_hours": age_hours,
        "last_restore_drill": describe(last_drill),
        "alert_hours": settings.BACKUP_ALERT_HOURS,
    }


def gather(include_workers: bool = True) -> dict:
    report = {
        "version": {"app": settings.APP_VERSION, "git_sha": settings.GIT_SHA},
        "database": _check_db(),
        "cache": _check_cache(),
        "queues": _queue_depths(),
        "disk": _disk(),
        "jobs": _jobs(),
        "backups": _backups(),
        "email": {"delivery": settings.EMAIL_DELIVERY},
        "signup_mode": settings.SIGNUP_MODE,
        "checked_at": timezone.now().isoformat(),
    }
    if include_workers:
        report["workers"] = _workers()
    return report


def alerts(report: dict) -> list[dict]:
    found = []
    disk = report["disk"]
    if not disk.get("ok", True):
        found.append({"code": "disk", "title": "Disk usage high",
                      "message": f"Storage is {disk.get('used_percent')}% full "
                                 f"({disk.get('free_gb')} GB free)."})
    jobs = report["jobs"]
    if jobs["oldest_queued_minutes"] > settings.QUEUE_ALERT_MINUTES:
        found.append({"code": "backlog", "title": "Job backlog",
                      "message": f"A job has waited {jobs['oldest_queued_minutes']} minutes "
                                 "for a worker. Check that the workers are running."})
    backups = report["backups"]
    if not backups["ok"]:
        age = backups["last_backup_age_hours"]
        found.append({"code": "backup", "title": "Backup overdue",
                      "message": "No successful backup has been recorded."
                      if age is None else f"The last successful backup is {age} hours old."})
    if not report["database"]["ok"]:
        found.append({"code": "database", "title": "Database unavailable",
                      "message": "The API could not reach PostgreSQL."})
    return found
