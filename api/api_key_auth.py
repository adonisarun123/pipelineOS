"""API-1: Authorization: Api-Key pk_live_... auth + per-tenant throttling.

Key lookup is by unique global hash, which resolves the tenant — the second
sanctioned cross-tenant lookup (allowlisted in tests/test_no_raw_manager.py):
like capture tokens, the key IS the credential that identifies the tenant.
"""
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.throttling import SimpleRateThrottle

from crm.api_keys import KEY_PREFIX, ApiKey
from tenants.context import set_current_tenant_id


class ApiKeyAuthentication(BaseAuthentication):
    keyword = b"api-key"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != self.keyword:
            return None
        if len(auth) != 2:
            raise AuthenticationFailed("Invalid Api-Key header.")
        raw = auth[1].decode()
        if not raw.startswith(KEY_PREFIX):
            raise AuthenticationFailed("Invalid API key.")
        key = (ApiKey.unscoped  # deliberate: key hash resolves the tenant
               .filter(key_hash=ApiKey.hash_key(raw), is_active=True, is_deleted=False)
               .select_related("acting_user", "tenant").first())
        if key is None or not key.tenant.is_active or not key.acting_user.is_active:
            raise AuthenticationFailed("Invalid or revoked API key.")
        set_current_tenant_id(key.tenant_id)
        ApiKey.unscoped.filter(pk=key.pk).update(last_used_at=timezone.now())
        request.api_key = key
        return key.acting_user, key

    def authenticate_header(self, request):
        return "Api-Key"


class ApiKeyScopePermission:
    """Deny writes for read-scoped keys. Combined into RoleWritePermission chain."""

    @staticmethod
    def allows(request) -> bool:
        key = getattr(request, "api_key", None)
        if key is None:
            return True  # session/token auth — role permissions apply as usual
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return key.scope == ApiKey.Scope.WRITE


class TenantRateThrottle(SimpleRateThrottle):
    """API-1: per-tenant limits on API-key traffic (UI traffic unaffected)."""

    scope = "tenant_api"
    rate = "600/hour"

    def get_cache_key(self, request, view):
        key = getattr(request, "api_key", None)
        if key is None:
            return None  # throttle only API-key requests
        return f"throttle_tenant_api_{key.tenant_id}"
