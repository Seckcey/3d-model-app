import re

from django.conf import settings
from django.core.management.base import BaseCommand

from core.mail import read_outbox

CODE = re.compile(r"^\s{2,}(\d{6})\s*$", re.M)
LINK = re.compile(r"https?://\S+/invite/\S+")


class Command(BaseCommand):
    help = ("Show messages written to the local outbox (used until an SMTP relay is configured). "
            "Only people with shell access to the server can run this.")

    def add_arguments(self, parser):
        parser.add_argument("--to", help="Only messages to this address")
        parser.add_argument("--limit", type=int, default=5)
        parser.add_argument("--code", action="store_true",
                            help="Print only the newest sign-in/verification code")
        parser.add_argument("--link", action="store_true",
                            help="Print only the newest invitation link")

    def handle(self, *args, to=None, limit=5, code=False, link=False, **options):
        if settings.EMAIL_DELIVERY != "outbox":
            self.stderr.write("Email is delivered by SMTP; the outbox is not in use.")
        messages = read_outbox(limit=50 if (code or link) else limit, to=to)
        if code or link:
            pattern = CODE if code else LINK
            for message in messages:
                match = pattern.search(message["body"])
                if match:
                    self.stdout.write(match.group(1) if code else match.group(0))
                    return
            self.stderr.write("No matching message found.")
            raise SystemExit(1)
        if not messages:
            self.stdout.write("Outbox is empty.")
        for message in messages:
            self.stdout.write("=" * 72)
            self.stdout.write(f"{message['sent_at']}  to: {', '.join(message['to'])}")
            self.stdout.write(f"subject: {message['subject']}")
            self.stdout.write("-" * 72)
            self.stdout.write(message["body"])
