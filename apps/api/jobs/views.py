from __future__ import annotations

import uuid

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core import audit
from core.params import filter_by
from orgs.models import Capability, Organization
from orgs.permissions import member_org_ids, require_capability
from projects.models import Artifact, PartRevision, SourceFile
from projects.serializers import ArtifactSerializer

from . import benchmark, health, services
from .models import Job
from .serializers import JobDetailSerializer, JobSerializer


def _idempotency_key(request, fallback: str) -> str:
    key = request.headers.get("Idempotency-Key") or request.data.get("idempotency_key") or fallback
    key = str(key).strip()
    if not 1 <= len(key) <= 120:
        raise ValidationError({"idempotency_key": "Use 1-120 characters."})
    return key


class JobViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    def get_serializer_class(self):
        return JobDetailSerializer if self.action == "retrieve" else JobSerializer

    def get_queryset(self):
        qs = Job.objects.filter(organization__in=member_org_ids(self.request)).select_related(
            "requested_by", "source_file"
        )
        qs = filter_by(qs, self.request.query_params,
                       ["organization", "revision", "source_file", "kind", "state"],
                       ["organization", "revision", "source_file"])
        if self.action == "retrieve":
            qs = qs.prefetch_related("events")
        return qs

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        job = self.get_object()
        require_capability(request, job.organization_id, Capability.EDIT)
        job = services.cancel(job)
        audit.record("job.cancel_requested", request=request, organization=job.organization,
                     target=job, state=job.state)
        return Response(JobDetailSerializer(job).data)


class RevisionJobsView(APIView):
    """POST /revisions/{id}/jobs — Phase 1 supports re-running the intake check.

    Generation, validation and export targets arrive with Phases 2-3 and use
    the same contract: a target, an idempotency key and a 202 with the job ID.
    """

    def post(self, request, pk):
        revision = get_object_or_404(
            PartRevision.objects.filter(organization__in=member_org_ids(request)), pk=pk
        )
        require_capability(request, revision.organization_id, Capability.EDIT)
        target = request.data.get("target")
        if target != Job.Kind.INTAKE_CHECK:
            raise ValidationError({"target": "Only intake_check is available in this release."})
        source = get_object_or_404(SourceFile, pk=request.data.get("source_file"), revision=revision)
        key = _idempotency_key(request, fallback=f"intake:{source.pk}:{uuid.uuid4()}")
        job, created = services.create_job(
            organization=revision.organization, kind=Job.Kind.INTAKE_CHECK, idempotency_key=key,
            requested_by=request.user, revision=revision, source_file=source,
        )
        if created:
            audit.record("job.created", request=request, organization=revision.organization,
                         target=job, kind=job.kind)
        return Response(JobSerializer(job).data,
                        status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK)


class BenchmarkView(APIView):
    def _org(self, request, org_pk, capability):
        if str(org_pk) not in member_org_ids(request):
            from rest_framework.exceptions import NotFound

            raise NotFound()
        require_capability(request, org_pk, capability)
        return Organization.objects.get(pk=org_pk)

    def get(self, request, org_pk):
        org = self._org(request, org_pk, Capability.VIEW)
        jobs = Job.objects.filter(organization=org, kind=Job.Kind.GEOMETRY_BENCHMARK)[:5]
        latest = jobs[0] if jobs else None
        artifacts = (Artifact.objects.filter(job=latest).order_by("filename") if latest else [])
        return Response({
            "latest": JobDetailSerializer(latest).data if latest else None,
            "history": JobSerializer(jobs, many=True).data,
            "artifacts": ArtifactSerializer(artifacts, many=True).data,
            "specs": [
                {"part": s["part"]["number"], "title": s["part"].get("name"),
                 "family": s.get("family")}
                for s in benchmark.load_reference_specs()
            ],
        })

    def post(self, request, org_pk):
        org = self._org(request, org_pk, Capability.EDIT)
        specs = benchmark.load_reference_specs()
        key = _idempotency_key(request, fallback=f"benchmark:{uuid.uuid4()}")
        job, created = services.create_job(
            organization=org,
            kind=Job.Kind.GEOMETRY_BENCHMARK,
            idempotency_key=key,
            requested_by=request.user,
            params={"specs": specs, "options": benchmark.build_options(org.effective_preferences)},
            deadline_seconds=settings.JOB_DEFAULT_DEADLINE_SECONDS,
            max_attempts=2,
        )
        if created:
            audit.record("job.created", request=request, organization=org, target=job, kind=job.kind)
        return Response(JobSerializer(job).data,
                        status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK)


class SystemHealthView(APIView):
    def get(self, request):
        if not request.user.is_staff:
            raise PermissionDenied("Administrators only.")
        report = health.gather()
        report["alerts"] = health.alerts(report)
        return Response(report)
