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
        fields = ["id", "name", "industry", "website", "gstin", "owner", "custom"]
        read_only_fields = ["custom"]


class PersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = ["id", "first_name", "last_name", "job_title", "organization",
                  "owner", "marketing_consent", "custom"]
        read_only_fields = ["custom"]


class LostReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = LostReason
        fields = ["id", "label"]


class ActivityTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityType
        fields = ["id", "name", "icon"]


class ActivitySerializer(serializers.ModelSerializer):
    type_name = serializers.CharField(source="type.name", read_only=True)
    deal_title = serializers.CharField(source="deal.title", read_only=True, default=None)

    class Meta:
        model = Activity
        fields = ["id", "type", "type_name", "subject", "due_at", "duration_min", "owner",
                  "deal", "deal_title", "person", "lead", "note", "done", "done_at", "outcome"]
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
                  "is_rotten", "needs_next_activity", "custom", "value_auto"]
        read_only_fields = ["status", "lost_reason", "closed_at", "stage_entered_at", "custom"]
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


class LeadSerializer(serializers.ModelSerializer):
    from crm.leads import Lead as _Lead  # local import to avoid top-level cycle

    source_name = serializers.CharField(source="source.name", read_only=True, default=None)
    owner_name = serializers.CharField(source="owner.username", read_only=True, default=None)
    sla_overdue = serializers.SerializerMethodField()

    def get_sla_overdue(self, obj) -> bool:
        from crm.services import lead_is_sla_overdue

        return lead_is_sla_overdue(obj)

    class Meta:
        from crm.leads import Lead

        model = Lead
        fields = ["id", "name", "organization_name", "phone_raw", "phone_normalized",
                  "email", "source", "source_name", "utm", "owner", "owner_name",
                  "status", "note", "disqualify_reason", "converted_deal",
                  "converted_person", "converted_organization", "converted_at",
                  "created_at", "sla_overdue"]
        read_only_fields = ["phone_normalized", "status", "disqualify_reason",
                            "converted_deal", "converted_person", "converted_organization",
                            "converted_at"]
        extra_kwargs = {"owner": {"required": False}}

    def validate(self, attrs):
        if "phone_raw" in attrs:
            from crm.services import normalize_phone

            attrs["phone_normalized"] = normalize_phone(attrs["phone_raw"])
        return attrs


class NoteSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.username", read_only=True, default=None)

    class Meta:
        from crm.models import Note

        model = Note
        fields = ["id", "body", "author", "author_name", "deal", "person", "lead", "created_at"]
        read_only_fields = ["author"]


class CustomFieldDefSerializer(serializers.ModelSerializer):
    class Meta:
        from crm.custom_fields import CustomFieldDef

        model = CustomFieldDef
        fields = ["id", "entity", "name", "key", "field_type", "options",
                  "is_important", "pipeline", "order"]


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", read_only=True, default=None)

    class Meta:
        from crm.audit import AuditLog

        model = AuditLog
        fields = ["id", "actor", "actor_name", "action", "model_name", "object_id",
                  "detail", "ip", "created_at"]


class PersonPhoneSerializer(serializers.ModelSerializer):
    class Meta:
        from crm.models import PersonPhone

        model = PersonPhone
        fields = ["id", "label", "raw", "normalized"]


class PersonEmailSerializer(serializers.ModelSerializer):
    class Meta:
        from crm.models import PersonEmail

        model = PersonEmail
        fields = ["id", "label", "email"]


class PersonDetailSerializer(PersonSerializer):
    phones = PersonPhoneSerializer(many=True, read_only=True)
    emails = PersonEmailSerializer(many=True, read_only=True)
    organization_name = serializers.CharField(source="organization.name",
                                              read_only=True, default=None)
    owner_name = serializers.CharField(source="owner.username", read_only=True, default=None)

    class Meta(PersonSerializer.Meta):
        fields = PersonSerializer.Meta.fields + ["phones", "emails",
                                                 "organization_name", "owner_name"]


class SavedViewSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.username", read_only=True)

    class Meta:
        from crm.models import SavedView

        model = SavedView
        fields = ["id", "name", "entity", "owner", "owner_name", "params", "columns",
                  "sort", "is_shared", "is_pinned"]
        read_only_fields = ["owner"]


class UserSerializer(serializers.ModelSerializer):
    from accounts.models import User as _User

    team_name = serializers.CharField(source="team.name", read_only=True, default=None)

    class Meta:
        from accounts.models import User

        model = User
        fields = ["id", "username", "email", "role", "team", "team_name", "is_active"]
        read_only_fields = ["username", "is_active"]


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        from crm.models import Product

        model = Product
        fields = ["id", "name", "sku", "category", "unit_price", "tax_rate", "is_active"]


class DealLineItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        from crm.models import DealLineItem

        model = DealLineItem
        fields = ["id", "product", "product_name", "quantity", "unit_price",
                  "discount_pct", "tax_rate", "subtotal"]
        extra_kwargs = {"unit_price": {"required": False}, "tax_rate": {"required": False}}

    def get_subtotal(self, obj) -> str:
        return str(obj.subtotal)


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        from crm.models import Notification

        model = Notification
        fields = ["id", "kind", "title", "body", "link_entity", "link_id",
                  "read_at", "created_at"]


class EmailAccountSerializer(serializers.ModelSerializer):
    class Meta:
        from crm.models import EmailAccount

        model = EmailAccount
        fields = ["id", "provider", "address", "status", "sync_scope",
                  "last_sync_at", "error"]  # oauth_credentials NEVER exposed
        read_only_fields = ["status", "last_sync_at", "error"]


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        from accounts.models import User

        model = User
        fields = ["id", "username", "email", "password", "role", "team"]

    def validate_password(self, value):
        from django.contrib.auth.password_validation import validate_password

        validate_password(value)
        return value


class StageWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stage
        fields = ["id", "pipeline", "name", "order", "rot_days", "probability"]


class FileAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.username",
                                             read_only=True, default=None)

    class Meta:
        from crm.models import FileAttachment

        model = FileAttachment
        fields = ["id", "name", "size", "content_type", "uploaded_by_name",
                  "deal", "person", "lead", "created_at"]


class WebhookSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        from crm.models import WebhookSubscription

        model = WebhookSubscription
        fields = ["id", "url", "events", "secret", "is_active",
                  "last_delivery_at", "last_error"]
        extra_kwargs = {"secret": {"write_only": True}}  # never readable back


class AutomationRuleSerializer(serializers.ModelSerializer):
    pipeline_name = serializers.CharField(source="pipeline.name", read_only=True,
                                          default=None)

    class Meta:
        from crm.automation import AutomationRule

        model = AutomationRule
        fields = ["id", "name", "trigger", "pipeline", "pipeline_name", "conditions",
                  "actions", "is_active", "order"]

    def validate_actions(self, value):
        known = {"create_activity", "move_stage", "update_field", "change_owner", "notify"}
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError("At least one action is required.")
        bad = [a.get("type") for a in value if a.get("type") not in known]
        if bad:
            raise serializers.ValidationError(f"Unknown action type(s): {bad}")
        return value

    def validate_conditions(self, value):
        from crm.automation import OPS

        for group in ("all", "any"):
            for c in (value or {}).get(group, []):
                if c.get("op") not in OPS:
                    raise serializers.ValidationError(f"Unknown operator: {c.get('op')}")
                if not c.get("field"):
                    raise serializers.ValidationError("Condition field is required.")
        return value


class AutomationRunSerializer(serializers.ModelSerializer):
    rule_name = serializers.CharField(source="rule.name", read_only=True)

    class Meta:
        from crm.automation import AutomationRun

        model = AutomationRun
        fields = ["id", "rule", "rule_name", "event_type", "record_id", "status",
                  "depth", "detail", "created_at"]
