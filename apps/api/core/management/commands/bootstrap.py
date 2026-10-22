from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from orgs.models import Membership, Organization, Role
from orgs.services import create_organization


class Command(BaseCommand):
    help = "Create (or update) the first administrator and their shop workspace. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--org", required=True, help="Workspace (shop) name")
        parser.add_argument("--name", default="", help="Administrator display name")

    @transaction.atomic
    def handle(self, *args, email: str, org: str, name: str, **options):
        email = email.strip().lower()
        if "@" not in email:
            raise CommandError("A valid email address is required")
        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create_superuser(email=email, full_name=name)
            self.stdout.write(f"Created administrator {email}")
        else:
            user.is_staff = user.is_superuser = user.is_active = True
            if name:
                user.full_name = name
            user.save()
            self.stdout.write(f"Administrator {email} already exists; ensured admin rights")
        address, _ = EmailAddress.objects.get_or_create(
            user=user, email=email, defaults={"verified": True, "primary": True}
        )
        if not address.verified or not address.primary:
            address.verified = address.primary = True
            address.save()

        organization = Organization.objects.filter(name__iexact=org.strip()).first()
        if organization is None:
            organization = create_organization(name=org, owner=user)
            self.stdout.write(f"Created workspace '{organization.name}'")
        membership, created = Membership.objects.get_or_create(
            organization=organization, user=user,
            defaults={"roles": [Role.OWNER, Role.ENGINEER, Role.REVIEWER]},
        )
        if not created and Role.OWNER not in membership.roles:
            membership.roles = sorted(set(membership.roles) | {Role.OWNER})
            membership.save()
        self.stdout.write(self.style.SUCCESS(
            f"Ready: {email} is an owner of '{organization.name}'. Sign in with an email code."
        ))
