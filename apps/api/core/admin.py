from django.contrib import admin

from .models import AuditEvent, BackupRecord


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "actor_email", "organization", "target_type", "ip"]
    list_filter = ["action", "organization"]
    search_fields = ["actor_email", "target_id", "action"]
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BackupRecord)
class BackupRecordAdmin(admin.ModelAdmin):
    list_display = ["created_at", "kind", "status", "location", "size_bytes"]
    list_filter = ["kind", "status"]
    readonly_fields = [f.name for f in BackupRecord._meta.fields]

    def has_add_permission(self, request):
        return False
