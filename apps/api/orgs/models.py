from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimestampedModel


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    ENGINEER = "engineer", "Engineer"
    REVIEWER = "reviewer", "Reviewer"
    VIEWER = "viewer", "Viewer"


ROLE_VALUES = {choice.value for choice in Role}


class Capability:
    VIEW = "view"
    DOWNLOAD_SOURCES = "download_sources"
    EDIT = "edit"
    APPROVE = "approve"
    MANAGE = "manage"


# Which roles grant which capability. A person may hold several roles; a small
# shop's owner usually holds owner + engineer + reviewer.
CAPABILITY_ROLES: dict[str, set[str]] = {
    Capability.VIEW: {Role.OWNER, Role.ENGINEER, Role.REVIEWER, Role.VIEWER},
    Capability.DOWNLOAD_SOURCES: {Role.OWNER, Role.ENGINEER, Role.REVIEWER},
    Capability.EDIT: {Role.ENGINEER},
    Capability.APPROVE: {Role.REVIEWER},
    Capability.MANAGE: {Role.OWNER},
}


def roles_grant(roles: list[str] | set[str], capability: str) -> bool:
    return bool(set(roles) & CAPABILITY_ROLES[capability])


# Shop modelling preferences. They are recorded from Phase 1 so the geometry
# pipeline (Phase 3) can honour how this shop programs parts. Each one answers
# a recurring CAM-programmer complaint (see docs/research/machinist-needs.md).
PREFERENCE_CHOICES: dict[str, tuple[str, ...]] = {
    "drawing_units": ("in", "mm"),
    "projection": ("third_angle", "first_angle"),
    # Mastercam/Fusion hole recognition sees only cylinders, so the shop picks
    # how a tapped hole is represented in the solid.
    "tapped_hole_model": ("tap_drill", "tap_drill_with_major_step", "major_diameter",
                          "minor_diameter"),
    "tap_drill_basis": ("cut_tap", "form_tap", "thread_mill"),
    "model_tolerance": ("nominal", "mid_tolerance"),
    "origin": ("datum_abc", "stock_corner", "stock_top_center", "part_center"),
    # "drawing" exports in the units the print was drawn in: no silent conversion.
    "step_units": ("drawing", "in", "mm"),
    "step_schema": ("AP214", "AP242"),
    "dxf_version": ("R12", "R2000"),
}
DEFAULT_PREFERENCES: dict[str, object] = {
    "drawing_units": "in",
    "projection": "third_angle",
    "tapped_hole_model": "tap_drill",
    "tap_drill_basis": "cut_tap",
    "model_tolerance": "nominal",
    "also_export_mid_tolerance": True,
    "color_faces_by_tolerance": True,
    "color_faces_by_hole_type": True,
    "origin": "datum_abc",
    "include_stock_body": False,
    "step_units": "drawing",
    "step_schema": "AP214",
    "dxf_version": "R12",
    "filename_pattern": "{part}_REV{rev}_{kind}",
    "cam_software": "",
    "stock_allowance_in": 0.125,
}
BOOLEAN_PREFERENCES = ("also_export_mid_tolerance", "color_faces_by_tolerance",
                       "color_faces_by_hole_type", "include_stock_body")
FILENAME_TOKENS = ("{part}", "{rev}", "{kind}", "{customer}", "{seq}")


class Organization(TimestampedModel):
    """A shop workspace. Every project, file, job and artifact belongs to one."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Local-only by default: drawings are sent to an external AI provider only
    # when the owner allows it here and the project allows it too.
    allow_external_ai = models.BooleanField(default=False)
    allowed_ai_providers = models.JSONField(default=list, blank=True)
    max_upload_mb = models.PositiveIntegerField(default=25)
    max_pdf_pages = models.PositiveIntegerField(default=20)
    max_active_generation_jobs = models.PositiveIntegerField(default=1)
    retention_days = models.PositiveIntegerField(null=True, blank=True)
    monthly_ai_budget_usd = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    preferences = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def effective_preferences(self) -> dict:
        merged = dict(DEFAULT_PREFERENCES)
        merged.update({k: v for k, v in (self.preferences or {}).items() if k in DEFAULT_PREFERENCES})
        return merged


class Membership(TimestampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    roles = models.JSONField(default=list)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="membership_unique")
        ]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization} {self.roles}"

    def can(self, capability: str) -> bool:
        return roles_grant(self.roles, capability)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Invitation(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        REVOKED = "revoked"
        EXPIRED = "expired"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    roles = models.JSONField(default=list)
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Invitation {self.email} -> {self.organization}"

    @classmethod
    def new_token(cls) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        return token, hash_token(token)

    @staticmethod
    def default_expiry():
        return timezone.now() + timedelta(days=settings.INVITATION_DAYS)

    @property
    def status(self) -> str:
        if self.accepted_at:
            return self.Status.ACCEPTED
        if self.revoked_at:
            return self.Status.REVOKED
        if self.expires_at <= timezone.now():
            return self.Status.EXPIRED
        return self.Status.PENDING

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING
