"""Per-request tenant context (contextvars: safe for threads and async)."""
import contextvars
from contextlib import contextmanager

_current_tenant_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_tenant_id", default=None
)


class TenantContextError(Exception):
    """Raised when tenant-scoped data is accessed with no tenant in context."""


def set_current_tenant_id(tenant_id: int | None) -> contextvars.Token:
    return _current_tenant_id.set(tenant_id)


def get_current_tenant_id() -> int | None:
    return _current_tenant_id.get()


def reset(token: contextvars.Token) -> None:
    _current_tenant_id.reset(token)


@contextmanager
def tenant_context(tenant_id: int):
    """Scope a block to one tenant (tests, Celery tasks, seeds)."""
    token = set_current_tenant_id(tenant_id)
    try:
        yield
    finally:
        reset(token)
