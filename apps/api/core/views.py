from __future__ import annotations

import csv
import io

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET
from rest_framework.response import Response
from rest_framework.views import APIView

from orgs.models import Capability
from orgs.permissions import require_capability

from .models import AuditEvent


@require_GET
def healthz(request):
    """Liveness: the process is up. Does not touch dependencies."""
    return JsonResponse({"status": "ok"})


@require_GET
def readyz(request):
    """Readiness: database and cache reachable."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = True
    except Exception:  # noqa: BLE001
        checks["database"] = False
    try:
        cache.set("bpcad:ready", 1, 5)
        checks["cache"] = cache.get("bpcad:ready") == 1
    except Exception:  # noqa: BLE001
        checks["cache"] = False
    ok = all(checks.values())
    return JsonResponse({"status": "ok" if ok else "unavailable", **checks}, status=200 if ok else 503)


@require_GET
def version(request):
    return JsonResponse({"product": settings.PRODUCT_NAME, "version": settings.APP_VERSION,
                         "git_sha": settings.GIT_SHA})


@require_GET
@ensure_csrf_cookie
def csrf(request):
    return JsonResponse({"csrfToken": get_token(request)})


AUDIT_FIELDS = ["created_at", "action", "actor_email", "target_type", "target_id", "ip", "data"]


class AuditEventsView(APIView):
    """Owner-only workspace audit log, as JSON pages or a CSV export."""

    def get(self, request, org_pk):
        require_capability(request, org_pk, Capability.MANAGE)
        qs = AuditEvent.objects.filter(organization_id=org_pk)
        action = request.query_params.get("action")
        if action:
            qs = qs.filter(action__startswith=action)
        if request.query_params.get("export") == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(AUDIT_FIELDS)
            for event in qs.iterator():
                writer.writerow([event.created_at.isoformat(), event.action, event.actor_email,
                                 event.target_type, event.target_id, event.ip or "", event.data])
            response = HttpResponse(buffer.getvalue(), content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="audit-log.csv"'
            return response
        try:
            limit = min(500, max(1, int(request.query_params.get("limit", 100))))
        except ValueError:
            limit = 100
        events = qs[:limit]
        return Response([
            {
                "id": e.id, "created_at": e.created_at, "action": e.action,
                "actor_email": e.actor_email, "target_type": e.target_type,
                "target_id": e.target_id, "ip": e.ip, "data": e.data,
            }
            for e in events
        ])
