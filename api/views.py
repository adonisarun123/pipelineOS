from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.response import Response

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
        return services.annotate_flags(
            services.visible_deals(self.request.user)
            .select_related("stage", "organization", "owner")
        )

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
    def move(self, request, pk=None):
        deal = self.get_object()
        stage = get_object_or_404(Stage, pk=request.data.get("stage_id"))
        services.change_stage(deal, stage, request.user)
        return Response(DealSerializer(deal).data)

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
        return Organization.objects.all()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PersonViewSet(viewsets.ModelViewSet):
    serializer_class = PersonSerializer

    def get_queryset(self):
        return Person.objects.all()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class LostReasonViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LostReasonSerializer
    pagination_class = None

    def get_queryset(self):
        return LostReason.objects.all()
