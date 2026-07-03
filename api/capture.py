"""L-7: unauthenticated per-source lead capture (Asha chatbot, webforms, ads).

This is the one endpoint that legitimately resolves a tenant from request data
instead of an auth token: the source token IS the credential. The unscoped
manager use below is deliberate and reviewed (allowlisted in
tests/test_no_raw_manager.py with this justification).
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from crm import services
from crm.leads import LeadSource
from tenants.context import tenant_context


class CaptureThrottle(AnonRateThrottle):
    rate = "60/min"  # per-IP; per-tenant rate limits arrive with Phase 3 metering


class LeadCaptureView(APIView):
    authentication_classes = []  # token in URL is the credential
    permission_classes = [AllowAny]
    throttle_classes = [CaptureThrottle]

    def post(self, request, token: str):
        if not token or len(token) < 16:
            return Response({"detail": "Not found."}, status=404)
        source = (LeadSource.unscoped  # deliberate: cross-tenant token resolution
                  .filter(token=token, is_deleted=False)
                  .select_related("tenant").first())
        if source is None or not source.tenant.is_active:
            return Response({"detail": "Not found."}, status=404)
        if not isinstance(request.data, dict) or len(str(request.data)) > 10000:
            return Response({"detail": "Invalid payload."}, status=400)
        with tenant_context(source.tenant_id):
            try:
                lead = services.capture_lead(source=source, payload=dict(request.data))
            except DjangoValidationError as exc:
                return Response({"detail": exc.messages}, status=400)
        return Response({"id": lead.pk, "status": "created"}, status=201)
