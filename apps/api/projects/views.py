from __future__ import annotations

from pathlib import Path

from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core import audit
from core.params import filter_by
from jobs.models import Job
from jobs.services import create_job
from orgs.models import Capability
from orgs.permissions import member_org_ids, require_capability

from . import storage, validators
from .models import Artifact, Customer, ExportControl, Part, PartRevision, Project, SourceFile
from .serializers import (
    ArtifactSerializer,
    CustomerSerializer,
    PartSerializer,
    ProjectSerializer,
    RevisionSerializer,
    SourceFileSerializer,
)


def _org_filter(request, queryset, field: str = "organization"):
    queryset = queryset.filter(**{f"{field}__in": member_org_ids(request)})
    return filter_by(queryset, {field: request.query_params.get("organization")}, [field], [field])


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    pagination_class = None

    def get_queryset(self):
        qs = _org_filter(self.request, Customer.objects.all())
        q = self.request.query_params.get("q")
        return qs.filter(name__icontains=q) if q else qs

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                customer = serializer.save()
        except IntegrityError as exc:
            raise ValidationError({"name": "A customer with this name already exists."}) from exc
        audit.record("customer.created", request=self.request, organization=customer.organization,
                     target=customer)

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        require_capability(self.request, instance.organization_id, Capability.EDIT)
        audit.record("customer.deleted", request=self.request, organization=instance.organization,
                     target=instance, name=instance.name)
        instance.delete()


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer

    def get_queryset(self):
        qs = _org_filter(self.request, Project.objects.select_related("customer")).annotate(
            part_count=Count("parts", distinct=True)
        ).order_by("-updated_at")
        params = self.request.query_params
        qs = filter_by(qs, params, ["status", "customer"], ["customer"])
        q = params.get("q")
        if q:
            qs = qs.filter(
                Q(name__icontains=q) | Q(reference__icontains=q) | Q(customer__name__icontains=q)
                | Q(parts__part_number__icontains=q) | Q(parts__description__icontains=q)
            ).distinct()
        return qs

    def perform_create(self, serializer):
        project = serializer.save(created_by=self.request.user)
        audit.record("project.created", request=self.request, organization=project.organization,
                     target=project, external_ai_allowed=project.external_ai_allowed)

    def perform_update(self, serializer):
        before = serializer.instance.external_ai_allowed
        project = serializer.save()
        if before != project.external_ai_allowed:
            audit.record("project.ai_policy_changed", request=self.request,
                         organization=project.organization, target=project,
                         external_ai_allowed=project.external_ai_allowed)

    def perform_destroy(self, instance):
        # Deleting a project removes its drawings and generated files. Backups
        # keep them until the backup retention period expires (see docs).
        require_capability(self.request, instance.organization_id, Capability.MANAGE)
        paths = list(SourceFile.objects.filter(revision__part__project=instance)
                     .values_list("storage_path", flat=True))
        paths += list(Artifact.objects.filter(revision__part__project=instance)
                      .values_list("storage_path", flat=True))
        audit.record("project.deleted", request=self.request, organization=instance.organization,
                     target=instance, name=instance.name, files_removed=len(paths))
        with transaction.atomic():
            instance.delete()
            transaction.on_commit(lambda: [storage.remove(p) for p in paths])


class PartViewSet(viewsets.ModelViewSet):
    serializer_class = PartSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = _org_filter(self.request, Part.objects.select_related("project", "project__customer"))
        params = self.request.query_params
        qs = filter_by(qs, params, ["project"], ["project"])
        q = params.get("q")
        if q:
            qs = qs.filter(Q(part_number__icontains=q) | Q(description__icontains=q))
        return qs

    def perform_create(self, serializer):
        project = serializer.validated_data["project"]
        part = serializer.save(organization=project.organization, created_by=self.request.user)
        audit.record("part.created", request=self.request, organization=part.organization,
                     target=part, part_number=part.part_number)

    def perform_destroy(self, instance):
        require_capability(self.request, instance.organization_id, Capability.MANAGE)
        audit.record("part.deleted", request=self.request, organization=instance.organization,
                     target=instance, part_number=instance.part_number)
        instance.delete()

    @action(detail=True, methods=["get", "post"])
    def revisions(self, request, pk=None):
        part = self.get_object()
        if request.method == "GET":
            revisions = part.revisions.select_related("part__project", "organization")
            return Response(RevisionSerializer(revisions, many=True).data)
        require_capability(request, part.organization_id, Capability.EDIT)
        serializer = RevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            locked = Part.objects.select_for_update().get(pk=part.pk)
            last = locked.revisions.order_by("-sequence").first()
            project = locked.project
            revision = PartRevision.objects.create(
                organization=locked.organization,
                part=locked,
                sequence=(last.sequence + 1) if last else 1,
                drawing_revision=serializer.validated_data.get("drawing_revision", ""),
                notes=serializer.validated_data.get("notes", ""),
                external_ai_allowed=bool(project.external_ai_allowed
                                         and locked.organization.allow_external_ai),
                created_by=request.user,
            )
        audit.record("revision.created", request=request, organization=revision.organization,
                     target=revision, drawing_revision=revision.drawing_revision,
                     sequence=revision.sequence)
        return Response(RevisionSerializer(revision).data, status=status.HTTP_201_CREATED)


class RevisionViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = RevisionSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]
    throttle_scope = "uploads"

    def get_throttles(self):
        if self.action == "files" and self.request.method == "POST":
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        return _org_filter(
            self.request,
            PartRevision.objects.select_related("part__project", "organization").prefetch_related(
                Prefetch("source_files", queryset=SourceFile.objects.prefetch_related("artifacts"))
            ),
        )

    def perform_update(self, serializer):
        require_capability(self.request, serializer.instance.organization_id, Capability.EDIT)
        if serializer.instance.state != PartRevision.State.DRAFT and "drawing_revision" in serializer.validated_data:
            raise ValidationError({"drawing_revision": "Only draft revisions can be relabelled."})
        serializer.save()

    @action(detail=True, methods=["post"], url_path="export-control")
    def export_control(self, request, pk=None):
        """Owner review of an export-control marking: confirm or clear it."""
        revision = self.get_object()
        require_capability(request, revision.organization_id, Capability.MANAGE)
        decision = request.data.get("decision")
        reason = str(request.data.get("reason", "")).strip()
        if decision not in ("confirmed", "cleared"):
            raise ValidationError({"decision": "Choose confirmed or cleared."})
        if len(reason) < 5:
            raise ValidationError({"reason": "Record why (at least 5 characters)."})
        revision.export_control = (ExportControl.CONFIRMED if decision == "confirmed"
                                   else ExportControl.CLEARED)
        if decision == "confirmed":
            revision.external_ai_allowed = False
        revision.save(update_fields=["export_control", "external_ai_allowed", "updated_at"])
        audit.record("revision.export_control_reviewed", request=request,
                     organization=revision.organization, target=revision, decision=decision,
                     reason=reason)
        return Response(RevisionSerializer(revision).data)

    @action(detail=True, methods=["get", "post"], parser_classes=[MultiPartParser])
    def files(self, request, pk=None):
        revision = self.get_object()
        if request.method == "GET":
            return Response(SourceFileSerializer(revision.source_files.all(), many=True).data)
        require_capability(request, revision.organization_id, Capability.EDIT)
        if revision.state not in (PartRevision.State.DRAFT, PartRevision.State.NEEDS_INPUT):
            raise ValidationError({"detail": "Drawings can only be added to a draft revision."})
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Attach a PDF, PNG or JPEG drawing."})
        org = revision.organization
        max_bytes = org.max_upload_mb * 1024 * 1024
        try:
            tmp_path, digest, size = storage.spool_upload(upload, max_bytes)
        except storage.TooLarge as exc:
            raise ValidationError(
                {"file": f"The file is larger than the {org.max_upload_mb} MB limit."}
            ) from exc
        try:
            existing = SourceFile.objects.filter(revision=revision, sha256=digest).first()
            if existing:
                return Response(SourceFileSerializer(existing).data, status=status.HTTP_200_OK)
            try:
                inspection = validators.inspect(tmp_path, max_pages=org.max_pdf_pages)
            except validators.UploadRejected as rejected:
                audit.record("file.rejected", request=request, organization=org, target=revision,
                             reason=rejected.code, size=size)
                raise ValidationError({"file": rejected.message, "code": rejected.code}) from rejected
            storage_path = storage.publish(
                tmp_path, org.pk, area="sources",
                extension=validators.EXTENSIONS[inspection.content_type],
            )
            tmp_path = None
            with transaction.atomic():
                source = SourceFile.objects.create(
                    organization=org,
                    revision=revision,
                    original_name=Path(upload.name or "drawing").name[:255],
                    content_type=inspection.content_type,
                    size_bytes=size,
                    sha256=digest,
                    page_count=inspection.page_count,
                    storage_path=storage_path,
                    selected_pages=list(range(1, inspection.page_count + 1)),
                    uploaded_by=request.user,
                )
                audit.record("file.uploaded", request=request, organization=org, target=source,
                             sha256=digest, size=size, pages=inspection.page_count)
                create_job(
                    organization=org, kind=Job.Kind.INTAKE_CHECK,
                    idempotency_key=f"intake:{source.pk}", requested_by=request.user,
                    revision=revision, source_file=source,
                )
        finally:
            if tmp_path is not None:
                Path(tmp_path).unlink(missing_ok=True)
        source = SourceFile.objects.prefetch_related("artifacts").get(pk=source.pk)
        return Response(SourceFileSerializer(source).data, status=status.HTTP_201_CREATED)


