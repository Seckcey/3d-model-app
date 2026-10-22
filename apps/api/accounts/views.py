from __future__ import annotations

import time

from allauth.account.internal.constants import LoginStageKey
from allauth.account.stages import LoginStageController
from allauth.headless.account.views import ResendLoginCodeView
from allauth.headless.base.response import RateLimitResponse
from django.conf import settings
from django.core.cache import cache
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from orgs.models import CAPABILITY_ROLES

from .adapter import login_code_sent_key


class CooldownResendLoginCodeView(ResendLoginCodeView):
    """allauth's resend endpoint plus a per-address sixty-second cooldown.

    A resend replaces the previous code (the old one stops working) because the
    pending code lives in the server-side login state.
    """

    def post(self, request, *args, **kwargs):
        stage = LoginStageController.enter(request, LoginStageKey.LOGIN_BY_CODE)
        email = stage.state.get("email") if stage else None
        if email:
            sent_at = cache.get(login_code_sent_key(email))
            cooldown = settings.LOGIN_CODE_RESEND_COOLDOWN_SECONDS
            if sent_at and time.time() - sent_at < cooldown:
                return RateLimitResponse(request)
        return super().post(request, *args, **kwargs)


class MeSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, allow_blank=True)


def capabilities_for(roles: list[str]) -> list[str]:
    return sorted(cap for cap, granted in CAPABILITY_ROLES.items() if set(roles) & granted)


class MeView(APIView):
    def get(self, request):
        user = request.user
        memberships = (
            user.memberships.select_related("organization")
            .filter(organization__is_active=True)
            .order_by("organization__name")
        )
        return Response(
            {
                "id": str(user.pk),
                "email": user.email,
                "full_name": user.full_name,
                "is_staff": user.is_staff,
                "memberships": [
                    {
                        "organization": {
                            "id": str(m.organization_id),
                            "name": m.organization.name,
                            "slug": m.organization.slug,
                        },
                        "roles": m.roles,
                        "capabilities": capabilities_for(m.roles),
                    }
                    for m in memberships
                ],
                "signup_mode": settings.SIGNUP_MODE,
            }
        )

    def patch(self, request):
        serializer = MeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.full_name = serializer.validated_data["full_name"].strip()
        request.user.save(update_fields=["full_name"])
        return self.get(request)
