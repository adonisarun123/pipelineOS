"""Mandatory tenant-scoped manager (spec §7).

`Model.objects` on tenant models ALWAYS filters by the current tenant and
excludes soft-deleted rows. With no tenant in context it fails closed.
The unscoped manager is `Model.unscoped` — its use outside the `tenants`
package, seeds, and migrations is forbidden and enforced by a test.
"""
from django.db import models

from .context import TenantContextError, get_current_tenant_id


class TenantManager(models.Manager):
    use_in_migrations = False

    def get_queryset(self) -> models.QuerySet:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise TenantContextError(
                f"Attempted tenant-scoped access to {self.model.__name__} "
                "with no tenant in context. Use tenant_context() or authenticate."
            )
        return super().get_queryset().filter(tenant_id=tenant_id, is_deleted=False)
