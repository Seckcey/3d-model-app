import json

import pytest
from django.core.management import call_command
from django.test import Client

from core.models import AuditEvent, BackupRecord
from tests.helpers import add_member, client_for, make_user


def test_health_endpoints(db):
    client = Client()
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["database"] is True
    assert client.get("/api/v1/version/").json()["product"] == "Blueprint to CAD"
    response = client.get("/api/v1/csrf/")
    assert "bpcad_csrftoken" in response.cookies


def test_system_health_is_staff_only(shop_a, monkeypatch):
    monkeypatch.setattr("jobs.health._workers", lambda: {"ok": False, "workers": [],
                                                         "missing_queues": ["cad"]})
    assert shop_a["client"].get("/api/v1/system/health/").status_code == 403
    admin = make_user("admin@platform.test", staff=True)
    report = client_for(admin).get("/api/v1/system/health/").json()
    assert report["database"]["ok"] is True
    assert report["email"]["delivery"] in ("outbox", "smtp")
    assert {a["code"] for a in report["alerts"]} >= {"backup"}


def test_backup_records_clear_the_backup_alert(shop_a, monkeypatch):
    monkeypatch.setattr("jobs.health._workers", lambda: {"ok": True, "workers": []})
    call_command("record_backup", kind="backup", status="succeeded", location="/backups/x.gpg",
                 size=1234, sha256="ab" * 32, details=json.dumps({"files": 3}))
    admin = make_user("admin@platform.test", staff=True)
    report = client_for(admin).get("/api/v1/system/health/").json()
    assert report["backups"]["ok"] is True
    assert BackupRecord.objects.count() == 1


def test_verify_storage_detects_tampering(shop_a, capsys):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from projects import storage
    from projects.models import SourceFile
    from tests.drawings import PLATE_DRAWING, make_pdf

    client, org = shop_a["client"], shop_a["org"]
    project = client.post("/api/v1/projects/", {"organization": str(org.pk), "name": "Storage"},
                          format="json").json()
    part = client.post("/api/v1/parts/", {"project": project["id"], "part_number": "X"},
                       format="json").json()
    revision = client.post(f"/api/v1/parts/{part['id']}/revisions/", {}, format="json").json()
    client.post(f"/api/v1/revisions/{revision['id']}/files/",
                {"file": SimpleUploadedFile("a.pdf", make_pdf([PLATE_DRAWING]), "application/pdf")},
                format="multipart")
    call_command("verify_storage")
    assert json.loads(capsys.readouterr().out)["ok"] is True

    call_command("verify_storage", counts_only=True, compact=True)
    recorded = capsys.readouterr().out.strip()
    assert "\n" not in recorded and json.loads(recorded)["counts"]["source_files"] == 1
    call_command("verify_storage", expect=recorded)  # a restore with the same data passes
    capsys.readouterr()
    with pytest.raises(SystemExit):  # fewer rows than the backup recorded fails
        call_command("verify_storage", expect=json.dumps({"source_files": 2}))
    assert json.loads(capsys.readouterr().out)["below_expected"]["source_files"]["actual"] == 1

    path = storage.absolute(SourceFile.objects.get().storage_path)
    path.chmod(0o640)
    path.write_bytes(b"tampered")
    with pytest.raises(SystemExit):
        call_command("verify_storage")
    assert json.loads(capsys.readouterr().out)["mismatched"]


def test_bootstrap_is_idempotent(db, capsys):
    call_command("bootstrap", email="Frankie@8westit.com", org="Ralls Precision", name="Frankie")
    call_command("bootstrap", email="frankie@8westit.com", org="Ralls Precision")
    from accounts.models import User
    from orgs.models import Membership, Organization

    user = User.objects.get(email="frankie@8westit.com")
    assert user.is_staff and user.is_superuser
    assert Organization.objects.count() == 1
    assert "owner" in Membership.objects.get(user=user).roles


def test_owner_audit_log_and_csv(shop_a):
    org = shop_a["org"]
    shop_a["client"].post("/api/v1/projects/", {"organization": str(org.pk), "name": "Audit me"},
                          format="json")
    events = shop_a["client"].get(f"/api/v1/organizations/{org.pk}/audit/").json()
    assert events[0]["action"] == "project.created"
    csv_response = shop_a["client"].get(f"/api/v1/organizations/{org.pk}/audit/?export=csv")
    assert csv_response["Content-Type"] == "text/csv"
    assert b"project.created" in csv_response.content
    engineer = make_user("eng@shop-a.test")
    add_member(org, engineer, ["engineer"])
    assert client_for(engineer).get(f"/api/v1/organizations/{org.pk}/audit/").status_code == 403
    assert AuditEvent.objects.filter(organization=org).count() >= 1


def test_preferences_validation(shop_a):
    url = f"/api/v1/organizations/{shop_a['org'].pk}/"
    client = shop_a["client"]
    ok = client.patch(url, {"preferences": {"tapped_hole_model": "tap_drill_with_major_step",
                                            "model_tolerance": "mid_tolerance",
                                            "filename_pattern": "{customer}_{part}_R{rev}_{kind}"}},
                      format="json")
    assert ok.status_code == 200, ok.content
    prefs = ok.json()["preferences"]
    assert prefs["tapped_hole_model"] == "tap_drill_with_major_step"
    assert prefs["step_units"] == "drawing"  # default: no silent unit conversion
    for bad in ({"tapped_hole_model": "guess"}, {"filename_pattern": "{part}_{evil}/x"},
                {"stock_allowance_in": 9}, {"unknown": 1}):
        assert client.patch(url, {"preferences": bad}, format="json").status_code == 400, bad


def test_external_ai_requires_workspace_policy(shop_a):
    response = shop_a["client"].post("/api/v1/projects/", {
        "organization": str(shop_a["org"].pk), "name": "AI please", "external_ai_allowed": True,
    }, format="json")
    assert response.status_code == 400


def test_admin_user_controls(shop_a):
    admin = make_user("admin@platform.test", staff=True)
    target = make_user("leaver@shop-a.test")
    add_member(shop_a["org"], target, ["engineer"])
    target_client = client_for(target)
    assert target_client.get("/api/v1/me/").status_code == 200
    assert shop_a["client"].post(f"/api/v1/admin/users/{target.pk}/deactivate/").status_code == 403
    response = client_for(admin).post(f"/api/v1/admin/users/{target.pk}/deactivate/")
    assert response.status_code == 200 and response.json()["is_active"] is False
    assert target_client.get("/api/v1/me/").status_code == 403
