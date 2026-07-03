from django.contrib.auth.models import AbstractUser
from django.db import models

from tenants.models import Tenant, TenantModel


class Team(TenantModel):
    """U-2: users belong to one primary team; managers see team records."""

    name = models.CharField(max_length=100)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_team_name_per_tenant")
        ]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """U-1 roles. NOT tenant-manager-scoped: auth must resolve users before a
    tenant exists in context. API views filter users by tenant explicitly."""

    class Role(models.TextChoices):
        ADMIN = "admin"
        MANAGER = "manager"
        MEMBER = "member"
        READONLY = "readonly"

    tenant = models.ForeignKey(
        Tenant, null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    team = models.ForeignKey(
        Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="members"
    )
    phone = models.CharField(max_length=20, blank=True)

    @property
    def is_admin_role(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_manager_role(self) -> bool:
        return self.role == self.Role.MANAGER

    def deactivate(self) -> None:
        """U-3: instant deactivation kills sessions and API tokens."""
        from rest_framework.authtoken.models import Token

        self.is_active = False
        self.save(update_fields=["is_active"])
        Token.objects.filter(user=self).delete()
