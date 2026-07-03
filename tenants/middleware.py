from .context import reset, set_current_tenant_id


class TenantContextMiddleware:
    """Guarantees a clean tenant context per request (WSGI threads are reused).

    The tenant itself is set by api.auth.TenantTokenAuthentication after the
    user is identified; this middleware only isolates and cleans up.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_current_tenant_id(None)
        try:
            return self.get_response(request)
        finally:
            reset(token)
