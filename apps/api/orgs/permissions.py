"""Organisation membership checks used by every view.

The rule: a request may only see rows whose organisation the user belongs to,
and may only act when one of their roles in *that* organisation grants the
capability. Unknown or foreign IDs return 404 so they reveal nothing.
"""

from __future__ import annotations

from uuid import UUID

from rest_framework.exceptions import NotFound, PermissionDenied

from .models import Capability, Membership


def _cache(request) -> dict:
    cache = getattr(request, "_bpcad_memberships", None)
    if cache is None:
        cache = {
            str(m.organization_id): m
            for m in Membership.objects.filter(user=request.user, organization__is_active=True)
        }
        request._bpcad_memberships = cache
    return cache


def memberships(request) -> dict[str, Membership]:
    if not request.user.is_authenticated:
        return {}
    return _cache(request)


def member_org_ids(request) -> list[str]:
    return list(memberships(request).keys())


def membership_for(request, organization_id: UUID | str) -> Membership | None:
    return memberships(request).get(str(organization_id))


def require_capability(request, organization_id: UUID | str, capability: str) -> Membership:
    membership = membership_for(request, organization_id)
    if membership is None:
        raise NotFound()
    if not membership.can(capability):
        raise PermissionDenied(_DENIED.get(capability, "Your role does not allow this action."))
    return membership


_DENIED = {
    Capability.EDIT: "Only engineers can change projects, parts or drawings.",
    Capability.APPROVE: "Only reviewers can approve a revision.",
    Capability.MANAGE: "Only workspace owners can do this.",
    Capability.DOWNLOAD_SOURCES: "Viewers can download released files only.",
}
