from django.contrib import admin

from .models import Artifact, Customer, Part, PartRevision, Project, SourceFile


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "organization"]
    search_fields = ["name", "code"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "reference", "customer", "organization", "status", "external_ai_allowed"]
    search_fields = ["name", "reference"]
    list_filter = ["status", "organization"]


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ["part_number", "description", "project", "organization"]
    search_fields = ["part_number", "description"]


@admin.register(PartRevision)
class PartRevisionAdmin(admin.ModelAdmin):
    list_display = ["part", "drawing_revision", "sequence", "state", "export_control", "organization"]
    list_filter = ["state", "export_control"]


@admin.register(SourceFile)
class SourceFileAdmin(admin.ModelAdmin):
    list_display = ["original_name", "revision", "content_type", "page_count", "intake_status",
                    "created_at"]
    readonly_fields = ["sha256", "storage_path", "size_bytes", "content_type", "intake_report"]


@admin.register(Artifact)
class ArtifactAdmin(admin.ModelAdmin):
    list_display = ["filename", "kind", "variant", "organization", "is_draft", "created_at"]
    list_filter = ["kind", "is_draft"]
    readonly_fields = ["sha256", "storage_path", "size_bytes"]
