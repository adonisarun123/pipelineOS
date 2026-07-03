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


class PipelineViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PipelineSerializer

    def get_queryset(self):
        return Pipeline.objects.prefetch_related("stages")

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


class DealViewSet(viewsets.ModelViewSet):
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

    @action(detail=True, methods=["post"])
    def set_custom(self, request, pk=None):
        """CF-3: set custom field values {key: value}; null clears."""
        from crm import custom_fields

        deal = self.get_object()
        cache = custom_fields.set_custom_values(deal, "deal", dict(request.data), request.user)
        return Response({"custom": cache})

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
        services.change_stage(deal, stage, request.user)
        return Response(DealSerializer(deal).data)

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


class ActivityViewSet(viewsets.ModelViewSet):
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


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        qs = Organization.objects.all()
        q = self.request.query_params.get("q")
        return qs.filter(name__icontains=q) if q else qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PersonViewSet(viewsets.ModelViewSet):
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

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """C-4 for people."""
        from .serializers import PersonDetailSerializer

        person = self.get_object()
        events = services.person_timeline(person)
        for e in events:
            e["at"] = e["at"].isoformat() if e["at"] else None
        return Response({"person": PersonDetailSerializer(person).data, "events": events})


class LostReasonViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LostReasonSerializer
    pagination_class = None

    def get_queryset(self):
        return LostReason.objects.all()


class LeadViewSet(viewsets.ModelViewSet):
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
        serializer.save(created_by=self.request.user,
                        owner=serializer.validated_data.get("owner") or self.request.user)

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
        return Response(self.get_serializer(lead).data)


class LeadSourceViewSet(viewsets.ReadOnlyModelViewSet):
    pagination_class = None

    def get_serializer_class(self):
        from rest_framework import serializers as s

        from crm.leads import LeadSource

        class LeadSourceSerializer(s.ModelSerializer):
            class Meta:
                model = LeadSource
                fields = ["id", "name"]

        return LeadSourceSerializer

    def get_queryset(self):
        from crm.leads import LeadSource

        return LeadSource.objects.all()


class ActivityTypeViewSet(viewsets.ReadOnlyModelViewSet):
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


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """Tenant user directory + U-3 admin actions."""

    pagination_class = None

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
