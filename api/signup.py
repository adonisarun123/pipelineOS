"""Phase 3: self-serve tenant signup + billing scaffold.

Signup is the third sanctioned tenant-boundary crossing (allowlisted): it CREATES
the tenant. Razorpay checkout activates once RAZORPAY_* env vars exist; the
webhook below verifies signatures and flips plans either way.
"""
import hashlib
import hmac
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from tenants.context import tenant_context
from tenants.models import PLANS, Tenant

GENERIC_STAGES = [("Qualified", 7, 10), ("Contacted", 7, 30),
                  ("Proposal", 5, 60), ("Won-ready", None, 90)]


class SignupThrottle(AnonRateThrottle):
    rate = "10/hour"


class SignupView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [SignupThrottle]

    @transaction.atomic
    def post(self, request):
        from datetime import timedelta

        from accounts.models import Team, User
        from crm.models import ActivityType, LostReason, Pipeline, Stage

        d = request.data
        required = ["company", "subdomain", "username", "email", "password"]
        missing = [f for f in required if not str(d.get(f, "")).strip()]
        if missing:
            return Response({"detail": f"Missing: {', '.join(missing)}"}, status=400)
        subdomain = str(d["subdomain"]).strip().lower()
        if not subdomain.replace("-", "").isalnum() or len(subdomain) < 3:
            return Response({"detail": "Subdomain: letters/digits/hyphens, min 3."},
                            status=400)
        if Tenant.objects.filter(subdomain=subdomain).exists():
            return Response({"detail": "Subdomain is taken."}, status=409)
        try:
            validate_password(str(d["password"]))
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=400)
        if User.objects.filter(username=d["username"]).exists():
            return Response({"detail": "Username is taken."}, status=409)

        tenant = Tenant.objects.create(
            name=str(d["company"])[:200], subdomain=subdomain, plan="trial",
            trial_ends_at=timezone.now() + timedelta(days=PLANS["trial"]["trial_days"]),
        )
        with tenant_context(tenant.id):
            team = Team(name="Sales")
            team.save()
            admin = User.objects.create_user(
                username=d["username"], email=d["email"], password=d["password"],
                tenant=tenant, role="admin", team=team)
            pipeline = Pipeline(name="Sales Pipeline", created_by=admin)
            pipeline.save()
            for order, (name, rot, prob) in enumerate(GENERIC_STAGES):
                Stage(pipeline=pipeline, name=name, order=order, rot_days=rot,
                      probability=prob, created_by=admin).save()
            for name in ["Call", "Meeting", "Task", "WhatsApp follow-up"]:
                ActivityType(name=name, created_by=admin).save()
            for label in ["Budget", "Not a fit", "Competitor", "Unresponsive"]:
                LostReason(label=label, created_by=admin).save()
        token, _ = Token.objects.get_or_create(user=admin)
        return Response({"tenant": subdomain, "token": token.key,
                         "user_id": admin.id, "username": admin.username,
                         "role": "admin",
                         "trial_ends_at": tenant.trial_ends_at}, status=201)


class BillingUsageView(APIView):
    def get(self, request):
        from accounts.models import User
        from crm.leads import Lead
        from crm.models import Deal, FileAttachment

        tenant = request.user.tenant
        seats_used = User.objects.filter(tenant=tenant, is_active=True).count()
        storage = sum(FileAttachment.objects.values_list("size", flat=True))
        return Response({
            "plan": tenant.plan,
            "seats_used": seats_used,
            "seats_limit": tenant.seats_limit,
            "trial_ends_at": tenant.trial_ends_at,
            "writable": tenant.is_writable,
            "deals": Deal.objects.count(),
            "leads": Lead.objects.count(),
            "storage_bytes": storage,
            "price_inr_month": PLANS[tenant.plan]["price_inr"],
            "razorpay_configured": bool(os.environ.get("RAZORPAY_KEY_ID")),
        })


class RazorpayWebhookView(APIView):
    """Signature-verified plan activation. Configure the webhook secret in env."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
        if not secret:
            return Response({"detail": "Billing not configured."}, status=503)
        signature = request.headers.get("X-Razorpay-Signature", "")
        expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return Response({"detail": "Bad signature."}, status=400)
        payload = request.data
        event = payload.get("event")
        notes = (payload.get("payload", {}).get("subscription", {})
                 .get("entity", {}).get("notes", {}))
        subdomain = notes.get("tenant")
        plan = notes.get("plan")
        if event == "subscription.charged" and subdomain and plan in PLANS:
            updated = Tenant.objects.filter(subdomain=subdomain).update(
                plan=plan, trial_ends_at=None)
            return Response({"activated": bool(updated), "plan": plan})
        return Response({"ignored": event})
