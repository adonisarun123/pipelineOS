from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from crm import services
from crm.models import Activity, Deal, LostReason, Organization, Person, Pipeline, Stage

from .serializers import (
    ActivitySerializer,
    DealSerializer,
    LostReasonSerializer,
    OrganizationSerializer,
    PersonSerializer,
    PipelineSerializer,
)


class SoftDeleteMixin:
    """U-1: delete = soft, admin/manager only. Hard delete does not exist in the API."""

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in ("admin", "manager"):
            return Response({"detail": "Delete requires admin or manager role."}, status=403)
        obj = self.get_object()
        obj.is_deleted = True
        obj.save(update_fields=["is_deleted", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminWriteMixin:
    """Config objects (P4 persona): everyone reads, only admins write."""

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.user.role != "admin":
            self.permission_denied(request, message="Only admins can configure this.")


class LoginView(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        from accounts.models import User

        user = User.objects.get(auth_token__key=response.data["token"])
        response.data.update(
            {"user_id": user.id, "username": user.username, "role": user.role}
        )
        if user.tenant_id:
            from crm import audit

            audit.log(actor=user, action="login", request=request, tenant_id=user.tenant_id)
        return response


class PipelineViewSet(AdminWriteMixin, viewsets.ModelViewSet):
    serializer_class = PipelineSerializer

    def get_queryset(self):
        return Pipeline.objects.prefetch_related("stages")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["get"])
    def kanban(self, request, pk=None):
        """D-3: per-stage cards, counts, totals, rot/next-activity flags."""
        pipeline = self.get_object()
        deals = services.annotate_flags(
            services.visible_deals(request.user)
            .filter(pipeline=pipeline, status=Deal.Status.OPEN)
            .select_related("stage", "organization", "owner")
        )
        if request.query_params.get("owner") == "me":
            deals = deals.filter(owner=request.user)
        by_stage: dict[int, list] = {}
        for deal in deals:
            by_stage.setdefault(deal.stage_id, []).append(deal)
        columns = []
        for stage in pipeline.stages.all():
            stage_deals = by_stage.get(stage.id, [])
            columns.append({
                "stage": {
                    "id": stage.id, "name": stage.name,
                    "rot_days": stage.rot_days, "probability": stage.probability,
                },
                "count": len(stage_deals),
                "total_value": str(sum(d.value for d in stage_deals)),
                "deals": DealSerializer(stage_deals, many=True).data,
            })
        return Response({"pipeline": {"id": pipeline.id, "name": pipeline.name},
                         "columns": columns})

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        """R-1 (Phase 1 basic pipeline summary)."""
        return Response(services.pipeline_summary(self.get_object(), request.user))


class DealViewSet(SoftDeleteMixin, viewsets.ModelViewSet):
    serializer_class = DealSerializer

    def get_queryset(self):
        qs = services.annotate_flags(
            services.visible_deals(self.request.user)
            .select_related("stage", "organization", "owner")
        )
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("pipeline"):
            qs = qs.filter(pipeline_id=p["pipeline"])
        if p.get("stage"):
            qs = qs.filter(stage_id=p["stage"])
        if p.get("owner") == "me":
            qs = qs.filter(owner=self.request.user)
        elif p.get("owner"):
            qs = qs.filter(owner_id=p["owner"])
        if p.get("min_value"):
            qs = qs.filter(value__gte=p["min_value"])
        if p.get("max_value"):
            qs = qs.filter(value__lte=p["max_value"])
        for param, val in p.items():  # CF-3: ?cf_<key>=value equality via typed table
            if not param.startswith("cf_") or not val:
                continue
            from django.db.models import Q as _Q

            from crm.custom_fields import CustomFieldValue

            key = param[3:]
            vq = CustomFieldValue.objects.filter(definition__entity="deal",
                                                 definition__key=key)
            cond = _Q(value_text=val)
            from decimal import Decimal, InvalidOperation

            try:
                cond |= _Q(value_number=Decimal(val))
            except InvalidOperation:
                pass  # non-numeric input can't match the number column
            qs = qs.filter(pk__in=vq.filter(cond).values("record_id"))
        return qs

    def perform_create(self, serializer):
        serializer.instance = services.create_deal(
            user=self.request.user,
            title=serializer.validated_data["title"],
            pipeline=serializer.validated_data["pipeline"],
            stage=serializer.validated_data.get("stage"),
            value=serializer.validated_data.get("value", 0),
            organization=serializer.validated_data.get("organization"),
            owner=serializer.validated_data.get("owner"),
            expected_close_date=serializer.validated_data.get("expected_close_date"),
        )
        services.notify_assignment(serializer.instance, entity="deal",
                                   owner=serializer.instance.owner, actor=self.request.user)

    @action(detail=True, methods=["get", "post"])
    def line_items(self, request, pk=None):
        """PR-2: list/add line items; recomputes value when value_auto."""
        from crm.models import DealLineItem, Product

        from .serializers import DealLineItemSerializer

        deal = self.get_object()
        if request.method == "POST":
            product = get_object_or_404(Product, pk=request.data.get("product"))
            serializer = DealLineItemSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            item = DealLineItem(deal=deal, created_by=request.user,
                                **{k: v for k, v in serializer.validated_data.items()
                                   if k != "product"}, product=product)
            if "unit_price" not in serializer.validated_data:
                item.unit_price = product.unit_price
            if "tax_rate" not in serializer.validated_data:
                item.tax_rate = product.tax_rate
            item.save()
            services.recompute_deal_value(deal)
        items = deal.line_items.select_related("product")
        return Response({
            "items": DealLineItemSerializer(items, many=True).data,
            "deal_value": str(deal.value), "value_auto": deal.value_auto,
        })

    @action(detail=True, methods=["delete"],
            url_path=r"line_items/(?P<item_id>\d+)")
    def remove_line_item(self, request, pk=None, item_id=None):
        from crm.models import DealLineItem

        deal = self.get_object()
        item = get_object_or_404(DealLineItem, pk=item_id, deal=deal)
        item.is_deleted = True
        item.save(update_fields=["is_deleted", "updated_at"])
        services.recompute_deal_value(deal)
        return Response({"deal_value": str(deal.value)})

    def perform_update(self, serializer):
        old_owner_id = serializer.instance.owner_id
        deal = serializer.save()
        services.recompute_deal_value(deal)
        if deal.owner_id != old_owner_id:
            services.notify_assignment(deal, entity="deal", owner=deal.owner,
                                       actor=self.request.user)

    @action(detail=True, methods=["post"])
    def set_custom(self, request, pk=None):
        """CF-3: set custom field values {key: value}; null clears."""
        from crm import custom_fields

        deal = self.get_object()
        cache = custom_fields.set_custom_values(deal, "deal", dict(request.data), request.user)
        return Response({"custom": cache})

    @action(detail=False, methods=["post"])
    def bulk(self, request):
        """C-6: bulk edit owner/stage — admin/manager only, permission-gated."""
        if request.user.role not in ("admin", "manager"):
            return Response({"detail": "Bulk edit requires admin or manager role."}, status=403)
        ids = request.data.get("ids") or []
        changes = request.data.get("set") or {}
        deals = list(self.get_queryset().filter(pk__in=ids))
        updated = 0
        new_owner = None
        if changes.get("owner"):
            from accounts.models import User as _User

            new_owner = get_object_or_404(
                _User.objects.filter(tenant_id=request.user.tenant_id),
                pk=changes["owner"])
        stage = None
        if changes.get("stage_id"):
            stage = get_object_or_404(Stage, pk=changes["stage_id"])
        for deal in deals:
            if new_owner is not None and deal.owner_id != new_owner.id:
                deal.owner = new_owner
                deal.save(update_fields=["owner", "updated_at"])
                services.notify_assignment(deal, entity="deal", owner=new_owner,
                                           actor=request.user)
            if stage is not None and deal.status == "open":
                services.change_stage(deal, stage, request.user)
            updated += 1
        return Response({"updated": updated})

    @action(detail=False, methods=["get"])
    def export(self, request):
        """I-3: CSV export of the current filtered list — audit-logged."""
        import csv

        from django.http import HttpResponse as DjangoResponse

        from crm import audit

        if request.user.role not in ("admin", "manager"):
            return Response({"detail": "Export requires admin or manager role."}, status=403)
        qs = self.get_queryset().select_related("pipeline", "lost_reason")
        resp = DjangoResponse(content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=deals.csv"
        w = csv.writer(resp)
        w.writerow(["id", "title", "value", "currency", "pipeline", "stage", "status",
                    "owner", "organization", "expected_close_date", "lost_reason",
                    "created_at", "custom"])
        count = 0
        for d in qs:
            w.writerow([d.id, d.title, d.value, d.currency, d.pipeline.name, d.stage.name,
                        d.status, d.owner.username,
                        d.organization.name if d.organization else "",
                        d.expected_close_date or "",
                        d.lost_reason.label if d.lost_reason else "",
                        d.created_at.isoformat(), d.custom])
            count += 1
        audit.log(actor=request.user, action="export", model_name="deal",
                  detail={"row_count": count,
                          "filters": dict(request.query_params.items())},
                  request=request)
        return resp

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        deal = self.get_object()
        stage = get_object_or_404(Stage, pk=request.data.get("stage_id"))
        nudges = services.stage_nudges(deal, stage)  # CF-2: prompt, don't block
        services.change_stage(deal, stage, request.user)
        data = DealSerializer(deal).data
        data["nudges"] = nudges
        return Response(data)

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """C-4/D-9: the deal's full history, reverse chronological."""
        deal = self.get_object()
        events = services.deal_timeline(deal)
        for e in events:
            e["at"] = e["at"].isoformat() if e["at"] else None
        return Response({"deal": DealSerializer(deal).data, "events": events})

    @action(detail=True, methods=["post"])
    def add_note(self, request, pk=None):
        from crm.models import Note

        from .serializers import NoteSerializer

        deal = self.get_object()
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"detail": "Note body is required."}, status=400)
        note = Note(body=body, deal=deal, author=request.user, created_by=request.user)
        note.save()
        return Response(NoteSerializer(note).data, status=201)

    @action(detail=True, methods=["post"])
    def won(self, request, pk=None):
        deal = self.get_object()
        services.mark_won(deal, request.user)
        return Response(DealSerializer(deal).data)

    @action(detail=True, methods=["post"])
    def lost(self, request, pk=None):
        deal = self.get_object()
        reason = None
        if request.data.get("lost_reason_id"):
            reason = get_object_or_404(LostReason, pk=request.data["lost_reason_id"])
        services.mark_lost(deal, request.user, reason)
        return Response(DealSerializer(deal).data)


class ActivityViewSet(SoftDeleteMixin, viewsets.ModelViewSet):
    serializer_class = ActivitySerializer

    def get_queryset(self):
        qs = Activity.objects.select_related("type", "deal")
        user = self.request.user
        if user.is_admin_role:
            return qs
        if user.is_manager_role and user.team_id:
            from django.db.models import Q

            return qs.filter(Q(owner=user) | Q(owner__team_id=user.team_id))
        return qs.filter(owner=user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user,
                        owner=serializer.validated_data.get("owner") or self.request.user)

    @action(detail=False, methods=["get"])
    def my(self, request):
        """A-2: Overdue / Today / This week / Planned — a rep's homepage."""
        buckets = services.my_activity_buckets(request.user)
        return Response({k: ActivitySerializer(v, many=True).data for k, v in buckets.items()})

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        result = services.complete_activity(
            self.get_object(), request.user, outcome=request.data.get("outcome", "")
        )
        return Response({
            "activity": ActivitySerializer(result["activity"]).data,
            "prompt_next": result["prompt_next"],
        }, status=status.HTTP_200_OK)


class OrganizationViewSet(SoftDeleteMixin, viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        qs = Organization.objects.all()
        q = self.request.query_params.get("q")
        return qs.filter(name__icontains=q) if q else qs

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        """C-5 for organizations."""
        if request.user.role not in ("admin", "manager"):
            return Response({"detail": "Merge requires admin or manager role."}, status=403)
        primary = self.get_object()
        duplicate = get_object_or_404(Organization, pk=request.data.get("duplicate_id"))
        return Response(services.merge_organizations(primary, duplicate, request.user))

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PersonViewSet(SoftDeleteMixin, viewsets.ModelViewSet):
    def get_serializer_class(self):
        from .serializers import PersonDetailSerializer

        return PersonDetailSerializer

    def get_queryset(self):
        qs = (Person.objects.select_related("organization", "owner")
              .prefetch_related("phones", "emails"))
        q = self.request.query_params.get("q")
        if q:
            from django.db.models import Q as _Q

            qs = qs.filter(_Q(first_name__icontains=q) | _Q(last_name__icontains=q)
                           | _Q(organization__name__icontains=q))
        return qs

    def perform_create(self, serializer):
        from crm.models import PersonEmail, PersonPhone

        person = serializer.save(created_by=self.request.user,
                                 owner=serializer.validated_data.get("owner")
                                 or self.request.user)
        phone = self.request.data.get("phone")
        email = self.request.data.get("email")
        if phone:
            PersonPhone(person=person, raw=phone,
                        normalized=services.normalize_phone(phone),
                        created_by=self.request.user).save()
        if email:
            PersonEmail(person=person, email=email, created_by=self.request.user).save()

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        """C-5: merge duplicate into this person. Admin/manager only."""
        if request.user.role not in ("admin", "manager"):
            return Response({"detail": "Merge requires admin or manager role."}, status=403)
        primary = self.get_object()
        duplicate = get_object_or_404(Person, pk=request.data.get("duplicate_id"))
        result = services.merge_people(primary, duplicate, request.user)
        return Response(result)

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """C-4 for people."""
        from .serializers import PersonDetailSerializer

        person = self.get_object()
        events = services.person_timeline(person)
        for e in events:
            e["at"] = e["at"].isoformat() if e["at"] else None
        return Response({"person": PersonDetailSerializer(person).data, "events": events})


class LostReasonViewSet(AdminWriteMixin, viewsets.ModelViewSet):
    serializer_class = LostReasonSerializer
    pagination_class = None

    def get_queryset(self):
        return LostReason.objects.all()


class LeadViewSet(SoftDeleteMixin, viewsets.ModelViewSet):
    """L-1 queue + L-3/L-4/L-5 actions."""

    def get_serializer_class(self):
        from .serializers import LeadSerializer

        return LeadSerializer

    def get_queryset(self):
        from crm.leads import Lead

        qs = services.visible_owned(Lead.objects.select_related("source", "owner"),
                                    self.request.user)
        status_f = self.request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        return qs

    def perform_create(self, serializer):
        lead = serializer.save(created_by=self.request.user,
                               owner=serializer.validated_data.get("owner") or self.request.user)
        services.notify_assignment(lead, entity="lead", owner=lead.owner,
                                   actor=self.request.user)
        from crm import events

        events.emit("lead.created", {"id": lead.pk, "name": lead.name,
                                     "source": lead.source.name if lead.source else None},
                    lead.tenant_id)

    def perform_update(self, serializer):
        old_owner_id = serializer.instance.owner_id
        lead = serializer.save()
        if lead.owner_id != old_owner_id:
            services.notify_assignment(lead, entity="lead", owner=lead.owner,
                                       actor=self.request.user)

    @action(detail=False, methods=["get"])
    def duplicates(self, request):
        """L-5: check before save. ?phone=&email=&org_name="""
        from .serializers import LeadSerializer

        d = services.find_lead_duplicates(
            phone=request.query_params.get("phone", ""),
            email=request.query_params.get("email", ""),
            org_name=request.query_params.get("org_name", ""),
        )
        return Response({"leads": LeadSerializer(d["leads"], many=True).data,
                         "people": PersonSerializer(d["people"], many=True).data})

    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        """L-3: one-click convert to deal."""
        lead = self.get_object()
        pipeline = get_object_or_404(Pipeline, pk=request.data.get("pipeline_id"))
        stage = None
        if request.data.get("stage_id"):
            stage = get_object_or_404(Stage, pk=request.data["stage_id"])
        services.convert_lead(lead=lead, user=request.user, pipeline=pipeline, stage=stage,
                              deal_title=request.data.get("deal_title", ""),
                              value=request.data.get("value", 0))
        return Response(self.get_serializer(lead).data)

    @action(detail=True, methods=["post"])
    def disqualify(self, request, pk=None):
        lead = self.get_object()
        reason = None
        if request.data.get("reason_id"):
            reason = get_object_or_404(LostReason, pk=request.data["reason_id"])
        services.disqualify_lead(lead, request.user, reason)
        return Response(self.get_serializer(lead).data)

    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        """L-1 fast disposition: new → attempted → contacted."""
        from crm.leads import Lead

        lead = self.get_object()
        new_status = request.data.get("status")
        if new_status not in (Lead.Status.NEW, Lead.Status.ATTEMPTED, Lead.Status.CONTACTED):
            return Response({"detail": "Use convert/disqualify for closing statuses."}, status=400)
        lead.status = new_status
        lead.save(update_fields=["status", "updated_at"])
        services.stamp_first_response(lead)  # L-8
        return Response(self.get_serializer(lead).data)


class LeadSourceViewSet(AdminWriteMixin, viewsets.ModelViewSet):
    pagination_class = None

    def get_serializer_class(self):
        from rest_framework import serializers as s

        from crm.leads import LeadSource

        class LeadSourceSerializer(s.ModelSerializer):
            class Meta:
                model = LeadSource
                fields = ["id", "name", "token", "sla_minutes", "field_mapping"]

            def to_representation(self, instance):
                data = super().to_representation(instance)
                req = self.context.get("request")
                if req is None or req.user.role != "admin":
                    data.pop("token", None)  # token visible to admins only
                return data

        return LeadSourceSerializer

    def get_queryset(self):
        from crm.leads import LeadSource

        return LeadSource.objects.all()


class ActivityTypeViewSet(AdminWriteMixin, viewsets.ModelViewSet):
    pagination_class = None

    def get_serializer_class(self):
        from .serializers import ActivityTypeSerializer

        return ActivityTypeSerializer

    def get_queryset(self):
        from crm.models import ActivityType

        return ActivityType.objects.all()


class SearchView(APIView):
    """S-1: global search."""

    def get(self, request):
        from .serializers import DealSerializer, LeadSerializer, OrganizationSerializer

        r = services.global_search(request.user, request.query_params.get("q", ""))
        return Response({
            "deals": DealSerializer(r["deals"], many=True).data,
            "people": PersonSerializer(r["people"], many=True).data,
            "organizations": OrganizationSerializer(r["organizations"], many=True).data,
            "leads": LeadSerializer(r["leads"], many=True).data,
        })


class ImportView(APIView):
    """I-1: CSV import. POST multipart: file, strategy, dry_run, mapping (json, optional)."""

    def post(self, request):
        import json as _json

        from crm import importer

        if request.user.role not in ("admin", "manager"):
            return Response({"detail": "Import requires admin or manager role."}, status=403)
        f = request.FILES.get("file")
        if f is None:
            return Response({"detail": "file is required"}, status=400)
        if f.size > 10 * 1024 * 1024:
            return Response({"detail": "file too large (10MB max)"}, status=400)
        try:
            content = f.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return Response({"detail": "file must be UTF-8 CSV"}, status=400)
        import csv as _csv
        import io as _io

        headers = next(_csv.reader(_io.StringIO(content)), [])
        mapping = (_json.loads(request.data["mapping"])
                   if request.data.get("mapping") else importer.auto_map(headers))
        dry_run = str(request.data.get("dry_run", "true")).lower() != "false"
        report = importer.import_people_csv(
            content=content, mapping=mapping,
            strategy=request.data.get("strategy", "skip"),
            user=request.user, dry_run=dry_run,
        )
        if not dry_run:
            from crm import audit

            audit.log(actor=request.user, action="import", model_name="person",
                      detail={"total": report.total, "created": report.created,
                              "updated": report.updated, "errors": len(report.errors)},
                      request=request)
        return Response({"mapping": mapping, "dry_run": dry_run, **report.as_dict()})


class CustomFieldDefViewSet(viewsets.ModelViewSet):
    """CF-1: admin-defined fields."""

    pagination_class = None

    def get_serializer_class(self):
        from .serializers import CustomFieldDefSerializer

        return CustomFieldDefSerializer

    def get_queryset(self):
        from crm.custom_fields import CustomFieldDef

        qs = CustomFieldDef.objects.all()
        entity = self.request.query_params.get("entity")
        return qs.filter(entity=entity) if entity else qs

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.user.role != "admin":
            self.permission_denied(request, message="Only admins configure custom fields.")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """U-4: admin-searchable."""

    def get_serializer_class(self):
        from .serializers import AuditLogSerializer

        return AuditLogSerializer

    def get_queryset(self):
        from crm.audit import AuditLog

        if not self.request.user.is_admin_role:
            return AuditLog.objects.none()
        qs = AuditLog.objects.select_related("actor")
        action_f = self.request.query_params.get("action")
        return qs.filter(action=action_f) if action_f else qs


class SavedViewViewSet(viewsets.ModelViewSet):
    """S-3: private or shared-with-team views."""

    pagination_class = None

    def get_serializer_class(self):
        from .serializers import SavedViewSerializer

        return SavedViewSerializer

    def get_queryset(self):
        from django.db.models import Q as _Q

        from crm.models import SavedView

        u = self.request.user
        qs = SavedView.objects.filter(_Q(owner=u) | _Q(is_shared=True))
        entity = self.request.query_params.get("entity")
        return qs.filter(entity=entity) if entity else qs

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user, created_by=self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.owner_id != self.request.user.id \
                and not self.request.user.is_admin_role:
            self.permission_denied(self.request, message="Not your view.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.owner_id != self.request.user.id and not self.request.user.is_admin_role:
            self.permission_denied(self.request, message="Not your view.")
        instance.is_deleted = True
        instance.save(update_fields=["is_deleted", "updated_at"])


class UserViewSet(viewsets.ModelViewSet):
    """Tenant user directory + U-1 admin management + U-3 admin actions."""

    pagination_class = None
    http_method_names = ["get", "post", "patch", "head", "options"]

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method not in ("GET", "HEAD", "OPTIONS") \
                and not request.user.is_admin_role:
            self.permission_denied(request, message="Only admins manage users.")

    def create(self, request, *args, **kwargs):
        """U-1: admin creates users with role + team."""
        from .serializers import UserCreateSerializer, UserSerializer

        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from accounts.models import User

        user = User.objects.create_user(
            username=serializer.validated_data["username"],
            email=serializer.validated_data.get("email", ""),
            password=serializer.validated_data["password"],
            tenant=request.user.tenant,
            role=serializer.validated_data.get("role", "member"),
            team=serializer.validated_data.get("team"),
        )
        return Response(UserSerializer(user).data, status=201)

    def get_serializer_class(self):
        from .serializers import UserSerializer

        return UserSerializer

    def get_queryset(self):
        from accounts.models import User

        return (User.objects.filter(tenant_id=self.request.user.tenant_id)
                .select_related("team").order_by("username"))

    def _require_admin(self, request):
        if not request.user.is_admin_role:
            self.permission_denied(request, message="Admin role required.")

    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        """U-3: bulk reassign all records to another user. Audit-logged."""
        from crm import audit

        self._require_admin(request)
        source = self.get_object()
        target = get_object_or_404(self.get_queryset(), pk=request.data.get("to_user_id"))
        counts = services.transfer_records(from_user=source, to_user=target,
                                           actor=request.user)
        audit.log(actor=request.user, action="transfer", model_name="user",
                  object_id=source.id,
                  detail={"to_user": target.username, "counts": counts}, request=request)
        services.notify(user=target, kind="transfer",
                        title=f"Records transferred to you from {source.username}",
                        body=", ".join(f"{v} {k}s" for k, v in counts.items() if v),
                        tenant_id=request.user.tenant_id)
        return Response({"transferred": counts, "to_user": target.username})

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """U-3: instant deactivation — kills sessions and API tokens."""
        from crm import audit

        self._require_admin(request)
        user = self.get_object()
        if user.id == request.user.id:
            return Response({"detail": "Cannot deactivate yourself."}, status=400)
        user.deactivate()
        audit.log(actor=request.user, action="update", model_name="user",
                  object_id=user.id, detail={"deactivated": True}, request=request)
        return Response({"deactivated": user.username})


class ProductViewSet(SoftDeleteMixin, viewsets.ModelViewSet):
    """PR-1."""

    def get_serializer_class(self):
        from .serializers import ProductSerializer

        return ProductSerializer

    def get_queryset(self):
        from crm.models import Product

        qs = Product.objects.all()
        if self.request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class StageViewSet(AdminWriteMixin, viewsets.ModelViewSet):
    """D-1: admin-configurable stages (P4 persona)."""

    pagination_class = None

    def get_serializer_class(self):
        from .serializers import StageWriteSerializer

        return StageWriteSerializer

    def get_queryset(self):
        qs = Stage.objects.select_related("pipeline")
        pid = self.request.query_params.get("pipeline")
        return qs.filter(pipeline_id=pid) if pid else qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """N-1: own notifications only, unread first."""

    def get_serializer_class(self):
        from .serializers import NotificationSerializer

        return NotificationSerializer

    def get_queryset(self):
        from crm.models import Notification

        qs = Notification.objects.filter(user=self.request.user)
        if self.request.query_params.get("unread") == "1":
            qs = qs.filter(read_at__isnull=True)
        return qs.order_by("-id")

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        return Response({"count": self.get_queryset().filter(read_at__isnull=True).count()})

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        from django.utils import timezone as tz

        n = self.get_object()
        if n.read_at is None:
            n.read_at = tz.now()
            n.save(update_fields=["read_at", "updated_at"])
        return Response({"ok": True})

    @action(detail=False, methods=["post"])
    def read_all(self, request):
        from django.utils import timezone as tz

        updated = self.get_queryset().filter(read_at__isnull=True).update(read_at=tz.now())
        return Response({"marked": updated})


class EmailAccountView(APIView):
    """E-1 groundwork: connect/disconnect a mailbox. Live Gmail OAuth requires
    tenant credentials — see docs/GMAIL-SETUP.md."""

    def get(self, request):
        from crm.models import EmailAccount

        from .serializers import EmailAccountSerializer

        acct = EmailAccount.objects.filter(user=request.user).first()
        return Response(EmailAccountSerializer(acct).data if acct
                        else {"status": "not_connected"})

    def post(self, request):
        import os

        from crm.models import EmailAccount

        from .serializers import EmailAccountSerializer

        address = (request.data.get("address") or request.user.email or "").strip()
        if not address or "@" not in address:
            return Response({"detail": "A valid email address is required."}, status=400)
        acct, _created = EmailAccount.objects.update_or_create(
            user=request.user,
            defaults={"address": address, "provider": "gmail",
                      "status": EmailAccount.Status.PENDING,
                      "created_by": request.user},
        )
        oauth_ready = bool(os.environ.get("GOOGLE_OAUTH_CLIENT_ID"))
        return Response({
            **EmailAccountSerializer(acct).data,
            "next_step": ("Redirect user to Google consent screen" if oauth_ready
                          else "Server missing GOOGLE_OAUTH_CLIENT_ID/SECRET — "
                               "see docs/GMAIL-SETUP.md"),
        }, status=201)

    def delete(self, request):
        from crm.models import EmailAccount

        EmailAccount.objects.filter(user=request.user).update(
            status=EmailAccount.Status.DISABLED, oauth_credentials={})
        return Response(status=204)


class FileAttachmentViewSet(SoftDeleteMixin, viewsets.ModelViewSet):
    """Attachments; downloads are authenticated + tenant-scoped (never public media)."""

    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_serializer_class(self):
        from .serializers import FileAttachmentSerializer

        return FileAttachmentSerializer

    def get_queryset(self):
        from crm.models import FileAttachment

        qs = FileAttachment.objects.select_related("uploaded_by")
        p = self.request.query_params
        for key in ("deal", "person", "lead"):
            if p.get(key):
                qs = qs.filter(**{f"{key}_id": p[key]})
        return qs

    def create(self, request, *args, **kwargs):
        from django.conf import settings as dj

        from crm.models import FileAttachment

        from .serializers import FileAttachmentSerializer

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "file is required"}, status=400)
        if upload.size > dj.MAX_ATTACHMENT_MB * 1024 * 1024:
            return Response(
                {"detail": f"File exceeds {dj.MAX_ATTACHMENT_MB}MB limit."}, status=400)
        att = FileAttachment(
            file=upload, name=upload.name, size=upload.size,
            content_type=getattr(upload, "content_type", "") or "",
            uploaded_by=request.user, created_by=request.user,
            deal_id=request.data.get("deal") or None,
            person_id=request.data.get("person") or None,
            lead_id=request.data.get("lead") or None,
        )
        att.save()
        return Response(FileAttachmentSerializer(att).data, status=201)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        from django.http import FileResponse

        att = self.get_object()  # tenant-scoped queryset -> cross-tenant = 404
        return FileResponse(att.file.open("rb"), as_attachment=True, filename=att.name)


class WebhookSubscriptionViewSet(AdminWriteMixin, viewsets.ModelViewSet):
    """§7 integration hooks (admin-configured; reads also admin-only)."""

    pagination_class = None

    def get_serializer_class(self):
        from .serializers import WebhookSubscriptionSerializer

        return WebhookSubscriptionSerializer

    def get_queryset(self):
        from crm.models import WebhookSubscription

        if not self.request.user.is_admin_role:
            return WebhookSubscription.objects.none()
        return WebhookSubscription.objects.all()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AutomationRuleViewSet(AdminWriteMixin, viewsets.ModelViewSet):
    """AU-1: rule CRUD (admins configure; managers/members can read)."""

    pagination_class = None

    def get_serializer_class(self):
        from .serializers import AutomationRuleSerializer

        return AutomationRuleSerializer

    def get_queryset(self):
        from crm.automation import AutomationRule

        return AutomationRule.objects.select_related("pipeline")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["get"])
    def runs(self, request, pk=None):
        from .serializers import AutomationRunSerializer

        rule = self.get_object()
        runs = rule.runs.order_by("-id")[:25]
        return Response(AutomationRunSerializer(runs, many=True).data)


class AutomationRunViewSet(viewsets.ReadOnlyModelViewSet):
    """AU-2: execution log (admin/manager)."""

    def get_queryset(self):
        from crm.automation import AutomationRun

        if self.request.user.role not in ("admin", "manager"):
            return AutomationRun.objects.none()
        return AutomationRun.objects.select_related("rule").order_by("-id")

    def get_serializer_class(self):
        from .serializers import AutomationRunSerializer

        return AutomationRunSerializer


class ReportsView(APIView):
    """R-2..R-5, visibility-scoped. ?days=90&pipeline=<id> where applicable."""

    def get(self, request, section: str):
        from crm import reports

        days = int(request.query_params.get("days", 90))
        if section == "funnel":
            pipeline = get_object_or_404(Pipeline,
                                         pk=request.query_params.get("pipeline"))
            return Response(reports.funnel(pipeline, request.user, days))
        if section == "activity":
            return Response(reports.activity_report(request.user, days))
        if section == "won-lost":
            return Response(reports.won_lost(request.user, days))
        if section == "sources":
            return Response(reports.source_roi(request.user, days))
        return Response({"detail": "Unknown report."}, status=404)
