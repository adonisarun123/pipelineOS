"""AU-2: Celery app. Active only when CELERY_BROKER_URL is set (Redis on
Railway/Render); everything degrades to synchronous in-process execution
without it, so a broker outage or a broker-less dev box never blocks sales.

Worker:  celery -A config worker -l info
Beat:    celery -A config beat -l info   (digest 08:00 IST, time triggers */15)
"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

try:
    from celery import Celery

    app = Celery("pipelineos")
    app.config_from_object("django.conf:settings", namespace="CELERY")
    app.autodiscover_tasks()

    app.conf.beat_schedule = {
        "daily-digest": {"task": "crm.tasks.send_digest_task",
                         "schedule": 60 * 60 * 24},  # refine with crontab() in prod
        "time-triggers": {"task": "crm.tasks.time_automations_task",
                          "schedule": 60 * 15},
    }
except ImportError:  # celery not installed — sync mode only
    app = None
