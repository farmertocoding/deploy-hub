from rest_framework.permissions import BasePermission

from core.rbac import has_capability, request_workspace


class RequireAdminRead(BasePermission):
    message = "Administration read capability required."

    def has_permission(self, request, view):
        user = request.user
        workspace = request_workspace(request)
        return bool(
            user and user.is_authenticated and workspace
            and has_capability(user, "admin_read", workspace)
        )
