"""Time-based triggers (AU-1): deal.stage_idle and activity.overdue.

Schedule every 15–30 min via cron, or Celery beat once a broker is deployed.
Emits synthetic events through the same engine as real-time triggers; computed
values (days_idle, hours_overdue) ride in payload._attrs for rule conditions.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from crm import events
from crm.automation import AutomationRule
from crm.leads import Lead
from crm.models import Activity, Deal
from crm.services import lead_is_sla_overdue, notify
from tenants.context import tenant_context
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Evaluate time-based automation triggers + L-8 SLA flags."

    def handle(self, *args, **options):
        fired = 0
        now = timezone.now()
        for tenant in Tenant.objects.filter(is_active=True):
            with tenant_context(tenant.id):
                if AutomationRule.objects.filter(trigger="deal.stage_idle",
                                                 is_active=True).exists():
                    for deal in Deal.objects.filter(status="open").select_related("stage"):
                        days = (now - deal.stage_entered_at).days
                        if days < 1:
                            continue
                        events.emit("deal.stage_idle",
                                    {"id": deal.pk, "title": deal.title,
                                     "_attrs": {"days_idle": days}}, tenant.id)
                        fired += 1
                if AutomationRule.objects.filter(trigger="activity.overdue",
                                                 is_active=True).exists():
                    overdue = Activity.objects.filter(done=False, due_at__lt=now)
                    for act in overdue:
                        hours = int((now - act.due_at).total_seconds() // 3600)
                        events.emit("activity.overdue",
                                    {"id": act.pk, "subject": act.subject,
                                     "_attrs": {"hours_overdue": hours}}, tenant.id)
                        fired += 1
                # L-8: SLA-overdue leads → notify owner (independent of rules)
                for lead in Lead.objects.filter(status="new",
                                                first_response_at__isnull=True,
                                                source__sla_minutes__isnull=False):
                    if lead_is_sla_overdue(lead) and lead.owner_id:
                        already = lead.owner.notifications.filter(
                            kind="overdue", link_entity="lead", link_id=lead.pk).exists()
                        if not already:
                            notify(user=lead.owner, kind="overdue",
                                   title=f"SLA breached: lead '{lead.name}' awaiting first response",
                                   link_entity="lead", link_id=lead.pk,
                                   tenant_id=tenant.id)
                            fired += 1
        self.stdout.write(self.style.SUCCESS(f"Fired {fired} time-based event(s)."))
