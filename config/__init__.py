try:
    from .celery import app as celery_app  # noqa: F401
except Exception:  # celery optional in dev
    celery_app = None
