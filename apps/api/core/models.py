import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    """UUID primary key plus creation/update timestamps.

    A UUID is an identifier, not an access control: every queryset that serves
    a request is filtered by organisation membership as well.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditEvent(models.Model):
    """Append-only record of security- and quality-relevant actions."""

    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(
        "orgs.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    actor_email = models.CharField(max_length=254, blank=True)
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.actor_email}"


class BackupRecord(models.Model):
    """Result of a backup or a restore drill, reported by the host scripts."""

    class Kind(models.TextChoices):
        BACKUP = "backup"
        RESTORE_DRILL = "restore_drill"

    class Status(models.TextChoices):
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    id = models.BigAutoField(primary_key=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices)
    location = models.CharField(max_length=500, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.kind} {self.status} {self.created_at:%Y-%m-%d %H:%M}"
