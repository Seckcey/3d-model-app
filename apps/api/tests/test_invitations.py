import re
from datetime import timedelta

import pytest
from django.core import mail
from django.test import Client
from django.utils import timezone

from accounts.models import User
from orgs.models import Invitation, Membership
from tests.helpers import add_member, client_for, latest_code, make_user

AUTH = "/_allauth/browser/v1/auth"
LINK = re.compile(r"/invite/(\S+)")


def invite(owner_client, org, email, roles, capture):
    with capture(execute=True):
        response = owner_client.post(f"/api/v1/organizations/{org.pk}/invitations/",
                                     {"email": email, "roles": roles}, format="json")
    assert response.status_code == 201, response.content
    token = LINK.search(mail.outbox[-1].body).group(1)
    return response.json(), token


def test_new_person_signs_up_through_invitation(shop_a, django_capture_on_commit_callbacks):
    data, token = invite(shop_a["client"], shop_a["org"], "Newhire@Shop-A.test",
                         ["engineer"], django_capture_on_commit_callbacks)
    assert data["email"] == "newhire@shop-a.test"
    assert data["status"] == "pending"

    browser = Client()
    preview = browser.get(f"/api/v1/invitations/{token}/")
    assert preview.status_code == 200
    assert preview.json()["organization"]["name"] == "Shop A"
    assert preview.json()["account_exists"] is False

    signup = browser.post(f"{AUTH}/signup", {"email": "newhire@shop-a.test"},
                          content_type="application/json")
    assert signup.status_code == 401  # pending email verification by code
    code = latest_code("newhire@shop-a.test")
    verified = browser.post(f"{AUTH}/email/verify", {"key": code}, content_type="application/json")
    assert verified.status_code == 200, verified.content

    accepted = browser.post(f"/api/v1/invitations/{token}/accept/")
    assert accepted.status_code == 200
    user = User.objects.get(email="newhire@shop-a.test")
    assert Membership.objects.get(user=user, organization=shop_a["org"]).roles == ["engineer"]
    assert browser.post(f"/api/v1/invitations/{token}/accept/").status_code == 400


def test_signup_with_a_different_address_is_refused(shop_a, django_capture_on_commit_callbacks):
    _, token = invite(shop_a["client"], shop_a["org"], "invited@shop-a.test", ["viewer"],
                      django_capture_on_commit_callbacks)
    browser = Client()
    browser.get(f"/api/v1/invitations/{token}/")
    response = browser.post(f"{AUTH}/signup", {"email": "someone-else@shop-a.test"},
                            content_type="application/json")
    assert response.status_code == 400
    assert not User.objects.filter(email="someone-else@shop-a.test").exists()


def test_existing_user_accepts_after_code_login(shop_a, shop_b, django_capture_on_commit_callbacks):
    _, token = invite(shop_a["client"], shop_a["org"], shop_b["owner"].email, ["reviewer"],
                      django_capture_on_commit_callbacks)
    browser = Client()
    assert browser.get(f"/api/v1/invitations/{token}/").json()["account_exists"] is True
    browser.post(f"{AUTH}/code/request", {"email": shop_b["owner"].email},
                 content_type="application/json")
    code = latest_code(shop_b["owner"].email)
    assert browser.post(f"{AUTH}/code/confirm", {"code": code},
                        content_type="application/json").status_code == 200
    assert browser.post(f"/api/v1/invitations/{token}/accept/").status_code == 200
    me = browser.get("/api/v1/me/").json()
    assert sorted(m["organization"]["name"] for m in me["memberships"]) == ["Shop A", "Shop B"]


def test_invitation_for_other_address_cannot_be_accepted(shop_a, shop_b,
                                                         django_capture_on_commit_callbacks):
    _, token = invite(shop_a["client"], shop_a["org"], "partner@shop-a.test", ["viewer"],
                      django_capture_on_commit_callbacks)
    response = shop_b["client"].post(f"/api/v1/invitations/{token}/accept/")
    assert response.status_code == 400
    assert not Membership.objects.filter(organization=shop_a["org"], user=shop_b["owner"]).exists()


def test_expired_and_revoked_invitations(shop_a, django_capture_on_commit_callbacks):
    data, token = invite(shop_a["client"], shop_a["org"], "late@shop-a.test", ["viewer"],
                         django_capture_on_commit_callbacks)
    user = make_user("late@shop-a.test")
    Invitation.objects.filter(pk=data["id"]).update(expires_at=timezone.now() - timedelta(minutes=1))
    assert client_for(user).post(f"/api/v1/invitations/{token}/accept/").status_code == 400

    data, token = invite(shop_a["client"], shop_a["org"], "late@shop-a.test", ["viewer"],
                         django_capture_on_commit_callbacks)
    shop_a["client"].delete(f"/api/v1/organizations/{shop_a['org'].pk}/invitations/{data['id']}/")
    assert client_for(user).post(f"/api/v1/invitations/{token}/accept/").status_code == 400


def test_resend_rotates_token(shop_a, django_capture_on_commit_callbacks):
    data, old_token = invite(shop_a["client"], shop_a["org"], "rotate@shop-a.test", ["viewer"],
                             django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        response = shop_a["client"].post(
            f"/api/v1/organizations/{shop_a['org'].pk}/invitations/{data['id']}/resend/")
    assert response.status_code == 200
    new_token = LINK.search(mail.outbox[-1].body).group(1)
    assert new_token != old_token
    assert Client().get(f"/api/v1/invitations/{old_token}/").status_code == 404
    assert Client().get(f"/api/v1/invitations/{new_token}/").status_code == 200


@pytest.mark.parametrize("roles", [["engineer"], ["reviewer"], ["viewer"]])
def test_only_owners_manage_invitations(shop_a, roles):
    person = make_user(f"{roles[0]}@shop-a.test")
    add_member(shop_a["org"], person, roles)
    client = client_for(person)
    url = f"/api/v1/organizations/{shop_a['org'].pk}/invitations/"
    assert client.post(url, {"email": "x@shop-a.test", "roles": ["owner"]}, format="json").status_code == 403
    assert client.get(url).status_code == 403


def test_matching_domain_grants_nothing(shop_a):
    lookalike = make_user("stranger@shop-a.test")
    client = client_for(lookalike)
    assert client.get("/api/v1/me/").json()["memberships"] == []
    assert client.get(f"/api/v1/organizations/{shop_a['org'].pk}/").status_code == 404
    assert client.get("/api/v1/projects/").json()["count"] == 0


def test_last_owner_cannot_be_removed_or_demoted(shop_a):
    org = shop_a["org"]
    membership = Membership.objects.get(organization=org, user=shop_a["owner"])
    client = shop_a["client"]
    url = f"/api/v1/organizations/{org.pk}/members/{membership.pk}/"
    assert client.patch(url, {"roles": ["engineer"]}, format="json").status_code == 400
    assert client.delete(url).status_code == 400


def test_unknown_role_rejected(shop_a):
    url = f"/api/v1/organizations/{shop_a['org'].pk}/invitations/"
    response = shop_a["client"].post(url, {"email": "a@b.test", "roles": ["superuser"]}, format="json")
    assert response.status_code == 400
