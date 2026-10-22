"""The API side of the CAD hand-off: staged files are verified by hash and
published atomically; anything suspicious fails the job."""

import hashlib
from pathlib import Path

import pytest
from django.conf import settings

from jobs import services
from jobs.models import Job
from jobs.tasks import finalize_geometry
from projects import storage
from projects.models import Artifact


@pytest.fixture
def running_job(shop_a):
    job, _ = services.create_job(organization=shop_a["org"], kind=Job.Kind.GEOMETRY_BENCHMARK,
                                 idempotency_key="bench")
    worker = "orchestrator:test"
    return services.claim(job.pk, worker), worker


def stage(job, name: str, data: bytes) -> dict:
    directory = Path(settings.STAGING_ROOT) / str(job.pk)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(data)
    return {"name": name, "kind": "step", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def result_with(files, passed=True):
    return {"ok": True, "engine": {"cadquery": "test"}, "elapsed_s": 0.5, "parts": [{
        "part": "BENCH-PLATE-01", "title": "Fixture plate", "variant": "nominal",
        "validation": {"passed": passed, "summary": {}, "checks": []}, "files": files,
    }]}


def test_verified_files_are_published(running_job):
    job, worker = running_job
    entry = stage(job, "BENCH-PLATE-01_REVA_NOMINAL-IN.step", b"ISO-10303-21; test")
    finalize_geometry(result_with([entry]), str(job.pk), worker)
    job.refresh_from_db()
    assert job.state == Job.State.SUCCEEDED and job.result["passed"] is True
    artifact = Artifact.objects.get(job=job)
    assert artifact.filename == entry["name"] and artifact.is_draft
    assert storage.absolute(artifact.storage_path).read_bytes() == b"ISO-10303-21; test"
    assert not (Path(settings.STAGING_ROOT) / str(job.pk)).exists()


def test_hash_mismatch_fails_the_job(running_job):
    job, worker = running_job
    entry = stage(job, "part.step", b"real")
    entry["sha256"] = "0" * 64
    finalize_geometry(result_with([entry]), str(job.pk), worker)
    job.refresh_from_db()
    assert job.state == Job.State.FAILED and job.error_code == "artifact_verification"
    assert not Artifact.objects.filter(job=job).exists()


def test_path_traversal_is_refused(running_job):
    job, worker = running_job
    outside = Path(settings.STAGING_ROOT).parent / "secret.txt"
    outside.write_bytes(b"secret")
    entry = {"name": "../secret.txt", "kind": "step",
             "sha256": hashlib.sha256(b"secret").hexdigest(), "size": 6}
    finalize_geometry(result_with([entry]), str(job.pk), worker)
    job.refresh_from_db()
    assert job.state == Job.State.FAILED
    assert not Artifact.objects.filter(job=job).exists()


def test_stale_worker_result_is_ignored(running_job):
    job, _ = running_job
    entry = stage(job, "part.step", b"x")
    finalize_geometry(result_with([entry]), str(job.pk), "orchestrator:someone-else")
    job.refresh_from_db()
    assert job.state == Job.State.RUNNING
    assert not Artifact.objects.filter(job=job).exists()


def test_unsupported_feature_sets_unsupported_state(running_job):
    job, worker = running_job
    finalize_geometry({"ok": False, "error": {"code": "unsupported_feature",
                                              "message": "H2: countersinks arrive in Phase 3"}},
                      str(job.pk), worker)
    job.refresh_from_db()
    assert job.state == Job.State.UNSUPPORTED and "countersinks" in job.error_message


def test_engine_crash_is_retried(running_job, _no_dispatch):
    job, worker = running_job
    finalize_geometry({"ok": False, "error": {"code": "cad_crash", "message": "boom",
                                              "retryable": True}}, str(job.pk), worker)
    job.refresh_from_db()
    assert job.state == Job.State.QUEUED and job.attempts == 1
