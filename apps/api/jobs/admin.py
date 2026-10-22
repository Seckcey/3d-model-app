from django.contrib import admin

from .models import Job, JobEvent


class JobEventInline(admin.TabularInline):
    model = JobEvent
    extra = 0
    readonly_fields = ["at", "state", "stage", "message"]
    can_delete = False


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["kind", "state", "stage", "organization", "attempts", "queued_at", "finished_at"]
    list_filter = ["kind", "state"]
    readonly_fields = ["lease_owner", "lease_expires_at", "heartbeat_at", "result", "params",
                       "engine_versions", "usage"]
    inlines = [JobEventInline]
