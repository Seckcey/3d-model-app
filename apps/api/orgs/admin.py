from django.contrib import admin

from .models import Invitation, Membership, Organization


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    fk_name = "organization"
    raw_id_fields = ["user", "invited_by"]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "allow_external_ai", "max_upload_mb", "max_pdf_pages",
                    "is_active", "created_at"]
    search_fields = ["name", "slug"]
    list_filter = ["is_active", "allow_external_ai"]
    inlines = [MembershipInline]


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ["email", "organization", "roles", "status", "expires_at", "created_at"]
    search_fields = ["email"]
    list_filter = ["organization"]
    readonly_fields = ["token_hash", "accepted_at", "accepted_by", "revoked_at", "last_sent_at"]
