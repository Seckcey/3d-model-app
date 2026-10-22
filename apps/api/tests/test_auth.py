"""Email-code sign-in: expiry, replay, attempt limits, resend cooldown,
enumeration resistance, logout and session revocation (Phase 1 exit gate)."""

import time

import pytest
from django.core import mail
from django.core.cache import cache
from django.test import Client

from tests.helpers import latest_code, make_org, make_user

AUTH = "/_allauth/browser/v1/auth"


def post(client, path, data=None):
    return client.post(path, data or {}, content_type="application/json")


def request_code(client, email):
    return post(client, f"{AUTH}/code/request", {"email": email})


@pytest.fixture
def member(db):
    user = make_user("machinist@shop.test")
    make_org("Test Shop", user)
    return user


def test_code_login_happy_path(member):
    client = Client()
    response = request_code(client, member.email)
    assert response.status_code == 401  # pending login_by_code flow
    flows = {f["id"]: f for f in response.json()["data"]["flows"]}
    assert flows["login_by_code"]["is_pending"] is True
    code = latest_code(member.email)
    assert len(code) == 6 and code.isdigit()
    assert "sign-in code" in mail.outbox[-1].subject.lower()
    assert code not in mail.outbox[-1].subject

    response = post(client, f"{AUTH}/code/confirm", {"code": code})
    assert response.status_code == 200
    assert response.json()["meta"]["is_authenticated"] is True
    me = client.get("/api/v1/me/")
    assert me.status_code == 200
    assert me.json()["email"] == member.email
    assert me.json()["memberships"][0]["organization"]["name"] == "Test Shop"


def test_code_cannot_be_replayed(member):
    client = Client()
    request_code(client, member.email)
    code = latest_code(member.email)
    assert post(client, f"{AUTH}/code/confirm", {"code": code}).status_code == 200
    client.delete(f"{AUTH}/session")
    assert client.get("/api/v1/me/").status_code == 403
    # the consumed code is gone with the login state; replaying it fails
    assert post(client, f"{AUTH}/code/confirm", {"code": code}).status_code == 409
    assert client.get("/api/v1/me/").status_code == 403


def test_code_expires_after_ten_minutes(member, monkeypatch):
    client = Client()
    request_code(client, member.email)
    code = latest_code(member.email)
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 10 * 60 + 5)
    assert post(client, f"{AUTH}/code/confirm", {"code": code}).status_code == 409
    monkeypatch.setattr(time, "time", real_time)
    assert client.get("/api/v1/me/").status_code == 403


def test_code_still_valid_at_nine_minutes(member, monkeypatch):
    client = Client()
    request_code(client, member.email)
    code = latest_code(member.email)
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 9 * 60)
    assert post(client, f"{AUTH}/code/confirm", {"code": code}).status_code == 200


def test_three_wrong_codes_end_the_attempt(member):
    client = Client()
    request_code(client, member.email)
    code = latest_code(member.email)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(3):
        assert post(client, f"{AUTH}/code/confirm", {"code": wrong}).status_code == 400
    # even the right code no longer works: a new code must be requested
    assert post(client, f"{AUTH}/code/confirm", {"code": code}).status_code == 409


def test_resend_has_sixty_second_cooldown_and_replaces_code(member, monkeypatch):
    client = Client()
    request_code(client, member.email)
    first = latest_code(member.email)
    assert post(client, f"{AUTH}/code/resend").status_code == 429
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 61)
    for _ in range(5):  # codes are random; retry in the rare case of a repeat
        assert post(client, f"{AUTH}/code/resend").status_code == 200
        second = latest_code(member.email)
        if second != first:
            break
        monkeypatch.setattr(time, "time", lambda: real_time() + 200)
    assert second != first
    assert post(client, f"{AUTH}/code/confirm", {"code": first}).status_code == 400
    assert post(client, f"{AUTH}/code/confirm", {"code": second}).status_code == 200


def test_new_code_request_is_rate_limited_per_address(member):
    assert request_code(Client(), member.email).status_code == 401
    response = request_code(Client(), member.email)
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "too_many_login_attempts"
    assert len([m for m in mail.outbox if member.email in m.to]) == 1


def test_unknown_email_gets_same_response(db):
    client = Client()
    response = request_code(client, "nobody@elsewhere.test")
    assert response.status_code == 401
    assert response.json()["data"]["flows"]
    assert "no account" in mail.outbox[-1].body.lower()
    assert "invitation" in mail.outbox[-1].body.lower()
    assert post(client, f"{AUTH}/code/confirm", {"code": "123456"}).status_code == 400


def test_signup_closed_without_invitation(db):
    response = post(Client(), f"{AUTH}/signup", {"email": "walkin@shop.test"})
    assert response.status_code == 403


def code_login(client, email):
    cache.clear()  # the per-address code limit would block the second device
    request_code(client, email)
    assert post(client, f"{AUTH}/code/confirm", {"code": latest_code(email)}).status_code == 200


def test_user_can_end_another_session(member):
    laptop = Client(HTTP_USER_AGENT="Mozilla/5.0 (Macintosh) Chrome/140")
    tablet = Client(HTTP_USER_AGENT="Mozilla/5.0 (iPad) Safari/605")
    for client in (laptop, tablet):
        code_login(client, member.email)
        assert client.get("/api/v1/me/").status_code == 200
    sessions = laptop.get(f"{AUTH}/sessions").json()["data"]
    assert len(sessions) == 2
    other = [s for s in sessions if not s["is_current"]][0]
    response = laptop.delete(f"{AUTH}/sessions", {"sessions": [other["id"]]},
                             content_type="application/json")
    assert response.status_code == 200
    assert tablet.get("/api/v1/me/").status_code == 403
    assert laptop.get("/api/v1/me/").status_code == 200


def test_logout_is_immediate(member):
    client = Client()
    client.force_login(member, backend="django.contrib.auth.backends.ModelBackend")
    assert client.get("/api/v1/me/").status_code == 200
    assert client.delete(f"{AUTH}/session").status_code == 401
    assert client.get("/api/v1/me/").status_code == 403


def test_session_cookie_flags(settings, member):
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.SESSION_COOKIE_AGE == 7 * 24 * 3600
