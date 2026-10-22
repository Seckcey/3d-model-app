"""Drawing intake check: previews, markings, hints and warnings."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from jobs.models import Job
from jobs.tasks import run_intake
from projects import intake
from projects.models import Artifact, ExportControl, PartRevision, SourceFile
from tests.drawings import ITAR_DRAWING, PLATE_DRAWING, make_pdf, make_png


@pytest.fixture
def make_revision(shop_a):
    def _make(drawing_revision="C", external_ai=False):
        client, org = shop_a["client"], shop_a["org"]
        if external_ai:
            org.allow_external_ai = True
            org.save()
        project = client.post("/api/v1/projects/", {
            "organization": str(org.pk), "name": "Intake", "external_ai_allowed": external_ai,
        }, format="json").json()
        part = client.post("/api/v1/parts/", {"project": project["id"], "part_number": "BP-1001"},
                           format="json").json()
        return client.post(f"/api/v1/parts/{part['id']}/revisions/",
                           {"drawing_revision": drawing_revision}, format="json").json()
    return _make


def upload_and_run(client, revision, data, name="d.pdf", ctype="application/pdf"):
    source = client.post(f"/api/v1/revisions/{revision['id']}/files/",
                         {"file": SimpleUploadedFile(name, data, ctype)}, format="multipart").json()
    job = Job.objects.get(source_file_id=source["id"])
    run_intake.apply(args=[str(job.pk)])
    job.refresh_from_db()
    return SourceFile.objects.get(pk=source["id"]), job


def test_vector_pdf_intake(shop_a, make_revision):
    revision = make_revision("C")
    sheet2 = ["SHEET 2 OF 2", "SECTION A-A", "DETAIL B  SCALE 2:1", "NOTES CONTINUED FROM SHEET 1"]
    source, job = upload_and_run(shop_a["client"], revision, make_pdf([PLATE_DRAWING, sheet2]))
    assert job.state == Job.State.SUCCEEDED, job.error_message
    report = source.intake_report
    assert report["page_count"] == 2
    assert all(p["has_vector_text"] for p in report["pages"])
    hints = report["hints"]
    assert hints["units"] == "in"
    assert hints["projection"] == "third_angle"
    assert "C" in hints["revision_candidates"]
    assert hints["material_candidates"][0].startswith("6061-T6")
    assert "anodize" in hints["outside_processes"]
    assert "1/4-20 UNC-2B" in hints["thread_callouts"]
    assert "M6x1.0 - 6H" in hints["thread_callouts"]
    assert hints["general_tolerance_block"] is True
    assert report["export_control"]["status"] == "none_found"
    kinds = sorted(Artifact.objects.filter(source_file=source).values_list("kind", "variant"))
    assert kinds == [("page_image", "p1"), ("page_image", "p2"), ("thumbnail", "p1"),
                     ("thumbnail", "p2")]
    revision_row = PartRevision.objects.get(pk=revision["id"])
    assert revision_row.export_control == ExportControl.NONE_FOUND
    # "no marking found" is not clearance: external AI stays off until a person clears it
    assert revision_row.effective_external_ai is False
    thumb = Artifact.objects.filter(source_file=source, kind="thumbnail").first()
    response = shop_a["client"].get(f"/api/v1/artifacts/{thumb.pk}/download/?inline=1")
    assert response.status_code == 200 and response["Content-Type"] == "image/webp"


def test_export_control_marking_locks_external_ai(shop_a, make_revision):
    revision = make_revision("C", external_ai=True)
    source, job = upload_and_run(shop_a["client"], revision, make_pdf([ITAR_DRAWING]))
    assert job.state == Job.State.SUCCEEDED
    markings = source.intake_report["export_control"]["markings"]
    kinds = [m["kind"] for m in markings]
    assert {"ITAR", "EXPORT WARNING", "DISTRIBUTION STATEMENT"} <= set(kinds)
    assert len(kinds) == len(set(kinds))  # one entry per kind per page
    itar = next(m for m in markings if m["kind"] == "ITAR")
    text = " ".join(" ".join(ITAR_DRAWING).split())
    at = text.find(itar["text"])
    assert at >= 0 and (at == 0 or text[at - 1] == " ")  # snippet starts on a whole word
    row = PartRevision.objects.get(pk=revision["id"])
    assert row.export_control == ExportControl.DETECTED
    assert row.external_ai_allowed is False and row.effective_external_ai is False

    # Engineers cannot clear it; owners can confirm or clear with a reason.
    url = f"/api/v1/revisions/{revision['id']}/export-control/"
    assert shop_a["client"].post(url, {"decision": "cleared"}, format="json").status_code == 400
    response = shop_a["client"].post(url, {"decision": "confirmed", "reason": "ITAR cat VIII per PO"},
                                     format="json")
    assert response.status_code == 200 and response.json()["export_control"] == "confirmed"


def test_owner_clearance_enables_external_ai(shop_a, make_revision):
    revision = make_revision("C", external_ai=True)
    upload_and_run(shop_a["client"], revision, make_pdf([PLATE_DRAWING]))
    url = f"/api/v1/revisions/{revision['id']}/export-control/"
    response = shop_a["client"].post(url, {"decision": "cleared", "reason": "Commercial part, EAR99"},
                                     format="json")
    assert response.status_code == 200
    assert response.json()["effective_external_ai"] is True


def test_revision_mismatch_warning(shop_a, make_revision):
    revision = make_revision("B")
    source, _ = upload_and_run(shop_a["client"], revision, make_pdf([PLATE_DRAWING]))
    codes = {w["code"] for w in source.intake_report["warnings"]}
    assert "revision_mismatch" in codes
    assert source.intake_status == "warning"


def test_raster_image_intake(shop_a, make_revision):
    revision = make_revision("C")
    source, job = upload_and_run(shop_a["client"], revision, make_png(1200, 800), "scan.png",
                                 "image/png")
    assert job.state == Job.State.SUCCEEDED
    codes = {w["code"] for w in source.intake_report["warnings"]}
    assert {"low_resolution", "raster_page"} <= codes
    assert source.intake_report["export_control"]["status"] == "not_scanned"
    assert PartRevision.objects.get(pk=revision["id"]).export_control == ExportControl.NOT_SCANNED


def test_sharpness_detects_blur():
    from io import BytesIO

    from PIL import Image

    sharp = intake.sharpness_score(Image.open(BytesIO(make_png())))
    blurry = intake.sharpness_score(Image.open(BytesIO(make_png(blurry=True))))
    assert sharp > intake.BLUR_WARNING_SCORE > blurry


def test_marking_patterns():
    text = "CUI\nControlled by: DoD\nDISTRIBUTION STATEMENT C. Distribution authorized to U.S. Government agencies"
    kinds = {m["kind"] for m in intake.scan_markings(text, 1)}
    assert {"CUI", "DISTRIBUTION STATEMENT"} <= kinds
    assert intake.scan_markings("DISTRIBUTION STATEMENT A. Approved for public release", 1)[0][
        "severity"] == "info"
    assert intake.scan_markings("Plain commercial bracket, 6061-T6", 1) == []
    revisions = intake.drawing_hints("REVISIONS\nREV  DESCRIPTION  BY\nREV D")["revision_candidates"]
    assert revisions == ["D"]


def test_failed_intake_is_retried_then_reported(shop_a, make_revision, monkeypatch):
    revision = make_revision("C")
    source = shop_a["client"].post(
        f"/api/v1/revisions/{revision['id']}/files/",
        {"file": SimpleUploadedFile("d.pdf", make_pdf([PLATE_DRAWING]), "application/pdf")},
        format="multipart").json()
    job = Job.objects.get(source_file_id=source["id"])
    job.max_attempts = 1
    job.save()

    def explode(*args, **kwargs):
        raise RuntimeError("renderer crashed")

    monkeypatch.setattr("projects.intake.run", explode)
    run_intake.apply(args=[str(job.pk)])
    job.refresh_from_db()
    assert job.state == Job.State.FAILED
    assert job.error_code == "intake_error"
    assert "RuntimeError" in job.error_message
