from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimestampedModel
from orgs.models import Organization


class Job(TimestampedModel):
    """Durable record of background work. PostgreSQL is the record of truth;
    the Celery queue only schedules work and may lose or repeat messages."""

    class Kind(models.TextChoices):
        INTAKE_CHECK = "intake_check", "Drawing intake check"
        GEOMETRY_BENCHMARK = "geometry_benchmark", "Geometry benchmark"

    class State(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        WAITING_INPUT = "waiting_input"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        UNSUPPORTED = "unsupported"
        CANCELED = "canceled"

    class Stage(models.TextChoices):
        NONE = ""
        EXTRACTING = "extracting"
        MODELING = "modeling"
        VALIDATING = "validating"
        EXPORTING = "exporting"

    TERMINAL_STATES = {State.SUCCEEDED, State.FAILED, State.UNSUPPORTED, State.CANCELED}
    ACTIVE_STATES = {State.QUEUED, State.RUNNING, State.WAITING_INPUT}

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="jobs")
    revision = models.ForeignKey(
        "projects.PartRevision", null=True, blank=True, on_delete=models.CASCADE, related_name="jobs"
    )
    source_file = models.ForeignKey(
        "projects.SourceFile", null=True, blank=True, on_delete=models.CASCADE, related_name="jobs"
    )
    kind = models.CharField(max_length=40, choices=Kind.choices)
    state = models.CharField(max_length=20, choices=State.choices, default=State.QUEUED, db_index=True)
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.NONE, blank=True)
    idempotency_key = models.CharField(max_length=120)
    params = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=60, blank=True)
    error_message = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    deadline_seconds = models.PositiveIntegerField(default=900)
    lease_owner = models.CharField(max_length=120, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)
    queued_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    engine_versions = models.JSONField(default=dict, blank=True)
    usage = models.JSONField(default=dict, blank=True)
    processing_location = models.CharField(max_length=40, default="local")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind", "idempotency_key"], name="job_idempotency_unique"
            )
        ]
        indexes = [models.Index(fields=["state", "lease_expires_at"])]

    def __str__(self) -> str:
        return f"{self.kind} {self.state} {self.pk}"

    @property
    def is_terminal(self) -> bool:
        return self.state in self.TERMINAL_STATES

    @property
    def elapsed_seconds(self) -> float | None:
        if not self.started_at:
            return None
        end = self.finished_at or timezone.now()
        return round((end - self.started_at).total_seconds(), 3)


class JobEvent(models.Model):
    """Timeline of state and stage changes, shown to users and kept for audits."""

    id = models.BigAutoField(primary_key=True)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="events")
    at = models.DateTimeField(default=timezone.now)
    state = models.CharField(max_length=20)
    stage = models.CharField(max_length=20, blank=True)
    message = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["at", "id"]

    def __str__(self) -> str:
        return f"{self.at:%H:%M:%S} {self.state} {self.message}"
