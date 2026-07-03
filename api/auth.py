from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed

from tenants.context import set_current_tenant_id


class TenantTokenAuthentication(TokenAuthentication):
    """Token auth that binds the request to the user's tenant (spec §7)."""

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if user.tenant_id is None:
            raise AuthenticationFailed("User has no tenant.")
        if not user.tenant.is_active:
            raise AuthenticationFailed("Tenant is inactive.")
        set_current_tenant_id(user.tenant_id)
        return user, token


__all__ = ["TenantTokenAuthentication", "Token"]
