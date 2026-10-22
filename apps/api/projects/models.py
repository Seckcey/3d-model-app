from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import TimestampedModel
from orgs.models import Organization


class Customer(TimestampedModel):
    """The shop's customer (who sent the drawing)."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=160)
    code = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="customer_name_unique")
        ]

    def __str__(self) -> str:
        return self.name


class Project(TimestampedModel):
    """A customer job, RFQ or PO that groups one or more parts."""

    class Status(models.TextChoices):
        ACTIVE = "active"
        ON_HOLD = "on_hold"
        COMPLETE = "complete"
        ARCHIVED = "archived"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="projects")
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects"
    )
    name = models.CharField(max_length=160)
    reference = models.CharField(max_length=80, blank=True, help_text="PO, RFQ or job number")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    due_date = models.DateField(null=True, blank=True)
    external_ai_allowed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.name


class Part(TimestampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="parts")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="parts")
    part_number = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True)
    material = models.CharField(max_length=120, blank=True)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["part_number"]
        constraints = [
            models.UniqueConstraint(fields=["project", "part_number"], name="part_number_unique")
        ]
        indexes = [models.Index(fields=["organization", "part_number"])]

    def __str__(self) -> str:
        return self.part_number


class ExportControl(models.TextChoices):
    NONE_FOUND = "none_found", "No marking found"
    NOT_SCANNED = "not_scanned", "Not scanned (raster page)"
    DETECTED = "detected", "Export-control marking detected"
    CONFIRMED = "confirmed", "Confirmed controlled"
    CLEARED = "cleared", "Reviewed: not controlled"


class PartRevision(TimestampedModel):
    """One modelling iteration of a part against a specific customer drawing revision.

    ``drawing_revision`` is the customer's letter (e.g. "C"); ``sequence`` is
    our own iteration counter. Revisions become immutable once generated.
    """

    class State(models.TextChoices):
        DRAFT = "draft"
        NEEDS_INPUT = "needs_input"
        READY_FOR_REVIEW = "ready_for_review"
        APPROVED = "approved"
        RELEASED = "released"
        SUPERSEDED = "superseded"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="revisions")
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="revisions")
    drawing_revision = models.CharField(max_length=20, blank=True)
    sequence = models.PositiveIntegerField()
    state = models.CharField(max_length=24, choices=State.choices, default=State.DRAFT)
    external_ai_allowed = models.BooleanField(default=False)
    export_control = models.CharField(
        max_length=20, choices=ExportControl.choices, default=ExportControl.NOT_SCANNED
    )
    export_control_markings = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-sequence"]
        constraints = [
            models.UniqueConstraint(fields=["part", "sequence"], name="revision_sequence_unique")
        ]

    def __str__(self) -> str:
        return f"{self.part} rev {self.drawing_revision or '?'} #{self.sequence}"

    @property
    def effective_external_ai(self) -> bool:
        """External AI may run only if org, project and revision all allow it and
        a person has recorded that the drawing is not export controlled.

        Drawings are treated as controlled until cleared: an unmarked drawing is
        not proof that it is uncontrolled, so "no marking found" is not enough.
        """
        org = self.organization
        project = self.part.project
        return bool(
            org.allow_external_ai
            and project.external_ai_allowed
            and self.external_ai_allowed
            and self.export_control == ExportControl.CLEARED
        )


class SourceFile(TimestampedModel):
    """An immutable original drawing. Never modified after upload."""

    class IntakeStatus(models.TextChoices):
        PENDING = "pending"
        OK = "ok"
        WARNING = "warning"
        FAILED = "failed"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="source_files")
    revision = models.ForeignKey(PartRevision, on_delete=models.CASCADE, related_name="source_files")
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=60)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    page_count = models.PositiveIntegerField(default=1)
    storage_path = models.CharField(max_length=500)
    selected_pages = models.JSONField(default=list, blank=True)
    intake_status = models.CharField(
        max_length=20, choices=IntakeStatus.choices, default=IntakeStatus.PENDING
    )
    intake_report = models.JSONField(default=dict, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["revision", "sha256"], name="sourcefile_unique_per_revision")
        ]

    def __str__(self) -> str:
        return self.original_name


class Artifact(TimestampedModel):
    """A generated file (thumbnail, STEP, DXF, GLB, report). Written to staging,
    hashed, then published atomically together with this row."""

    class Kind(models.TextChoices):
        PAGE_IMAGE = "page_image"
        THUMBNAIL = "thumbnail"
        STEP = "step"
        DXF = "dxf"
        GLB = "glb"
        REPORT = "report"
        MANIFEST = "manifest"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="artifacts")
    revision = models.ForeignKey(
        PartRevision, null=True, blank=True, on_delete=models.CASCADE, related_name="artifacts"
    )
    source_file = models.ForeignKey(
        SourceFile, null=True, blank=True, on_delete=models.CASCADE, related_name="artifacts"
    )
    job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="artifacts"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    variant = models.CharField(max_length=40, blank=True)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=80)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_path = models.CharField(max_length=500)
    is_draft = models.BooleanField(default=True)
    released_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.filename
