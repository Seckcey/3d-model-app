from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core import audit

from . import services
from .models import Capability, Invitation, Membership, Organization
from .permissions import member_org_ids, require_capability
from .serializers import (
    InvitationCreateSerializer,
    InvitationSerializer,
    MembershipSerializer,
    OrganizationSerializer,
)


class OrganizationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                          mixins.UpdateModelMixin, mixins.CreateModelMixin,
                          viewsets.GenericViewSet):
    serializer_class = OrganizationSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return Organization.objects.filter(pk__in=member_org_ids(self.request))

    def create(self, request, *args, **kwargs):
        if settings.SIGNUP_MODE != "open" and not request.user.is_staff:
            raise PermissionDenied("New workspaces are created by invitation during the pilot.")
        name = str(request.data.get("name", "")).strip()
        if len(name) < 2:
            raise ValidationError({"name": "Use at least 2 characters."})
        org = services.create_organization(name=name, owner=request.user, request=request)
        request._bpcad_memberships = None
        return Response(self.get_serializer(org).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        require_capability(self.request, serializer.instance.pk, Capability.MANAGE)
        before = {f: getattr(serializer.instance, f) for f in (
            "allow_external_ai", "max_upload_mb", "max_pdf_pages", "retention_days")}
        org = serializer.save()
        audit.record("organization.updated", request=self.request, organization=org, target=org,
                     changed=sorted(serializer.validated_data.keys()),
                     before={k: str(v) for k, v in before.items()})


class OrgScopedMixin:
    """Resolve the organisation from the URL and require a capability."""

    read_capability = Capability.VIEW
    write_capability = Capability.MANAGE

    def get_org(self) -> Organization:
        org_id = self.kwargs["org_pk"]
        if str(org_id) not in member_org_ids(self.request):
            raise NotFound()
        capability = (self.read_capability if self.request.method in ("GET", "HEAD", "OPTIONS")
                      else self.write_capability)
        require_capability(self.request, org_id, capability)
        return Organization.objects.get(pk=org_id)


class MemberViewSet(OrgScopedMixin, mixins.ListModelMixin, mixins.UpdateModelMixin,
                    mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = MembershipSerializer
    pagination_class = None
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        org = self.get_org()
        return Membership.objects.filter(organization=org).select_related("user")

    def update(self, request, *args, **kwargs):
        membership = self.get_object()
        services.update_member_roles(membership, request.data.get("roles"), request=request)
        return Response(self.get_serializer(membership).data)

    def destroy(self, request, *args, **kwargs):
        membership = self.get_object()
        services.remove_member(membership, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationViewSet(OrgScopedMixin, mixins.ListModelMixin, mixins.DestroyModelMixin,
                        viewsets.GenericViewSet):
    serializer_class = InvitationSerializer
    pagination_class = None
    read_capability = Capability.MANAGE
    throttle_scope = "invitations"

    def get_throttles(self):
        if self.action in ("create", "resend"):
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        org = self.get_org()
        return Invitation.objects.filter(organization=org).select_related("invited_by")

    def create(self, request, *args, **kwargs):
        org = self.get_org()
        payload = InvitationCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        invitation, _token = services.create_invitation(
            organization=org,
            email=payload.validated_data["email"],
            roles=payload.validated_data["roles"],
            invited_by=request.user,
            request=request,
        )
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        services.revoke_invitation(self.get_object(), request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def resend(self, request, *args, **kwargs):
        invitation = self.get_object()
        services.resend_invitation(invitation, request=request)
        invitation.refresh_from_db()
        return Response(InvitationSerializer(invitation).data)


class InvitationPreviewView(APIView):
    """Public, token-gated summary shown on the invitation landing page.

    Visiting it also records the token in the session so the invited person may
    complete email-code signup (signup is otherwise closed during the pilot).
    """

    permission_classes = [AllowAny]

    def get(self, request, token: str):
        invitation = services.find_invitation(token)
        if invitation is None:
            raise NotFound("This invitation link is not valid.")
        if invitation.is_pending:
            request.session[services.SESSION_INVITATION_KEY] = token
        User = get_user_model()
        return Response({
            "organization": {"name": invitation.organization.name},
            "email": invitation.email,
            "roles": invitation.roles,
            "status": invitation.status,
            "expires_at": invitation.expires_at,
            "invited_by": invitation.invited_by.get_full_name() if invitation.invited_by else None,
            "account_exists": User.objects.filter(email__iexact=invitation.email).exists(),
        })


class InvitationAcceptView(APIView):
    def post(self, request, token: str):
        invitation = services.find_invitation(token)
        if invitation is None:
            raise NotFound("This invitation link is not valid.")
        with transaction.atomic():
            membership = services.accept_invitation(invitation, request.user, request=request)
        return Response({
            "organization": {"id": str(membership.organization_id),
                             "name": membership.organization.name},
            "roles": membership.roles,
        })


class AdminUserView(APIView):
    """Platform administrator controls: deactivate users and end their sessions."""

    def _require_staff(self, request):
        if not request.user.is_staff:
            raise PermissionDenied("Administrators only.")

    def get(self, request):
        self._require_staff(request)
        User = get_user_model()
        users = User.objects.order_by("email").prefetch_related("memberships__organization")
        return Response([
            {
                "id": str(u.pk), "email": u.email, "full_name": u.full_name,
                "is_active": u.is_active, "is_staff": u.is_staff,
                "last_login": u.last_login, "date_joined": u.date_joined,
                "organizations": [m.organization.name for m in u.memberships.all()],
            }
            for u in users
        ])

    def post(self, request, user_id, operation: str):
        self._require_staff(request)
        user = get_object_or_404(get_user_model(), pk=user_id)
        if operation == "deactivate":
            if user == request.user:
                raise ValidationError({"detail": "You cannot deactivate yourself."})
            user.is_active = False
            user.save(update_fields=["is_active"])
            ended = services.end_user_sessions(user)
        elif operation == "reactivate":
            user.is_active = True
            user.save(update_fields=["is_active"])
            ended = 0
        elif operation == "end-sessions":
            keep = request.session.session_key if user == request.user else None
            ended = services.end_user_sessions(user, except_session_key=keep)
        else:
            raise NotFound()
        audit.record(f"admin.user_{operation.replace('-', '_')}", request=request, target=user,
                     email=user.email, sessions_ended=ended)
        return Response({"id": str(user.pk), "is_active": user.is_active, "sessions_ended": ended})
