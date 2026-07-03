from rest_framework import serializers

from crm import services
from crm.models import (
    Activity,
    ActivityType,
    Deal,
    LostReason,
    Organization,
    Person,
    Pipeline,
    Stage,
)


class StageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stage
        fields = ["id", "name", "order", "rot_days", "probability"]


class PipelineSerializer(serializers.ModelSerializer):
    stages = StageSerializer(many=True, read_only=True)

    class Meta:
        model = Pipeline
        fields = ["id", "name", "order", "stages"]


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "industry", "website", "gstin", "owner"]


class PersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = ["id", "first_name", "last_name", "job_title", "organization",
                  "owner", "marketing_consent"]


class LostReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = LostReason
        fields = ["id", "label"]


class ActivityTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityType
        fields = ["id", "name", "icon"]


class ActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Activity
        fields = ["id", "type", "subject", "due_at", "duration_min", "owner",
                  "deal", "person", "note", "done", "done_at", "outcome"]
        read_only_fields = ["done", "done_at", "outcome"]
        extra_kwargs = {"owner": {"required": False}}


class DealSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.name", read_only=True, default=None)
    owner_name = serializers.CharField(source="owner.username", read_only=True)
    is_rotten = serializers.SerializerMethodField()
    needs_next_activity = serializers.SerializerMethodField()

    class Meta:
        model = Deal
        fields = ["id", "title", "value", "currency", "pipeline", "stage", "owner",
                  "owner_name", "organization", "organization_name", "expected_close_date",
                  "probability", "status", "lost_reason", "closed_at", "stage_entered_at",
                  "is_rotten", "needs_next_activity"]
        read_only_fields = ["status", "lost_reason", "closed_at", "stage_entered_at"]
        extra_kwargs = {"owner": {"required": False}, "stage": {"required": False}}

    def get_is_rotten(self, obj) -> bool:
        return services.deal_is_rotten(obj)

    def get_needs_next_activity(self, obj) -> bool:
        return services.deal_needs_next_activity(obj)

    def validate(self, attrs):
        pipeline = attrs.get("pipeline") or (self.instance.pipeline if self.instance else None)
        stage = attrs.get("stage")
        if stage and pipeline and stage.pipeline_id != pipeline.id:
            raise serializers.ValidationError("Stage does not belong to pipeline.")
        return attrs
