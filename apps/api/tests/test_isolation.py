"""Phase 1 exit gate: two shops cannot access each other's files or jobs.

Shop A creates a full chain (customer, project, part, revision, drawing,
intake job, preview artifacts). Shop B then tries every read and write path
with Shop A's IDs and must get nothing back.
"""

from django.core.files.uploadedfile import SimpleUploadedFile

from jobs.models import Job
from jobs.tasks import run_intake
from projects.models import Artifact
from tests.drawings import PLATE_DRAWING, make_pdf


def build_shop_a_chain(shop_a):
    client, org = shop_a["client"], shop_a["org"]
    customer = client.post("/api/v1/customers/", {"organization": str(org.pk), "name": "Acme Aero"},
                           format="json").json()
    project = client.post("/api/v1/projects/", {
        "organization": str(org.pk), "name": "PO 4471 brackets", "customer": customer["id"],
        "reference": "PO-4471"}, format="json").json()
    part = client.post("/api/v1/parts/", {"project": project["id"], "part_number": "BP-1001"},
                       format="json").json()
    revision = client.post(f"/api/v1/parts/{part['id']}/revisions/", {"drawing_revision": "C"},
                           format="json").json()
    upload = SimpleUploadedFile("BP-1001_C.pdf", make_pdf([PLATE_DRAWING]), "application/pdf")
    source = client.post(f"/api/v1/revisions/{revision['id']}/files/", {"file": upload},
                         format="multipart").json()
    job = Job.objects.get(source_file_id=source["id"])
    run_intake.apply(args=[str(job.pk)])
    artifact = Artifact.objects.filter(source_file_id=source["id"]).first()
    return {"customer": customer, "project": project, "part": part, "revision": revision,
            "source": source, "job": job, "artifact": artifact}


def test_shops_cannot_read_each_others_records(shop_a, shop_b):
    chain = build_shop_a_chain(shop_a)
    assert chain["artifact"] is not None
    b = shop_b["client"]
    org_a = shop_a["org"].pk

    # Lists come back empty, even when filtered by Shop A's organisation.
    for url in ("/api/v1/projects/", "/api/v1/parts/", "/api/v1/jobs/"):
        assert b.get(url).json()["count"] == 0
        assert b.get(f"{url}?organization={org_a}").json()["count"] == 0
    assert b.get("/api/v1/customers/").json() == []
    assert b.get(f"/api/v1/artifacts/?organization={org_a}").json() == []
    assert b.get("/api/v1/search/?q=BP-1001").json()["parts"] == []

    # Direct object access by ID is a 404, never a 403 that confirms existence.
    for url in (
        f"/api/v1/organizations/{org_a}/",
        f"/api/v1/customers/{chain['customer']['id']}/",
        f"/api/v1/projects/{chain['project']['id']}/",
        f"/api/v1/parts/{chain['part']['id']}/",
        f"/api/v1/parts/{chain['part']['id']}/revisions/",
        f"/api/v1/revisions/{chain['revision']['id']}/",
        f"/api/v1/revisions/{chain['revision']['id']}/files/",
        f"/api/v1/files/{chain['source']['id']}/",
        f"/api/v1/files/{chain['source']['id']}/download/",
        f"/api/v1/artifacts/{chain['artifact'].pk}/download/",
        f"/api/v1/artifacts/{chain['artifact'].pk}/download/?inline=1",
        f"/api/v1/jobs/{chain['job'].pk}/",
        f"/api/v1/organizations/{org_a}/members/",
        f"/api/v1/organizations/{org_a}/invitations/",
        f"/api/v1/organizations/{org_a}/audit/",
        f"/api/v1/organizations/{org_a}/benchmark/",
    ):
        assert b.get(url).status_code == 404, url


def test_shops_cannot_write_into_each_other(shop_a, shop_b):
    chain = build_shop_a_chain(shop_a)
    b = shop_b["client"]
    org_a = shop_a["org"].pk

    assert b.post("/api/v1/projects/", {"organization": str(org_a), "name": "Sneaky"},
                  format="json").status_code == 400
    assert b.post("/api/v1/customers/", {"organization": str(org_a), "name": "Sneaky"},
                  format="json").status_code == 400
    assert b.post("/api/v1/parts/", {"project": chain["project"]["id"], "part_number": "X-1"},
                  format="json").status_code == 400
    assert b.post(f"/api/v1/parts/{chain['part']['id']}/revisions/", {},
                  format="json").status_code == 404
    upload = SimpleUploadedFile("evil.pdf", make_pdf([["X"]]), "application/pdf")
    assert b.post(f"/api/v1/revisions/{chain['revision']['id']}/files/", {"file": upload},
                  format="multipart").status_code == 404
    assert b.post(f"/api/v1/jobs/{chain['job'].pk}/cancel/").status_code == 404
    assert b.post(f"/api/v1/revisions/{chain['revision']['id']}/jobs/",
                  {"target": "intake_check", "source_file": chain["source"]["id"]},
                  format="json").status_code == 404
    assert b.patch(f"/api/v1/projects/{chain['project']['id']}/", {"name": "Renamed"},
                   format="json").status_code == 404
    assert b.delete(f"/api/v1/projects/{chain['project']['id']}/").status_code == 404
    assert b.patch(f"/api/v1/organizations/{org_a}/", {"name": "Owned"},
                   format="json").status_code == 404
    assert b.post(f"/api/v1/organizations/{org_a}/invitations/",
                  {"email": "spy@shop-b.test", "roles": ["owner"]}, format="json").status_code == 404
    assert b.post(f"/api/v1/organizations/{org_a}/benchmark/").status_code == 404

    # A's data is untouched.
    a = shop_a["client"]
    assert a.get(f"/api/v1/projects/{chain['project']['id']}/").json()["name"] == "PO 4471 brackets"


def test_project_in_own_shop_cannot_reference_foreign_customer(shop_a, shop_b):
    chain = build_shop_a_chain(shop_a)
    response = shop_b["client"].post("/api/v1/projects/", {
        "organization": str(shop_b["org"].pk), "name": "Mine",
        "customer": chain["customer"]["id"]}, format="json")
    assert response.status_code == 400


def test_malformed_ids_in_filters_match_nothing(shop_a):
    client = shop_a["client"]
    assert client.get("/api/v1/jobs/?revision=not-a-uuid").json()["count"] == 0
    assert client.get("/api/v1/projects/?organization=../../etc").json()["count"] == 0
    assert client.get("/api/v1/parts/?project=1%20OR%201=1").json()["count"] == 0
    assert client.get("/api/v1/artifacts/?job=abc").json() == []
    assert client.get("/api/v1/jobs/not-a-uuid/").status_code == 404


def test_anonymous_requests_are_rejected(shop_a):
    from rest_framework.test import APIClient

    chain = build_shop_a_chain(shop_a)
    anon = APIClient()
    for url in ("/api/v1/projects/", f"/api/v1/files/{chain['source']['id']}/download/",
                f"/api/v1/jobs/{chain['job'].pk}/", "/api/v1/me/"):
        assert anon.get(url).status_code == 403, url
