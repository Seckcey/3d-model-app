from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path

from celery import shared_task, signature
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction

from core import audit
from projects import intake, storage
from projects.models import Artifact, ExportControl, PartRevision, SourceFile

from . import health, services
from .models import Job

logger = logging.getLogger("bpcad.jobs")

PREVIEW_TYPES = {".png": "image/png", ".webp": "image/webp"}
MODEL_CONTENT_TYPES = {
    "step": "model/step",
    "glb": "model/gltf-binary",
    "dxf": "image/vnd.dxf",
    "report": "application/json",
    "manifest": "application/json",
}


def _worker_id(task) -> str:
    return f"{task.request.hostname or 'local'}:{task.request.id or 'eager'}"


def _app_versions() -> dict:
    return {"app": settings.APP_VERSION, "git_sha": settings.GIT_SHA}


def _export_control_value(status: str) -> str:
    return {
        "detected": ExportControl.DETECTED,
        "none_found": ExportControl.NONE_FOUND,
    }.get(status, ExportControl.NOT_SCANNED)


@shared_task(name="jobs.run_intake", bind=True)
def run_intake(self, job_id: str) -> None:
    worker = _worker_id(self)
    job = services.claim(job_id, worker)
    if job is None:
        return
    result = None
    published: list[str] = []
    started = time.monotonic()
    try:
        services.heartbeat(job, worker, stage=Job.Stage.EXTRACTING)
        source = SourceFile.objects.select_related("revision").get(pk=job.source_file_id)
        result = intake.run(
            storage.absolute(source.storage_path),
            source.content_type,
            expected_revision=source.revision.drawing_revision,
        )
        with transaction.atomic():
            revision = PartRevision.objects.select_for_update().get(pk=source.revision_id)
            created = []
            for page in result.pages:
                for path, kind in ((page.page_image, Artifact.Kind.PAGE_IMAGE),
                                   (page.thumbnail, Artifact.Kind.THUMBNAIL)):
                    if path is None:
                        continue
                    storage_path = storage.publish_copy(
                        path, job.organization_id, area="artifacts", extension=path.suffix
                    )
                    published.append(storage_path)
                    created.append(Artifact.objects.create(
                        organization_id=job.organization_id,
                        revision=revision,
                        source_file=source,
                        job=job,
                        kind=kind,
                        variant=f"p{page.number}",
                        filename=f"{Path(source.original_name).stem}-p{page.number}{path.suffix}",
                        content_type=PREVIEW_TYPES[path.suffix],
                        size_bytes=path.stat().st_size,
                        sha256=storage.sha256_file(path),
                        storage_path=storage_path,
                        metadata={"page": page.number},
                    ))
            source.intake_report = result.report
            source.intake_status = result.status
            source.save(update_fields=["intake_report", "intake_status", "updated_at"])

            status = result.report["export_control"]["status"]
            blocking = [m for m in result.markings if m["severity"] == "block"]
            if blocking:
                revision.export_control = ExportControl.DETECTED
                revision.export_control_markings = blocking
                revision.external_ai_allowed = False
                revision.save(update_fields=["export_control", "export_control_markings",
                                             "external_ai_allowed", "updated_at"])
                audit.record("revision.export_control_detected", organization=job.organization,
                             target=revision, markings=[m["kind"] for m in blocking])
            elif revision.export_control not in {ExportControl.DETECTED, ExportControl.CONFIRMED,
                                                 ExportControl.CLEARED}:
                # Only a full vector scan of every file may claim "none found".
                others = SourceFile.objects.filter(revision=revision).exclude(pk=source.pk)
                statuses = {status} | {
                    (o.intake_report or {}).get("export_control", {}).get("status", "not_scanned")
                    for o in others
                }
                revision.export_control = (
                    ExportControl.NONE_FOUND if statuses == {"none_found"} else ExportControl.NOT_SCANNED
                )
                revision.save(update_fields=["export_control", "updated_at"])

            services.finish(
                job, worker,
                result={
                    "status": result.status,
                    "pages": len(result.pages),
                    "warnings": len(result.report["warnings"]),
                    "export_control": status,
                    "artifacts": [str(a.pk) for a in created],
                },
                usage={"cpu_seconds": round(time.monotonic() - started, 3), "ai_usd": 0},
                engine_versions={**_app_versions(), "intake": result.report["version"]},
                message=f"Intake complete: {result.status}",
            )
    except services.LeaseLost:
        logger.warning("intake job %s lost its lease; results discarded", job_id)
        for path in published:  # the rows rolled back; do not leave their files behind
            storage.remove(path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("intake job %s failed", job_id)
        for path in published:
            storage.remove(path)
        services.fail_or_retry(
            job, worker, error_code="intake_error",
            message=f"The drawing could not be analysed ({type(exc).__name__}).",
            retryable=True,
        )
    finally:
        if result is not None and result.workdir is not None:
            shutil.rmtree(result.workdir, ignore_errors=True)


@shared_task(name="jobs.start_geometry", bind=True)
def start_geometry(self, job_id: str) -> None:
    """Claim a geometry job and hand the validated spec to the isolated CAD worker.

    The CAD worker has no database access and no outbound network; it writes to
    its staging directory and returns hashes, which finalize_geometry verifies.
    """
    from config.celery import app

    worker = f"orchestrator:{self.request.id or 'eager'}"
    job = services.claim(job_id, worker)
    if job is None:
        return
    services.heartbeat(job, worker, stage=Job.Stage.MODELING)
    callback = signature("jobs.finalize_geometry", args=(str(job.pk), worker), queue="default")
    app.send_task(
        "cad.build_parts",
        args=[str(job.pk), job.params.get("specs", []), job.params.get("options", {})],
        queue="cad",
        link=callback,
        soft_time_limit=job.deadline_seconds,
        time_limit=job.deadline_seconds + 30,
    )


def _verify_staged(job_id: str, entry: dict) -> Path:
    staging = (Path(settings.STAGING_ROOT) / job_id).resolve()
    path = (staging / entry["name"]).resolve()
    if staging not in path.parents:
        raise ValueError("staged file outside job directory")
    if not path.is_file():
        raise ValueError(f"missing staged file {entry['name']}")
    if storage.sha256_file(path) != entry["sha256"]:
        raise ValueError(f"hash mismatch for {entry['name']}")
    return path


@shared_task(name="jobs.finalize_geometry")
def finalize_geometry(result: dict, job_id: str, worker: str) -> None:
    job = Job.objects.select_related("organization").filter(pk=job_id).first()
    staging = Path(settings.STAGING_ROOT) / job_id
    try:
        if job is None or job.state != Job.State.RUNNING or job.lease_owner != worker:
            logger.warning("finalize for job %s ignored (state changed)", job_id)
            return
        if not isinstance(result, dict) or not result.get("ok"):
            error = (result or {}).get("error", {}) if isinstance(result, dict) else {}
            if error.get("code") == "unsupported_feature":
                services.finish(job, worker, state=Job.State.UNSUPPORTED,
                                error_code=error["code"], error_message=error.get("message", ""),
                                message="Unsupported: " + error.get("message", "")[:180])
                return
            services.fail_or_retry(
                job, worker,
                error_code=error.get("code", "cad_error"),
                message=error.get("message", "The geometry worker reported an error."),
                retryable=bool(error.get("retryable", False)),
            )
            return
        services.heartbeat(job, worker, stage=Job.Stage.EXPORTING)
        with transaction.atomic():
            artifacts = []
            for part in result.get("parts", []):
                for entry in part.get("files", []):
                    path = _verify_staged(job_id, entry)
                    storage_path = storage.publish_copy(
                        path, job.organization_id, area="artifacts", extension=path.suffix
                    )
                    artifacts.append(Artifact.objects.create(
                        organization_id=job.organization_id,
                        job=job,
                        kind=entry["kind"],
                        variant=part.get("variant", ""),
                        filename=entry["name"],
                        content_type=MODEL_CONTENT_TYPES.get(entry["kind"], "application/octet-stream"),
                        size_bytes=entry["size"],
                        sha256=entry["sha256"],
                        storage_path=storage_path,
                        is_draft=True,
                        metadata={"part": part.get("part"), "validation": part.get("validation")},
                    ))
            passed = all(p.get("validation", {}).get("passed") for p in result.get("parts", []))
            services.finish(
                job, worker,
                state=Job.State.SUCCEEDED,
                result={
                    "passed": passed,
                    "parts": [
                        {k: p.get(k) for k in ("part", "variant", "validation", "title")}
                        for p in result.get("parts", [])
                    ],
                    "artifacts": [str(a.pk) for a in artifacts],
                },
                usage={"cad_seconds": result.get("elapsed_s"), "ai_usd": 0},
                engine_versions={**_app_versions(), **result.get("engine", {})},
                message="Benchmark passed" if passed else "Benchmark finished with failed checks",
            )
    except services.LeaseLost:
        logger.warning("geometry job %s lost its lease during finalize", job_id)
    except ValueError as exc:
        if job is not None:
            services.fail_or_retry(job, worker, error_code="artifact_verification",
                                   message=str(exc), retryable=False)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


@shared_task(name="jobs.reconcile")
def reconcile() -> dict:
    stats = services.reconcile()
    if any(stats.values()):
        logger.info("reconcile %s", json.dumps(stats))
    return stats


@shared_task(name="jobs.purge_staging")
def purge_staging(max_age_hours: int = 24) -> int:
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for base in (Path(settings.STAGING_ROOT), storage.root() / "tmp"):
        if not base.exists():
            continue
        for entry in base.iterdir():
            try:
                if entry.stat().st_mtime < cutoff:
                    if entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=True)
                    else:
                        entry.unlink(missing_ok=True)
                    removed += 1
            except FileNotFoundError:
                continue
    return removed


@shared_task(name="jobs.check_alerts")
def check_alerts() -> list[str]:
    """Email staff when disk, backlog or backups cross the configured limits."""
    report = health.gather(include_workers=False)
    alerts = health.alerts(report)
    staff = list(
        get_user_model().objects.filter(is_staff=True, is_active=True).values_list("email", flat=True)
    )
    sent = []
    for alert in alerts:
        key = "bpcad:alert:" + hashlib.sha1(alert["code"].encode()).hexdigest()
        if not staff or not cache.add(key, 1, timeout=6 * 3600):
            continue
        send_mail(
            f"[{settings.PRODUCT_NAME}] {alert['title']}",
            f"{alert['message']}\n\nSystem status: {settings.PUBLIC_URL}/system\n",
            settings.DEFAULT_FROM_EMAIL,
            staff,
        )
        sent.append(alert["code"])
    return sent
