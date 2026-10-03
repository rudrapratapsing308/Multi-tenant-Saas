"""
DRF permission classes for the three roles.

The *model layer* of isolation (TenantQuerySet.for_tenant) lives in
``apps.tenants.permissions``; these classes answer "is this user allowed to
reach this view at all?". Query scoping still happens in get_queryset() -
permission alone never guarantees tenant isolation.
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission

from .models import BusinessMembership


class IsCustomer(BasePermission):
    """Authenticated user with the Customer role (reviews, checkout, cart)."""

    message = "Customer accounts only."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_customer)


class IsVendorForTenant(BasePermission):
    """
    Vendor role AND an active membership on the CURRENT tenant.

    Mounted under /api/v1/vendor/..., so the middleware has already turned the
    Host header into ``request.tenant``. A vendor of store A presenting their
    token against store B fails the membership test here - before any queryset
    is built - which is the human half of tenant isolation.
    """

    message = "You do not manage this store."

    def has_permission(self, request, view) -> bool:
        user = request.user
        tenant = getattr(request, "tenant", None)
        if not (user and user.is_authenticated and user.is_vendor and tenant is not None):
            return False
        return BusinessMembership.objects.filter(
            user=user, business=tenant, is_active=True
        ).exists()