class SourceFileView(APIView):
    def get(self, request, pk):
        source = get_object_or_404(
            SourceFile.objects.filter(organization__in=member_org_ids(request))
            .prefetch_related("artifacts"),
            pk=pk,
        )
        return Response(SourceFileSerializer(source).data)

    def patch(self, request, pk):
        source = get_object_or_404(
            SourceFile.objects.filter(organization__in=member_org_ids(request)), pk=pk
        )
        require_capability(request, source.organization_id, Capability.EDIT)
        pages = request.data.get("selected_pages")
        if (not isinstance(pages, list) or not pages
                or not all(isinstance(p, int) and 1 <= p <= source.page_count for p in pages)):
            raise ValidationError({"selected_pages": "Choose at least one valid page number."})
        source.selected_pages = sorted(set(pages))
        source.save(update_fields=["selected_pages", "updated_at"])
        return Response(SourceFileSerializer(source).data)


class SourceFileDownloadView(APIView):
    def get(self, request, pk):
        source = get_object_or_404(
            SourceFile.objects.filter(organization__in=member_org_ids(request)), pk=pk
        )
        require_capability(request, source.organization_id, Capability.DOWNLOAD_SOURCES)
        audit.record("file.downloaded", request=request, organization=source.organization,
                     target=source)
        return storage.serve(source.storage_path, download_name=source.original_name,
                             content_type=source.content_type)


class ArtifactDownloadView(APIView):
    PREVIEW_KINDS = {Artifact.Kind.THUMBNAIL, Artifact.Kind.PAGE_IMAGE, Artifact.Kind.GLB}

    def get(self, request, pk):
        artifact = get_object_or_404(
            Artifact.objects.filter(organization__in=member_org_ids(request)), pk=pk
        )
        # Previews are visible to every member; drawing-derived exports follow the
        # source-download rule until a revision is released (Phase 4).
        if artifact.kind not in self.PREVIEW_KINDS and artifact.released_at is None:
            require_capability(request, artifact.organization_id, Capability.DOWNLOAD_SOURCES)
        inline = request.query_params.get("inline") == "1" and artifact.kind in self.PREVIEW_KINDS
        if not inline:
            audit.record("artifact.downloaded", request=request, organization=artifact.organization,
                         target=artifact, kind=artifact.kind)
        response = storage.serve(artifact.storage_path, download_name=artifact.filename,
                                 content_type=artifact.content_type, inline=inline)
        if inline:
            response["Cache-Control"] = "private, max-age=3600"
        return response


class ArtifactListView(APIView):
    def get(self, request):
        qs = _org_filter(request, Artifact.objects.all())
        qs = filter_by(qs, request.query_params, ["job", "revision", "source_file", "kind"],
                       ["job", "revision", "source_file"])
        return Response(ArtifactSerializer(qs[:500], many=True).data)


class SearchView(APIView):
    """Repeat-job lookup: find projects, parts and customers across a workspace."""

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response({"projects": [], "parts": [], "customers": []})
        parts = _org_filter(request, Part.objects.select_related("project", "project__customer"))
        parts = parts.filter(Q(part_number__icontains=q) | Q(description__icontains=q))[:25]
        projects = _org_filter(request, Project.objects.select_related("customer")).filter(
            Q(name__icontains=q) | Q(reference__icontains=q)
        )[:25]
        customers = _org_filter(request, Customer.objects.all()).filter(name__icontains=q)[:25]
        return Response({
            "parts": PartSerializer(parts, many=True).data,
            "projects": ProjectSerializer(projects, many=True).data,
            "customers": CustomerSerializer(customers, many=True, context={"request": request}).data,
        })
