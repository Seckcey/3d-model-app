from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from django.core.cache import cache

from tests.helpers import client_for, make_org, make_user


@pytest.fixture(autouse=True)
def _isolated_storage(settings):
    root = Path(tempfile.mkdtemp(prefix="bpcad-test-"))
    settings.FILES_ROOT = root / "files"
    settings.STAGING_ROOT = root / "files" / "staging"
    settings.FILE_UPLOAD_TEMP_DIR = str(root / "files" / "tmp")
    settings.OUTBOX_DIR = root / "outbox"
    for sub in ("tmp", "staging", "orgs"):
        (root / "files" / sub).mkdir(parents=True, exist_ok=True)
    cache.clear()
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch):
    """Queue messages are recorded instead of sent; tests run tasks explicitly."""
    sent: list[str] = []
    monkeypatch.setattr("jobs.services.dispatch", lambda job_id, countdown=None: sent.append(str(job_id)))
    return sent


@pytest.fixture
def shop_a(db):
    owner = make_user("owner@shop-a.test")
    org = make_org("Shop A", owner)
    return {"org": org, "owner": owner, "client": client_for(owner)}


@pytest.fixture
def shop_b(db):
    owner = make_user("owner@shop-b.test")
    org = make_org("Shop B", owner)
    return {"org": org, "owner": owner, "client": client_for(owner)}
