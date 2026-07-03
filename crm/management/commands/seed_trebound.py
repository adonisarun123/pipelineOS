"""Seed the Trebound pilot tenant (spec §12.1) with demo data for smoke testing."""
import os
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Team, User
from crm import services
from crm.custom_fields import CustomFieldDef
from crm.leads import Lead, LeadSource
from crm.models import (
    Activity,
    ActivityType,
    LostReason,
    Organization,
    Pipeline,
    Product,
    Stage,
)
from tenants.context import tenant_context
from tenants.models import Tenant

STAGES = [  # name, rot_days, probability
    ("Qualified", 7, 10),
    ("Contact Made", 7, 25),
    ("Proposal Sent", 5, 50),
    ("Negotiation", 5, 75),
    ("Booking Confirmed", None, 95),
]
PIPELINES = ["Corporate Events IN", "International", "Kids' Outbound"]
ACTIVITY_TYPES = ["Call", "Meeting", "Task", "Deadline", "WhatsApp follow-up", "Site visit"]
LOST_REASONS = ["Budget", "Not a fit", "Competitor", "Unresponsive", "Junk", "Date conflict"]


class Command(BaseCommand):
    help = "Seed Trebound tenant, users, pipelines, and demo deals."

    def handle(self, *args, **options):
        tenant, created = Tenant.objects.get_or_create(
            subdomain="trebound", defaults={"name": "Trebound"}
        )
        if not created:
            self.stdout.write("Tenant exists; skipping (idempotent).")
            return

        with tenant_context(tenant.id):
            team = Team(name="Corporate Sales")
            team.save()
            pw = os.environ.get("SEED_PASSWORD", "trebound@2026!")
            users = {}
            for uname, role in [("admin", "admin"), ("manager", "manager"),
                                ("rep1", "member"), ("rep2", "member")]:
                u = User.objects.create_user(
                    username=uname, password=pw, email=f"{uname}@trebound.example",
                    tenant=tenant, role=role, team=team,
                )
                users[uname] = u

            for label in LOST_REASONS:
                LostReason(label=label).save()
            types = {}
            for name in ACTIVITY_TYPES:
                t = ActivityType(name=name)
                t.save()
                types[name] = t

            pipelines = []
            for p_order, p_name in enumerate(PIPELINES):
                p = Pipeline(name=p_name, order=p_order)
                p.save()
                for order, (name, rot, prob) in enumerate(STAGES):
                    Stage(pipeline=p, name=name, order=order, rot_days=rot, probability=prob).save()
                pipelines.append(p)

            # Demo deals in the main pipeline
            main = pipelines[0]
            stages = list(main.stages.all())
            demo = [
                ("Infosys offsite — Coorg", 450000, "rep1", 0),
                ("Wipro leadership retreat", 800000, "rep1", 2),
                ("Zerodha annual day", 1200000, "rep2", 1),
                ("Freshworks team day", 300000, "rep2", 3),
            ]
            now = timezone.now()
            for title, value, rep, stage_idx in demo:
                org = Organization(name=title.split(" ")[0], owner=users[rep])
                org.save()
                deal = services.create_deal(
                    user=users[rep], title=title, pipeline=main,
                    stage=stages[stage_idx], value=value, organization=org,
                )
                Activity(
                    type=types["Call"], subject=f"Follow up: {title}",
                    due_at=now + timedelta(days=2), owner=users[rep], deal=deal,
                ).save()
            # One rotten deal: entered stage 10 days ago, no activity
            rotten = services.create_deal(
                user=users["rep1"], title="TCS hackathon event (stale)",
                pipeline=main, stage=stages[1], value=250000,
            )
            rotten.stage_entered_at = now - timedelta(days=10)
            rotten.save(update_fields=["stage_entered_at"])

            # Product catalogue (PR-1)
            for pname, cat, price in [
                ("Outbound Team Building — Full Day", "Outbound", 2500),
                ("Indoor Team Games — Half Day", "Indoor", 1200),
                ("Leadership Workshop", "Workshop", 4000),
                ("Resort Venue — Coorg (per head)", "Venue", 3500),
                ("Transport — AC Coach (per bus)", "Logistics", 15000),
            ]:
                Product(name=pname, category=cat, unit_price=price).save()

            # Custom fields (CF-2 example: "Event Date" is important for Trebound)
            for order, (name, key, ftype, opts, imp, nudge) in enumerate([
                ("Event Date", "event_date", "date", [], True, 2),   # nudge at Proposal Sent
                ("Headcount", "headcount", "number", [], True, 2),
                ("Venue Type", "venue_type", "single_select",
                 ["Resort", "Office", "Outdoor", "Virtual"], False, None),
                ("Advance Received", "advance_received", "checkbox", [], False, None),
            ]):
                CustomFieldDef(entity="deal", name=name, key=key, field_type=ftype,
                               options=opts, is_important=imp, order=order,
                               nudge_stage_order=nudge).save()

            # Lead sources + demo leads (L-1/L-2)
            sources = {}
            for s in ["Website", "Chatbot", "Referral", "IndiaMART", "Google Ads", "WhatsApp"]:
                src = LeadSource(name=s)
                src.save()
                sources[s] = src
            for lname, lorg, lphone, lsrc, lowner in [
                ("Priya Sharma", "Razorpay", "98450 11223", "Website", "rep1"),
                ("Amit Verma", "Swiggy", "99000 55667", "Chatbot", "rep2"),
                ("Neha Gupta", "", "97411 88990", "WhatsApp", "rep1"),
            ]:
                lead = Lead(name=lname, organization_name=lorg, phone_raw=lphone,
                            phone_normalized=services.normalize_phone(lphone),
                            source=sources[lsrc], owner=users[lowner],
                            note="Inbound enquiry — corporate offsite")
                lead.save()

        self.stdout.write(self.style.SUCCESS(
            f"Seeded tenant 'trebound' (id={tenant.id}); users admin/manager/rep1/rep2; "
            "password from SEED_PASSWORD env (default trebound@2026!)."
        ))
