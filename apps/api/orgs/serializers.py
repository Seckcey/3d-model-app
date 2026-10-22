from __future__ import annotations

from rest_framework import serializers

from .models import (
    BOOLEAN_PREFERENCES,
    DEFAULT_PREFERENCES,
    FILENAME_TOKENS,
    PREFERENCE_CHOICES,
    Invitation,
    Membership,
    Organization,
)
from .permissions import membership_for


def validate_preferences(value: dict) -> dict:
    if not isinstance(value, dict):
        raise serializers.ValidationError("Preferences must be an object.")
    unknown = set(value) - set(DEFAULT_PREFERENCES)
    if unknown:
        raise serializers.ValidationError(f"Unknown preference(s): {', '.join(sorted(unknown))}")
    for key, choices in PREFERENCE_CHOICES.items():
        if key in value and value[key] not in choices:
            raise serializers.ValidationError({key: f"Choose one of: {', '.join(choices)}"})
    for key in BOOLEAN_PREFERENCES:
        if key in value and not isinstance(value[key], bool):
            raise serializers.ValidationError({key: "Must be true or false."})
    if "filename_pattern" in value:
        pattern = value["filename_pattern"]
        if not isinstance(pattern, str) or not (3 <= len(pattern) <= 80):
            raise serializers.ValidationError({"filename_pattern": "Use 3-80 characters."})
        if "{part}" not in pattern or "{rev}" not in pattern:
            raise serializers.ValidationError(
                {"filename_pattern": "The pattern must include {part} and {rev}."}
            )
        stripped = pattern
        for token in FILENAME_TOKENS:
            stripped = stripped.replace(token, "")
        if "{" in stripped or "}" in stripped or "/" in stripped or "\\" in stripped:
            raise serializers.ValidationError(
                {"filename_pattern": f"Allowed tokens: {', '.join(FILENAME_TOKENS)}"}
            )
    if "stock_allowance_in" in value:
        allowance = value["stock_allowance_in"]
        if not isinstance(allowance, (int, float)) or not (0 <= allowance <= 2):
            raise serializers.ValidationError({"stock_allowance_in": "Use 0 to 2 inches."})
    if "cam_software" in value and (not isinstance(value["cam_software"], str)
                                    or len(value["cam_software"]) > 80):
        raise serializers.ValidationError({"cam_software": "Use up to 80 characters."})
    return value


class OrganizationSerializer(serializers.ModelSerializer):
    my_roles = serializers.SerializerMethodField()
    preferences = serializers.JSONField(required=False)

    class Meta:
        model = Organization
        fields = [
            "id", "name", "slug", "allow_external_ai", "allowed_ai_providers", "max_upload_mb",
            "max_pdf_pages", "max_active_generation_jobs", "retention_days",
            "monthly_ai_budget_usd", "preferences", "created_at", "my_roles",
        ]
        read_only_fields = ["id", "slug", "created_at", "my_roles"]

    def get_my_roles(self, obj) -> list[str]:
        request = self.context.get("request")
        membership = membership_for(request, obj.pk) if request else None
        return membership.roles if membership else []

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["preferences"] = instance.effective_preferences
        return data

    def validate_preferences(self, value):
        return validate_preferences(value)

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Use at least 2 characters.")
        return value

    def validate_max_upload_mb(self, value):
        if not 1 <= value <= 200:
            raise serializers.ValidationError("Use 1 to 200 MB.")
        return value

    def validate_max_pdf_pages(self, value):
        if not 1 <= value <= 200:
            raise serializers.ValidationError("Use 1 to 200 pages.")
        return value

    def validate_allowed_ai_providers(self, value):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise serializers.ValidationError("Must be a list of provider names.")
        return sorted(set(value))

    def update(self, instance, validated_data):
        if "preferences" in validated_data:
            merged = dict(instance.preferences or {})
            merged.update(validated_data.pop("preferences"))
            instance.preferences = merged
        return super().update(instance, validated_data)


class UserSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.CharField()
    last_login = serializers.DateTimeField()


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "roles", "created_at"]
        read_only_fields = ["id", "user", "created_at"]


class InvitationSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    invited_by_email = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = ["id", "email", "roles", "status", "expires_at", "created_at", "last_sent_at",
                  "invited_by_email"]
        read_only_fields = fields

    def get_invited_by_email(self, obj) -> str | None:
        return obj.invited_by.email if obj.invited_by else None


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    roles = serializers.ListField(child=serializers.CharField(), allow_empty=False)
