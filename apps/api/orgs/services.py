from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from core import audit

from .models import ROLE_VALUES, Invitation, Membership, Organization, Role, hash_token

logger = logging.getLogger("bpcad.orgs")
SESSION_INVITATION_KEY = "bpcad_invitation_token"


def clean_roles(roles) -> list[str]:
    if not isinstance(roles, list) or not roles:
        raise ValidationError({"roles": "Choose at least one role."})
    cleaned = sorted({str(role) for role in roles})
    unknown = set(cleaned) - ROLE_VALUES
    if unknown:
        raise ValidationError({"roles": f"Unknown role(s): {', '.join(sorted(unknown))}"})
    return cleaned


def unique_slug(name: str) -> str:
    base = slugify(name)[:60] or "shop"
    slug, n = base, 2
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


@transaction.atomic
def create_organization(*, name: str, owner, request=None) -> Organization:
    org = Organization.objects.create(name=name.strip(), slug=unique_slug(name), created_by=owner)
    Membership.objects.create(
        organization=org, user=owner, roles=[Role.OWNER, Role.ENGINEER, Role.REVIEWER]
    )
    audit.record("organization.created", request=request, actor=owner, organization=org, target=org)
    return org


def invitation_link(token: str) -> str:
    return f"{settings.PUBLIC_URL}/invite/{token}"


def send_invitation_email(invitation: Invitation, token: str) -> None:
    inviter = invitation.invited_by
    context = {
        "product_name": settings.PRODUCT_NAME,
        "organization": invitation.organization.name,
        "inviter": inviter.get_full_name() if inviter else "A workspace owner",
        "roles": ", ".join(invitation.roles),
        "link": invitation_link(token),
        "expires_at": invitation.expires_at,
    }
    subject = render_to_string("emails/invitation_subject.txt", context).strip()
    body = render_to_string("emails/invitation_message.txt", context)
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [invitation.email])
    except Exception:  # noqa: BLE001 - the invitation exists; the owner can resend
        logger.exception("invitation email to %s failed", invitation.email)
        audit.record("invitation.email_failed", organization=invitation.organization,
                     target=invitation, email=invitation.email)
        return
    invitation.last_sent_at = timezone.now()
    invitation.save(update_fields=["last_sent_at", "updated_at"])


@transaction.atomic
def create_invitation(*, organization: Organization, email: str, roles, invited_by, request=None):
    email = email.strip().lower()
    roles = clean_roles(roles)
    if Membership.objects.filter(organization=organization, user__email__iexact=email).exists():
        raise ValidationError({"email": "This person is already a member of the workspace."})
    # A new invitation replaces any pending one for the same address.
    now = timezone.now()
    for old in Invitation.objects.select_for_update().filter(
        organization=organization, email=email, accepted_at__isnull=True, revoked_at__isnull=True
    ):
        old.revoked_at = now
        old.save(update_fields=["revoked_at", "updated_at"])
    token, token_hash = Invitation.new_token()
    invitation = Invitation.objects.create(
        organization=organization,
        email=email,
        roles=roles,
        token_hash=token_hash,
        invited_by=invited_by,
        expires_at=Invitation.default_expiry(),
    )
    audit.record(
        "invitation.created", request=request, organization=organization, target=invitation,
        email=email, roles=roles,
    )
    transaction.on_commit(lambda: send_invitation_email(invitation, token))
    return invitation, token


@transaction.atomic
def resend_invitation(invitation: Invitation, request=None) -> str:
    """Rotate the token (old links stop working) and send it again."""
    if not invitation.is_pending:
        raise ValidationError({"detail": "Only pending invitations can be resent."})
    token, token_hash = Invitation.new_token()
    invitation.token_hash = token_hash
    invitation.expires_at = Invitation.default_expiry()
    invitation.save(update_fields=["token_hash", "expires_at", "updated_at"])
    audit.record("invitation.resent", request=request, organization=invitation.organization,
                 target=invitation, email=invitation.email)
    transaction.on_commit(lambda: send_invitation_email(invitation, token))
    return token


def revoke_invitation(invitation: Invitation, request=None) -> None:
    if invitation.accepted_at:
        raise ValidationError({"detail": "This invitation was already accepted."})
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at", "updated_at"])
    audit.record("invitation.revoked", request=request, organization=invitation.organization,
                 target=invitation, email=invitation.email)


def find_invitation(token: str) -> Invitation | None:
    if not token or len(token) > 200:
        return None
    return (
        Invitation.objects.select_related("organization", "invited_by")
        .filter(token_hash=hash_token(token))
        .first()
    )


def pending_invitation_from_session(request) -> Invitation | None:
    token = request.session.get(SESSION_INVITATION_KEY) if request is not None else None
    invitation = find_invitation(token) if token else None
    if invitation and invitation.is_pending:
        return invitation
    return None


def user_has_verified_email(user, email: str) -> bool:
    from allauth.account.models import EmailAddress

    return EmailAddress.objects.filter(user=user, email__iexact=email, verified=True).exists()


@transaction.atomic
def accept_invitation(invitation: Invitation, user, request=None) -> Membership:
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if not invitation.is_pending:
        raise ValidationError({"detail": f"This invitation is {invitation.status}."})
    if not user_has_verified_email(user, invitation.email):
        raise ValidationError(
            {"detail": f"This invitation was sent to {invitation.email}. Sign in with that address."}
        )
    membership, created = Membership.objects.get_or_create(
        organization=invitation.organization,
        user=user,
        defaults={"roles": invitation.roles, "invited_by": invitation.invited_by},
    )
    if not created:
        membership.roles = sorted(set(membership.roles) | set(invitation.roles))
        membership.save(update_fields=["roles", "updated_at"])
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["accepted_at", "accepted_by", "updated_at"])
    if request is not None:
        request.session.pop(SESSION_INVITATION_KEY, None)
    audit.record("invitation.accepted", request=request, actor=user,
                 organization=invitation.organization, target=invitation, roles=membership.roles)
    return membership


def _owner_count(organization: Organization, exclude: Membership | None = None) -> int:
    qs = Membership.objects.filter(organization=organization)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return sum(1 for m in qs if Role.OWNER in m.roles)


@transaction.atomic
def update_member_roles(membership: Membership, roles, request=None) -> Membership:
    roles = clean_roles(roles)
    if Role.OWNER in membership.roles and Role.OWNER not in roles:
        if _owner_count(membership.organization, exclude=membership) == 0:
            raise ValidationError({"roles": "A workspace needs at least one owner."})
    before = list(membership.roles)
    membership.roles = roles
    membership.save(update_fields=["roles", "updated_at"])
    audit.record("member.roles_changed", request=request, organization=membership.organization,
                 target=membership, user=membership.user.email, before=before, after=roles)
    return membership


@transaction.atomic
def remove_member(membership: Membership, request=None) -> None:
    if Role.OWNER in membership.roles and _owner_count(membership.organization, exclude=membership) == 0:
        raise ValidationError({"detail": "You cannot remove the last owner of a workspace."})
    audit.record("member.removed", request=request, organization=membership.organization,
                 target=membership, user=membership.user.email, roles=membership.roles)
    membership.delete()


def end_user_sessions(user, *, except_session_key: str | None = None) -> int:
    """End every tracked browser session of a user (immediate sign-out)."""
    from allauth.usersessions.models import UserSession

    count = 0
    for session in UserSession.objects.filter(user=user):
        if except_session_key and session.session_key == except_session_key:
            continue
        session.end()
        count += 1
    return count
