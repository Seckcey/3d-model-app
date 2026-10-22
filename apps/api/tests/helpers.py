from __future__ import annotations

import re

from allauth.account.models import EmailAddress
from django.core import mail
from rest_framework.test import APIClient

from accounts.models import User
from orgs.models import Membership, Organization, Role

CODE_RE = re.compile(r"^\s{2,}(\d{6})\s*$", re.M)


def make_user(email: str, *, staff: bool = False, verified: bool = True) -> User:
    user = User.objects.create_user(email=email, is_staff=staff)
    EmailAddress.objects.create(user=user, email=email, verified=verified, primary=True)
    return user


def make_org(name: str, owner: User, roles=None) -> Organization:
    org = Organization.objects.create(name=name, slug=name.lower().replace(" ", "-"))
    Membership.objects.create(organization=org, user=owner,
                              roles=roles or [Role.OWNER, Role.ENGINEER, Role.REVIEWER])
    return org


def add_member(org: Organization, user: User, roles) -> Membership:
    return Membership.objects.create(organization=org, user=user, roles=list(roles))


def client_for(user: User) -> APIClient:
    client = APIClient()
    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    return client


def latest_code(email: str) -> str:
    for message in reversed(mail.outbox):
        if email in message.to:
            match = CODE_RE.search(message.body)
            if match:
                return match.group(1)
    raise AssertionError(f"no code sent to {email}")
