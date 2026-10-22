from rest_framework import serializers

from .models import Job, JobEvent


class JobEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobEvent
        fields = ["at", "state", "stage", "message"]


class JobSerializer(serializers.ModelSerializer):
    elapsed_seconds = serializers.FloatField(read_only=True)
    requested_by_email = serializers.CharField(source="requested_by.email", read_only=True,
                                               default=None)
    source_file_name = serializers.CharField(source="source_file.original_name", read_only=True,
                                             default=None)

    class Meta:
        model = Job
        fields = [
            "id", "organization", "revision", "source_file", "source_file_name", "kind", "state",
            "stage", "idempotency_key", "result", "error_code", "error_message", "attempts",
            "max_attempts", "deadline_seconds", "cancel_requested", "queued_at", "started_at",
            "finished_at", "elapsed_seconds", "engine_versions", "usage", "processing_location",
            "requested_by_email", "created_at",
        ]
        read_only_fields = fields


class JobDetailSerializer(JobSerializer):
    events = JobEventSerializer(many=True, read_only=True)

    class Meta(JobSerializer.Meta):
        fields = [*JobSerializer.Meta.fields, "events"]
        read_only_fields = fields
