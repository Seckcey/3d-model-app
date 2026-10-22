import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Wait until the database accepts connections."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=90)

    def handle(self, *args, timeout=90, **options):
        deadline = time.monotonic() + timeout
        while True:
            try:
                connection.ensure_connection()
                self.stdout.write("database is ready")
                return
            except OperationalError as exc:
                if time.monotonic() > deadline:
                    raise CommandError(f"database not reachable after {timeout}s") from exc
                time.sleep(2)
