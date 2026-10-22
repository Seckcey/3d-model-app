"""Job lifecycle: idempotent creation, leased claims, heartbeats, fenced
completion and reconciliation of abandoned work.

Workers never trust a queue message on its own: a message only names a job,
and the worker must win an atomic claim on the database row before doing any
work. Completion is fenced by the lease owner, so a worker whose lease expired
cannot overwrite the result of the worker that replaced it.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import APIException

from .models import Job, JobEvent

logger = logging.getLogger("bpcad.jobs")

LEASE_GRACE_SECONDS = 120
REDISPATCH_AFTER = timedelta(minutes=10)
GEOMETRY_KINDS = {Job.Kind.GEOMETRY_BENCHMARK}

TASKS = {
    Job.Kind.INTAKE_CHECK: ("jobs.run_intake", "extract"),
    Job.Kind.GEOMETRY_BENCHMARK: ("jobs.start_geometry", "default"),
}


class JobConflict(APIException):
    status_code = 409
    default_code = "job_conflict"
    default_detail = "A conflicting job is already active."


class LeaseLost(Exception):
    """The worker no longer owns the job; its results must be discarded."""


def log_event(job: Job, message: str = "") -> None:
    JobEvent.objects.create(job=job, state=job.state, stage=job.stage, message=message[:500])


def create_job(
    *,
    organization,
    kind: str,
    idempotency_key: str,
    requested_by=None,
    revision=None,
    source_file=None,
    params: dict | None = None,
    deadline_seconds: int = 900,
    max_attempts: int = 3,
    processing_location: str = "local",
) -> tuple[Job, bool]:
    with transaction.atomic():
        existing = Job.objects.filter(
            organization=organization, kind=kind, idempotency_key=idempotency_key
        ).first()
        if existing:
            return existing, False
        if kind in GEOMETRY_KINDS:
            # Lock the organisation row so concurrent requests cannot both pass the limit.
            type(organization).objects.select_for_update().get(pk=organization.pk)
            active = Job.objects.filter(
                organization=organization, kind__in=GEOMETRY_KINDS, state__in=Job.ACTIVE_STATES
            ).count()
            if active >= organization.max_active_generation_jobs:
                raise JobConflict("A geometry job is already running for this workspace. "
                                  "Wait for it to finish or cancel it.")
        job, created = Job.objects.get_or_create(
            organization=organization,
            kind=kind,
            idempotency_key=idempotency_key,
            defaults={
                "requested_by": requested_by,
                "revision": revision,
                "source_file": source_file,
                "params": params or {},
                "deadline_seconds": deadline_seconds,
                "max_attempts": max_attempts,
                "processing_location": processing_location,
            },
        )
        if created:
            log_event(job, "Queued")
            transaction.on_commit(lambda: dispatch(job.pk))
    return job, created


def dispatch(job_id, countdown: int | None = None) -> None:
    from config.celery import app

    job = Job.objects.filter(pk=job_id).only("kind").first()
    if job is None:
        return
    name, queue = TASKS[job.kind]
    try:
        app.send_task(name, args=[str(job_id)], queue=queue, countdown=countdown)
    except Exception:  # noqa: BLE001 - the reconciler re-dispatches queued jobs
        logger.exception("dispatch failed for job %s; reconciler will retry", job_id)


def claim(job_id, worker: str) -> Job | None:
    now = timezone.now()
    job = Job.objects.filter(pk=job_id).only("deadline_seconds").first()
    if job is None:
        return None
    lease_until = now + timedelta(seconds=job.deadline_seconds + LEASE_GRACE_SECONDS)
    won = Job.objects.filter(pk=job_id, state=Job.State.QUEUED, cancel_requested=False).update(
        state=Job.State.RUNNING,
        attempts=F("attempts") + 1,
        lease_owner=worker,
        lease_expires_at=lease_until,
        heartbeat_at=now,
        started_at=Coalesce(F("started_at"), Value(now)),
        updated_at=now,
    )
    if not won:
        return None
    job = Job.objects.select_related("organization", "source_file", "revision").get(pk=job_id)
    log_event(job, f"Started (attempt {job.attempts} of {job.max_attempts})")
    return job


def heartbeat(job: Job, worker: str, *, stage: str | None = None) -> bool:
    """Extend the lease. Returns False if the worker lost the job or it was canceled."""
    now = timezone.now()
    fields = {
        "heartbeat_at": now,
        "lease_expires_at": now + timedelta(seconds=job.deadline_seconds + LEASE_GRACE_SECONDS),
        "updated_at": now,
    }
    if stage is not None:
        fields["stage"] = stage
    updated = Job.objects.filter(
        pk=job.pk, state=Job.State.RUNNING, lease_owner=worker, cancel_requested=False
    ).update(**fields)
    if updated and stage is not None and stage != job.stage:
        job.stage = stage
        log_event(job, f"Stage: {stage}")
    return bool(updated)


def finish(
    job: Job,
    worker: str,
    *,
    state: str = Job.State.SUCCEEDED,
    result: dict | None = None,
    error_code: str = "",
    error_message: str = "",
    usage: dict | None = None,
    engine_versions: dict | None = None,
    message: str = "",
) -> None:
    """Record a terminal state. Raises LeaseLost if another worker owns the job."""
    now = timezone.now()
    fields = {
        "state": state,
        "finished_at": now,
        "lease_owner": "",
        "lease_expires_at": None,
        "error_code": error_code,
        "error_message": error_message[:2000],
        "updated_at": now,
    }
    if result is not None:
        fields["result"] = result
    if usage is not None:
        fields["usage"] = usage
    if engine_versions is not None:
        fields["engine_versions"] = engine_versions
    updated = Job.objects.filter(pk=job.pk, state=Job.State.RUNNING, lease_owner=worker).update(**fields)
    if not updated:
        raise LeaseLost(str(job.pk))
    job.refresh_from_db()
    log_event(job, message or state.capitalize())


def fail_or_retry(job: Job, worker: str, *, error_code: str, message: str, retryable: bool) -> None:
    job.refresh_from_db(fields=["attempts", "max_attempts", "cancel_requested"])
    if job.cancel_requested:
        try:
            finish(job, worker, state=Job.State.CANCELED, message="Canceled")
        except LeaseLost:
            pass
        return
    if retryable and job.attempts < job.max_attempts:
        now = timezone.now()
        updated = Job.objects.filter(pk=job.pk, state=Job.State.RUNNING, lease_owner=worker).update(
            state=Job.State.QUEUED, lease_owner="", lease_expires_at=None, stage="",
            error_code=error_code, error_message=message[:2000], updated_at=now,
        )
        if updated:
            job.refresh_from_db()
            log_event(job, f"Retrying after error: {message[:200]}")
            dispatch(job.pk, countdown=min(300, 15 * 2 ** job.attempts))
        return
    try:
        finish(job, worker, state=Job.State.FAILED, error_code=error_code, error_message=message,
               message=f"Failed: {message[:200]}")
    except LeaseLost:
        pass


def cancel(job: Job) -> Job:
    now = timezone.now()
    with transaction.atomic():
        job = Job.objects.select_for_update().get(pk=job.pk)
        if job.is_terminal:
            return job
        if job.state in {Job.State.QUEUED, Job.State.WAITING_INPUT}:
            job.state = Job.State.CANCELED
            job.finished_at = now
            job.cancel_requested = True
            job.save(update_fields=["state", "finished_at", "cancel_requested", "updated_at"])
            log_event(job, "Canceled")
        else:
            job.cancel_requested = True
            job.save(update_fields=["cancel_requested", "updated_at"])
            log_event(job, "Cancellation requested")
    return job


def reconcile() -> dict:
    """Repair state from the database: expired leases and lost messages."""
    now = timezone.now()
    stats = {"requeued": 0, "failed": 0, "canceled": 0, "redispatched": 0}
    expired = Job.objects.filter(state=Job.State.RUNNING, lease_expires_at__lt=now)
    for job in expired:
        with transaction.atomic():
            job = Job.objects.select_for_update().get(pk=job.pk)
            if job.state != Job.State.RUNNING or not job.lease_expires_at or job.lease_expires_at >= now:
                continue
            job.lease_owner = ""
            job.lease_expires_at = None
            if job.cancel_requested:
                job.state, job.finished_at = Job.State.CANCELED, now
                stats["canceled"] += 1
                note = "Canceled (worker stopped)"
            elif job.attempts < job.max_attempts:
                job.state, job.stage = Job.State.QUEUED, ""
                stats["requeued"] += 1
                note = "Worker stopped responding; requeued"
            else:
                job.state, job.finished_at = Job.State.FAILED, now
                job.error_code = "lease_expired"
                job.error_message = ("The worker stopped responding and the retry budget is used up. "
                                     "Try again, and report the part if it keeps failing.")
                stats["failed"] += 1
                note = "Failed: worker stopped responding"
            job.save()
            log_event(job, note)
            if job.state == Job.State.QUEUED:
                transaction.on_commit(lambda pk=job.pk: dispatch(pk))
    stale = Job.objects.filter(state=Job.State.QUEUED, updated_at__lt=now - REDISPATCH_AFTER)
    for job in stale:
        Job.objects.filter(pk=job.pk, state=Job.State.QUEUED).update(updated_at=now)
        dispatch(job.pk)
        stats["redispatched"] += 1
    return stats
