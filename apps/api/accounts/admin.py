from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "full_name", "is_active", "is_staff", "last_login", "date_joined"]
    search_fields = ["email", "full_name"]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    fieldsets = (
        (None, {"fields": ("email", "full_name")}),
        ("Access", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "full_name")}),)
    readonly_fields = ["last_login", "date_joined"]
    filter_horizontal = ["groups"]
