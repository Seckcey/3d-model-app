from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import models

from .models import AuditEvent

logger = logging.getLogger("bpcad.audit")


def client_ip(request) -> str | None:
    if request is None:
        return None
    if getattr(settings, "BEHIND_PROXY", False):
        ip = request.headers.get("X-Client-IP")
        if ip:
            return ip.strip()
    return request.META.get("REMOTE_ADDR")


def record(
    action: str,
    *,
    request=None,
    actor=None,
    organization=None,
    target: models.Model | None = None,
    **data: Any,
) -> AuditEvent:
    """Write an audit event. Never pass drawing content or login codes in data."""
    if actor is None and request is not None and getattr(request, "user", None) is not None:
        if request.user.is_authenticated:
            actor = request.user
    event = AuditEvent.objects.create(
        organization=organization,
        actor=actor,
        actor_email=getattr(actor, "email", "") or "",
        action=action,
        target_type=target._meta.label_lower if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        ip=client_ip(request),
        data=data,
    )
    logger.info("audit %s org=%s target=%s:%s", action, getattr(organization, "pk", None),
                event.target_type, event.target_id)
    return event
