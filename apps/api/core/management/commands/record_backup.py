import json

from django.core.management.base import BaseCommand

from core.models import BackupRecord


class Command(BaseCommand):
    help = "Record the outcome of a host backup or restore drill (called by infra/scripts)."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=[k.value for k in BackupRecord.Kind], required=True)
        parser.add_argument("--status", choices=[s.value for s in BackupRecord.Status], required=True)
        parser.add_argument("--location", default="")
        parser.add_argument("--size", type=int)
        parser.add_argument("--sha256", default="")
        parser.add_argument("--details", default="{}", help="JSON object")

    def handle(self, *args, kind, status, location, size, sha256, details, **options):
        try:
            data = json.loads(details) if details else {}
        except ValueError:
            data = {"raw": details[:2000]}
        record = BackupRecord.objects.create(kind=kind, status=status, location=location[:500],
                                             size_bytes=size, sha256=sha256[:64], details=data)
        self.stdout.write(f"recorded {record.kind} {record.status} #{record.pk}")
