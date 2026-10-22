from __future__ import annotations

from rest_framework import serializers

from orgs.models import Capability, Organization
from orgs.permissions import require_capability

from .models import Artifact, Customer, Part, PartRevision, Project, SourceFile


class OrgField(serializers.PrimaryKeyRelatedField):
    """Organisation chosen on create; only the user's own workspaces resolve."""

    def get_queryset(self):
        from orgs.permissions import member_org_ids

        request = self.context.get("request")
        return Organization.objects.filter(is_active=True, pk__in=member_org_ids(request))


class CustomerSerializer(serializers.ModelSerializer):
    organization = OrgField()

    class Meta:
        model = Customer
        fields = ["id", "organization", "name", "code", "notes", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        org = attrs.get("organization") or self.instance.organization
        if self.instance and "organization" in attrs and attrs["organization"] != self.instance.organization:
            raise serializers.ValidationError({"organization": "Cannot move between workspaces."})
        require_capability(self.context["request"], org.pk, Capability.EDIT)
        return attrs


class ProjectSerializer(serializers.ModelSerializer):
    organization = OrgField()
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)
    part_count = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = Project
        fields = [
            "id", "organization", "customer", "customer_name", "name", "reference", "status",
            "due_date", "external_ai_allowed", "notes", "created_at", "updated_at", "part_count",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "customer_name", "part_count"]

    def validate(self, attrs):
        org = attrs.get("organization") or self.instance.organization
        if self.instance and "organization" in attrs and attrs["organization"] != self.instance.organization:
            raise serializers.ValidationError({"organization": "Cannot move between workspaces."})
        require_capability(self.context["request"], org.pk, Capability.EDIT)
        customer = attrs.get("customer")
        if customer is not None and customer.organization_id != org.pk:
            raise serializers.ValidationError({"customer": "Unknown customer."})
        if attrs.get("external_ai_allowed") and not org.allow_external_ai:
            raise serializers.ValidationError(
                {"external_ai_allowed": "External AI processing is disabled for this workspace."}
            )
        name = attrs.get("name")
        if name is not None and len(name.strip()) < 2:
            raise serializers.ValidationError({"name": "Use at least 2 characters."})
        return attrs


class PartSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source="project.name", read_only=True)
    customer_name = serializers.CharField(source="project.customer.name", read_only=True, default=None)
    latest_revision = serializers.SerializerMethodField()

    class Meta:
        model = Part
        fields = [
            "id", "organization", "project", "project_name", "customer_name", "part_number",
            "description", "material", "quantity", "created_at", "updated_at", "latest_revision",
        ]
        read_only_fields = ["id", "organization", "created_at", "updated_at", "project_name",
                            "customer_name", "latest_revision"]

    def get_latest_revision(self, obj):
        revision = obj.revisions.order_by("-sequence").first()
        if revision is None:
            return None
        return {"id": str(revision.pk), "drawing_revision": revision.drawing_revision,
                "sequence": revision.sequence, "state": revision.state}

    def validate_part_number(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("A part number is required.")
        return value

    def validate(self, attrs):
        project = attrs.get("project") or self.instance.project
        if self.instance and "project" in attrs and attrs["project"] != self.instance.project:
            raise serializers.ValidationError({"project": "Parts cannot move between projects."})
        request = self.context["request"]
        from orgs.permissions import membership_for

        if membership_for(request, project.organization_id) is None:
            raise serializers.ValidationError({"project": "Unknown project."})
        require_capability(request, project.organization_id, Capability.EDIT)
        part_number = attrs.get("part_number")
        if part_number:
            clash = Part.objects.filter(project=project, part_number__iexact=part_number)
            if self.instance:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError({"part_number": "This part is already in the project."})
        return attrs


class SourceFileSerializer(serializers.ModelSerializer):
    uploaded_by_email = serializers.CharField(source="uploaded_by.email", read_only=True, default=None)
    thumbnails = serializers.SerializerMethodField()

    class Meta:
        model = SourceFile
        fields = [
            "id", "revision", "original_name", "content_type", "size_bytes", "sha256",
            "page_count", "selected_pages", "intake_status", "intake_report", "created_at",
            "uploaded_by_email", "thumbnails",
        ]
        read_only_fields = fields

    def get_thumbnails(self, obj):
        items = [a for a in obj.artifacts.all() if a.kind in (Artifact.Kind.THUMBNAIL,
                                                               Artifact.Kind.PAGE_IMAGE)]
        pages: dict[int, dict] = {}
        for artifact in items:
            page = artifact.metadata.get("page", 1)
            pages.setdefault(page, {"page": page})[artifact.kind] = str(artifact.pk)
        return [pages[p] for p in sorted(pages)]


class RevisionSerializer(serializers.ModelSerializer):
    source_files = SourceFileSerializer(many=True, read_only=True)
    effective_external_ai = serializers.BooleanField(read_only=True)
    part_number = serializers.CharField(source="part.part_number", read_only=True)

    class Meta:
        model = PartRevision
        fields = [
            "id", "organization", "part", "part_number", "drawing_revision", "sequence", "state",
            "external_ai_allowed", "effective_external_ai", "export_control",
            "export_control_markings", "notes", "created_at", "updated_at", "source_files",
        ]
        read_only_fields = [
            "id", "organization", "part", "part_number", "sequence", "state",
            "effective_external_ai", "export_control", "export_control_markings", "created_at",
            "updated_at", "source_files",
        ]

    def validate_drawing_revision(self, value: str) -> str:
        return value.strip().upper()[:20]

    def validate_external_ai_allowed(self, value: bool) -> bool:
        if value and self.instance is not None:
            if not self.instance.part.project.external_ai_allowed:
                raise serializers.ValidationError("External AI is off for this project.")
            if self.instance.export_control in ("detected", "confirmed"):
                raise serializers.ValidationError(
                    "An export-control marking was found; an owner must review it first."
                )
        return value


class ArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Artifact
        fields = ["id", "kind", "variant", "filename", "content_type", "size_bytes", "sha256",
                  "is_draft", "released_at", "metadata", "created_at", "job", "revision"]
        read_only_fields = fields
