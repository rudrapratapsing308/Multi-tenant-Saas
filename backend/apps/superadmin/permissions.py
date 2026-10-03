"""
Platform (super admin) permissions.

Everything in this app deliberately IGNORES ``request.tenant``: the platform
owner oversees every store, so their endpoints are tenant-exempt in the
middleware (``/api/v1/superadmin/`` in ``TENANT_EXEMPT_PATH_PREFIXES``) and
scoped by *role*, not by host.
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission


class IsSuperAdmin(BasePermission):
    """
    Strict platform gate: the user's role must be SUPER_ADMIN.

    Note this is intentionally role-only - not ``is_staff``/``is_superuser``
    and not "any authenticated user with a membership". Platform accounts
    cannot be created through self-registration (the register serializer
    only offers customer/vendor), so this list is operator-controlled.
    """

    message = "Platform access only."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_super_admin)
