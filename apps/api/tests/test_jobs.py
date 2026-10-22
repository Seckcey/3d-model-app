"""Durable job records: idempotency, atomic claims, fenced completion,
reconciliation of abandoned work and cancellation."""

from datetime import timedelta

import pytest
from django.utils import timezone

from jobs import services
from jobs.models import Job
from tests.helpers import add_member, client_for, make_user


@pytest.fixture
def org(shop_a):
    return shop_a["org"]


def new_job(org, key="k1", kind=Job.Kind.INTAKE_CHECK, **kwargs):
    job, _ = services.create_job(organization=org, kind=kind, idempotency_key=key, **kwargs)
    return job


def test_same_idempotency_key_returns_same_job(org, _no_dispatch):
    first, created1 = services.create_job(organization=org, kind=Job.Kind.INTAKE_CHECK,
                                          idempotency_key="upload-1")
    second, created2 = services.create_job(organization=org, kind=Job.Kind.INTAKE_CHECK,
                                           idempotency_key="upload-1")
    assert created1 and not created2
    assert first.pk == second.pk
    assert Job.objects.count() == 1


def test_only_one_worker_wins_the_claim(org):
    job = new_job(org)
    assert services.claim(job.pk, "worker-1") is not None
    assert services.claim(job.pk, "worker-2") is None
    job.refresh_from_db()
    assert job.state == Job.State.RUNNING and job.attempts == 1 and job.lease_owner == "worker-1"


def test_completion_is_fenced_by_lease_owner(org):
    job = services.claim(new_job(org).pk, "worker-1")
    with pytest.raises(services.LeaseLost):
        services.finish(job, "worker-2", result={"x": 1})
    services.finish(job, "worker-1", result={"ok": True})
    job.refresh_from_db()
    assert job.state == Job.State.SUCCEEDED and job.result == {"ok": True}
    assert job.lease_owner == "" and job.finished_at is not None
    assert [e.message for e in job.events.all()][0] == "Queued"


def test_reconcile_requeues_then_fails_expired_leases(org, _no_dispatch):
    job = new_job(org)
    job.max_attempts = 2
    job.save()
    for attempt in (1, 2):
        claimed = services.claim(job.pk, f"worker-{attempt}")
        assert claimed is not None
        Job.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        services.reconcile()
        job.refresh_from_db()
    assert job.state == Job.State.FAILED
    assert job.error_code == "lease_expired"
    assert job.attempts == 2


def test_reconcile_redispatches_stale_queued_jobs(org, _no_dispatch):
    job = new_job(org)
    Job.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=11))
    _no_dispatch.clear()
    stats = services.reconcile()
    assert stats["redispatched"] == 1
    assert _no_dispatch == [str(job.pk)]


def test_retry_then_fail(org, _no_dispatch):
    job = new_job(org)
    job.max_attempts = 2
    job.save()
    claimed = services.claim(job.pk, "w")
    services.fail_or_retry(claimed, "w", error_code="boom", message="temporary", retryable=True)
    job.refresh_from_db()
    assert job.state == Job.State.QUEUED
    claimed = services.claim(job.pk, "w2")
    services.fail_or_retry(claimed, "w2", error_code="boom", message="again", retryable=True)
    job.refresh_from_db()
    assert job.state == Job.State.FAILED and job.error_message == "again"


def test_cancel_queued_and_running(org):
    queued = new_job(org, key="a")
    assert services.cancel(queued).state == Job.State.CANCELED
    assert services.claim(queued.pk, "w") is None

    running = services.claim(new_job(org, key="b").pk, "w")
    canceled = services.cancel(running)
    assert canceled.state == Job.State.RUNNING and canceled.cancel_requested
    assert services.heartbeat(canceled, "w") is False
    services.fail_or_retry(canceled, "w", error_code="x", message="stop", retryable=True)
    canceled.refresh_from_db()
    assert canceled.state == Job.State.CANCELED


def test_one_active_geometry_job_per_shop(org):
    services.create_job(organization=org, kind=Job.Kind.GEOMETRY_BENCHMARK, idempotency_key="g1")
    with pytest.raises(services.JobConflict):
        services.create_job(organization=org, kind=Job.Kind.GEOMETRY_BENCHMARK, idempotency_key="g2")
    # retrying the first request is still fine (idempotent)
    job, created = services.create_job(organization=org, kind=Job.Kind.GEOMETRY_BENCHMARK,
                                       idempotency_key="g1")
    assert not created


def test_benchmark_endpoint_roles_and_idempotency(shop_a):
    url = f"/api/v1/organizations/{shop_a['org'].pk}/benchmark/"
    client = shop_a["client"]
    first = client.post(url, HTTP_IDEMPOTENCY_KEY="bench-1")
    assert first.status_code == 202, first.content
    again = client.post(url, HTTP_IDEMPOTENCY_KEY="bench-1")
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert client.post(url, HTTP_IDEMPOTENCY_KEY="bench-2").status_code == 409
    job = Job.objects.get(pk=first.json()["id"])
    assert len(job.params["specs"]) == 3
    assert job.params["options"]["tapped_hole_model"] == "tap_drill"

    viewer = make_user("viewer@shop-a.test")
    add_member(shop_a["org"], viewer, ["viewer"])
    assert client_for(viewer).post(url).status_code == 403
    listing = client_for(viewer).get(url).json()
    assert listing["latest"]["id"] == first.json()["id"]
    assert {s["part"] for s in listing["specs"]} == {"BENCH-PLATE-01", "BENCH-BRKT-02",
                                                     "BENCH-SHAFT-03"}


def test_job_api_cancel_requires_engineer(shop_a):
    job = new_job(shop_a["org"])
    viewer = make_user("v@shop-a.test")
    add_member(shop_a["org"], viewer, ["viewer"])
    assert client_for(viewer).post(f"/api/v1/jobs/{job.pk}/cancel/").status_code == 403
    response = shop_a["client"].post(f"/api/v1/jobs/{job.pk}/cancel/")
    assert response.status_code == 200 and response.json()["state"] == "canceled"
    detail = shop_a["client"].get(f"/api/v1/jobs/{job.pk}/").json()
    assert [e["message"] for e in detail["events"]] == ["Queued", "Canceled"]
