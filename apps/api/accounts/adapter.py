from __future__ import annotations

import time

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core import context as allauth_context
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError

from orgs.services import pending_invitation_from_session


def login_code_sent_key(email: str) -> str:
    return f"bpcad:logincode:sent:{email.strip().lower()}"


class AccountAdapter(DefaultAccountAdapter):
    """Email-code sign in with invitation-gated signup.

    During the pilot (SIGNUP_MODE=invite_only) a new account can only be
    created by someone holding a valid invitation, and only for the invited
    address. Matching email domains never grant access to a workspace.
    """

    def is_open_for_signup(self, request) -> bool:
        if settings.SIGNUP_MODE == "open":
            return True
        return pending_invitation_from_session(request) is not None

    def clean_email(self, email: str) -> str:
        email = super().clean_email(email).strip().lower()
        request = getattr(allauth_context, "request", None)
        if (
            request is not None
            and settings.SIGNUP_MODE != "open"
            and request.path.rstrip("/").endswith("/auth/signup")
        ):
            # Without an invitation is_open_for_signup() refuses with 403; with one,
            # the account must be for the invited address.
            invitation = pending_invitation_from_session(request)
            if invitation is not None and invitation.email != email:
                raise ValidationError("Use the email address this invitation was sent to.")
        return email

    def send_mail(self, template_prefix: str, email: str, context: dict) -> None:
        if template_prefix == "account/email/login_code":
            cache.set(login_code_sent_key(email), time.time(), timeout=3600)
        context = {
            "product_name": settings.PRODUCT_NAME,
            "public_url": settings.PUBLIC_URL,
            "code_minutes": settings.ACCOUNT_LOGIN_BY_CODE_TIMEOUT // 60,
            "signup_mode": settings.SIGNUP_MODE,
            **context,
        }
        super().send_mail(template_prefix, email, context)
