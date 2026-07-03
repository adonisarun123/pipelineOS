"""N-3: morning digest — today's activities, overdue items, new leads.

Run via cron (Phase 1) or Celery beat (Phase 2):  0 8 * * *  manage.py send_daily_digest
Email backend: console in dev; set EMAIL_HOST/PORT/USER/PASSWORD env for SMTP.
"""
from datetime import timedelta

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from crm import services
from crm.leads import Lead
from tenants.context import tenant_context
from tenants.models import Tenant


def build_digest(user: User) -> str | None:
    """Returns plaintext digest body, or None if there is nothing to say."""
    buckets = services.my_activity_buckets(user)
    yesterday = timezone.now() - timedelta(days=1)
    new_leads = Lead.objects.filter(owner=user, status="new",
                                    created_at__gte=yesterday)
    if not (buckets["today"] or buckets["overdue"] or new_leads.exists()):
        return None
    lines = [f"Good morning {user.username} — your PipelineOS digest:", ""]
    if buckets["overdue"]:
        lines.append(f"⚠ OVERDUE ({len(buckets['overdue'])}):")
        lines += [f"  - {a.type.name}: {a.subject}"
                  + (f" [{a.deal.title}]" if a.deal else "") for a in buckets["overdue"]]
        lines.append("")
    if buckets["today"]:
        lines.append(f"TODAY ({len(buckets['today'])}):")
        lines += [f"  - {a.due_at.astimezone().strftime('%H:%M')} {a.type.name}: "
                  f"{a.subject}" for a in buckets["today"]]
        lines.append("")
    if new_leads.exists():
        lines.append(f"NEW LEADS ({new_leads.count()}):")
        lines += [f"  - {lead.name} ({lead.source.name if lead.source else 'unknown'})"
                  for lead in new_leads]
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Send the morning email digest to every active user (N-3)."

    def handle(self, *args, **options):
        sent = 0
        for tenant in Tenant.objects.filter(is_active=True):
            with tenant_context(tenant.id):
                users = User.objects.filter(tenant=tenant, is_active=True).exclude(email="")
                for user in users:
                    body = build_digest(user)
                    if body is None:
                        continue
                    send_mail(
                        subject=f"PipelineOS digest — {timezone.localdate():%d %b}",
                        message=body,
                        from_email=None,  # DEFAULT_FROM_EMAIL
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                    sent += 1
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} digest(s)."))
