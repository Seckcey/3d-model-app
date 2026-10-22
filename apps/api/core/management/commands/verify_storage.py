import json

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from core.models import AuditEvent
from jobs.models import Job
from orgs.models import Membership, Organization
from projects import storage
from projects.models import Artifact, Part, PartRevision, Project, SourceFile


def counts() -> dict:
    return {
        "users": User.objects.count(),
        "organizations": Organization.objects.count(),
        "memberships": Membership.objects.count(),
        "projects": Project.objects.count(),
        "parts": Part.objects.count(),
        "revisions": PartRevision.objects.count(),
        "source_files": SourceFile.objects.count(),
        "artifacts": Artifact.objects.count(),
        "jobs": Job.objects.count(),
        "audit_events": AuditEvent.objects.count(),
    }


class Command(BaseCommand):
    help = ("Check that every stored drawing and artifact exists with the recorded SHA-256. "
            "Prints a JSON summary; exits 1 if anything is missing, altered or below --expect.")

    def add_arguments(self, parser):
        parser.add_argument("--counts-only", action="store_true", help="Skip the file hash checks")
        parser.add_argument("--compact", action="store_true", help="Single-line JSON output")
        parser.add_argument("--expect", help="JSON from an earlier run (or a counts object); every "
                                             "current count must be at least the expected one")

    def handle(self, *args, counts_only=False, compact=False, expect=None, **options):
        summary = {"counts": counts(), "missing": [], "mismatched": [], "below_expected": {}}
        if not counts_only:
            for model in (SourceFile, Artifact):
                for row in model.objects.only("id", "storage_path", "sha256").iterator():
                    path = storage.absolute(row.storage_path)
                    if not path.exists():
                        summary["missing"].append(f"{model.__name__}:{row.pk}")
                    elif storage.sha256_file(path) != row.sha256:
                        summary["mismatched"].append(f"{model.__name__}:{row.pk}")
        if expect:
            try:
                expected = json.loads(expect)
            except ValueError as exc:
                raise CommandError("--expect is not valid JSON") from exc
            expected = expected.get("counts", expected)
            for key, value in expected.items():
                actual = summary["counts"].get(key)
                if actual is None or actual < int(value):
                    summary["below_expected"][key] = {"expected": value, "actual": actual}
        summary["ok"] = not (summary["missing"] or summary["mismatched"] or summary["below_expected"])
        self.stdout.write(json.dumps(summary, separators=(",", ":")) if compact
                          else json.dumps(summary, indent=2))
        if not summary["ok"]:
            raise SystemExit(1)
