import hashlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import AuditEvent
from jobs.models import Job
from projects import storage
from projects.models import SourceFile
from tests.drawings import PLATE_DRAWING, make_pdf, make_png
from tests.helpers import add_member, client_for, make_user


@pytest.fixture
def revision(shop_a):
    client, org = shop_a["client"], shop_a["org"]
    project = client.post("/api/v1/projects/", {"organization": str(org.pk), "name": "Job 1"},
                          format="json").json()
    part = client.post("/api/v1/parts/", {"project": project["id"], "part_number": "BP-1"},
                       format="json").json()
    return client.post(f"/api/v1/parts/{part['id']}/revisions/", {"drawing_revision": "a"},
                       format="json").json()


def upload(client, revision, name, data, content_type="application/pdf"):
    return client.post(f"/api/v1/revisions/{revision['id']}/files/",
                       {"file": SimpleUploadedFile(name, data, content_type)}, format="multipart")


def test_pdf_upload_is_stored_immutably_and_queues_intake(shop_a, revision):
    pdf = make_pdf([PLATE_DRAWING, ["SHEET 2"]])
    response = upload(shop_a["client"], revision, "../../etc/passwd.pdf", pdf)
    assert response.status_code == 201, response.content
    data = response.json()
    assert data["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert data["page_count"] == 2
    assert data["original_name"] == "passwd.pdf"
    source = SourceFile.objects.get(pk=data["id"])
    path = storage.absolute(source.storage_path)
    assert path.read_bytes() == pdf
    assert oct(path.stat().st_mode & 0o777) == "0o440"
    assert ".." not in source.storage_path and source.storage_path.startswith(f"orgs/{shop_a['org'].pk}/")
    job = Job.objects.get(source_file=source)
    assert job.kind == Job.Kind.INTAKE_CHECK and job.state == Job.State.QUEUED
    assert AuditEvent.objects.filter(action="file.uploaded", target_id=str(source.pk)).exists()
    assert revision["drawing_revision"] == "A"


def test_duplicate_upload_returns_existing_file(shop_a, revision):
    pdf = make_pdf([PLATE_DRAWING])
    first = upload(shop_a["client"], revision, "a.pdf", pdf).json()
    second = upload(shop_a["client"], revision, "a-copy.pdf", pdf)
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert Job.objects.filter(kind=Job.Kind.INTAKE_CHECK).count() == 1


@pytest.mark.parametrize("name,data,ctype,code", [
    ("notes.pdf", b"this is not a pdf", "application/pdf", "unsupported_type"),
    ("drawing.dwg", b"AC1032" + b"\x00" * 100, "application/octet-stream", "unsupported_type"),
    ("broken.pdf", b"%PDF-1.4\n garbage", "application/pdf", "corrupt_pdf"),
    ("broken.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png", "corrupt_image"),
])
def test_rejects_bad_files_by_content(shop_a, revision, name, data, ctype, code):
    response = upload(shop_a["client"], revision, name, data, ctype)
    assert response.status_code == 400
    assert response.json()["code"] == [code] or response.json()["code"] == code
    assert SourceFile.objects.count() == 0
    assert list((storage.root() / "tmp").iterdir()) == []


def test_page_limit(shop_a, revision):
    org = shop_a["org"]
    org.max_pdf_pages = 2
    org.save()
    response = upload(shop_a["client"], revision, "big.pdf", make_pdf([["p"]] * 3))
    assert response.status_code == 400
    assert "3 pages" in str(response.json()["file"])


def test_size_limit(shop_a, revision):
    org = shop_a["org"]
    org.max_upload_mb = 1
    org.save()
    big = make_pdf([PLATE_DRAWING]) + b"%" + b"0" * (1024 * 1024 + 10)
    response = upload(shop_a["client"], revision, "huge.pdf", big)
    assert response.status_code == 400
    assert "1 MB" in str(response.json()["file"])
    assert list((storage.root() / "tmp").iterdir()) == []


def test_png_upload(shop_a, revision):
    response = upload(shop_a["client"], revision, "scan.png", make_png(), "image/png")
    assert response.status_code == 201
    assert response.json()["content_type"] == "image/png"


def test_roles_for_upload_and_download(shop_a, revision):
    pdf = make_pdf([PLATE_DRAWING])
    source = upload(shop_a["client"], revision, "a.pdf", pdf).json()
    viewer = make_user("viewer@shop-a.test")
    add_member(shop_a["org"], viewer, ["viewer"])
    reviewer = make_user("reviewer@shop-a.test")
    add_member(shop_a["org"], reviewer, ["reviewer"])

    viewer_client = client_for(viewer)
    assert upload(viewer_client, revision, "b.pdf", make_pdf([["B"]])).status_code == 403
    assert viewer_client.get(f"/api/v1/files/{source['id']}/").status_code == 200
    assert viewer_client.get(f"/api/v1/files/{source['id']}/download/").status_code == 403

    reviewer_client = client_for(reviewer)
    assert upload(reviewer_client, revision, "c.pdf", make_pdf([["C"]])).status_code == 403
    response = reviewer_client.get(f"/api/v1/files/{source['id']}/download/")
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == pdf
    assert response["Content-Disposition"].startswith("attachment")
    assert AuditEvent.objects.filter(action="file.downloaded", actor=reviewer).exists()


def test_x_accel_redirect_mode(shop_a, revision, settings):
    settings.USE_X_ACCEL_REDIRECT = True
    source = upload(shop_a["client"], revision, "a.pdf", make_pdf([PLATE_DRAWING])).json()
    response = shop_a["client"].get(f"/api/v1/files/{source['id']}/download/")
    assert response.status_code == 200
    assert response["X-Accel-Redirect"].startswith("/_protected/orgs/")


def test_page_selection(shop_a, revision):
    source = upload(shop_a["client"], revision, "a.pdf", make_pdf([["1"], ["2"], ["3"]])).json()
    url = f"/api/v1/files/{source['id']}/"
    assert shop_a["client"].patch(url, {"selected_pages": [1, 3]}, format="json").json()[
        "selected_pages"] == [1, 3]
    assert shop_a["client"].patch(url, {"selected_pages": [4]}, format="json").status_code == 400


def test_project_delete_removes_files(shop_a, revision, django_capture_on_commit_callbacks):
    source = upload(shop_a["client"], revision, "a.pdf", make_pdf([PLATE_DRAWING])).json()
    path = storage.absolute(SourceFile.objects.get(pk=source["id"]).storage_path)
    project_id = SourceFile.objects.get(pk=source["id"]).revision.part.project_id
    assert path.exists()
    with django_capture_on_commit_callbacks(execute=True):
        response = shop_a["client"].delete(f"/api/v1/projects/{project_id}/")
    assert response.status_code == 204
    assert not SourceFile.objects.filter(pk=source["id"]).exists()
    assert AuditEvent.objects.filter(action="project.deleted").exists()
    assert not path.exists()


def test_only_owner_deletes_projects(shop_a, revision):
    from projects.models import Part

    engineer = make_user("eng@shop-a.test")
    add_member(shop_a["org"], engineer, ["engineer"])
    project_id = Part.objects.get(pk=revision["part"]).project_id
    assert client_for(engineer).delete(f"/api/v1/projects/{project_id}/").status_code == 403
