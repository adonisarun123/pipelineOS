from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import User


class RoleWritePermission(BasePermission):
    """U-1: ReadOnly role cannot mutate."""

    message = "Your role does not permit write operations."

    def has_permission(self, request, view) -> bool:
        from .api_key_auth import ApiKeyScopePermission

        if not ApiKeyScopePermission.allows(request):
            self.message = "This API key is read-only."
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_authenticated and request.user.role != User.Role.READONLY
