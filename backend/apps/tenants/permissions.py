"""
Strict per-tenant data isolation primitives.

Multi-tenancy strategy: **shared tables, discriminator column**. Every
tenant-owned row carries ``business_id``; this module makes that column
impossible to ignore:

    TenantQuerySet.for_tenant(tenant)      -> WHERE business_id = <tenant pk>
    BusinessScopedModel                    -> abstract base that declares the
                                              business FK *and* the manager
    require_tenant(request)                -> helper for views: fail loudly
                                              instead of silently querying
                                              every tenant's data

    # usage inside a view (next modules)
    qs = Product.objects.for_tenant(request.tenant).filter(is_active=True)

The manager never *hides* rows by itself - that would need request state
inside the ORM - so the contract is: **any queryset that leaves the view must
have gone through ``for_tenant``**. ``require_tenant()`` + the middleware's
JSON 404 guarantee there is always a tenant to scope against.

DRF permission classes (authentication/authorization) are layered on top in
the auth module; this file is the *model layer* of the same isolation story.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import models

from apps.core.models import TimeStampedModel

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids circular imports
    from apps.tenants.models import Business


class TenantRequiredError(Exception):
    """Raised when a view runs without a resolved tenant (defence in depth)."""


class TenantQuerySet(models.QuerySet):
    """QuerySet that can be narrowed to exactly one business."""

    def for_tenant(self, tenant: "Business | None") -> "TenantQuerySet":
        """
        Scope every subsequent filter to one business.

        A missing tenant returns an EMPTY queryset instead of everything:
        widening the scope is a data-leak, narrowing it is a bug report.
        """
        if tenant is None:
            return self.none()
        return self.filter(business_id=_tenant_pk(tenant))

    def create_for_tenant(self, tenant: "Business | None", **kwargs: Any):
        """Create a row that is guaranteed to belong to ``tenant``."""
        if tenant is None:
            raise TenantRequiredError(
                "Refusing to create a tenant-owned row without a business."
            )
        pk = _tenant_pk(tenant)
        if kwargs.get("business_id") not in (None, pk):
            raise TenantRequiredError(
                "business_id does not match the tenant this row is created for."
            )
        return self.create(business_id=pk, **kwargs)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Default manager for tenant-owned models (``objects.for_tenant(...)``)."""


def _tenant_pk(tenant: "Business | None") -> Any:
    """Accept a Business instance or a raw pk; refuse anything else."""
    if isinstance(tenant, models.Model):
        return tenant.pk
    return tenant


class BusinessScopedModel(TimeStampedModel):
    """
    Abstract base for every row that belongs to exactly one store.

    Declares the discriminator FK plus the scoping manager (and inherits the
    created_at/updated_at audit columns), so a model gets isolation for free::

        class Product(BusinessScopedModel):
            name = models.CharField(max_length=200)

        Product.objects.for_tenant(request.tenant)      # only this store
        Product.objects.create_for_tenant(tenant, ...)  # always tagged

    Related names are generated as ``%(class)ss`` (business.products,
    business.reviews, business.discountcodes, ...).
    """

    business = models.ForeignKey(
        "tenants.Business",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        help_text="Owning store - every query must be scoped by this column.",
    )

    objects = TenantManager()

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{type(self).__name__} #{self.pk}"


def require_tenant(request) -> "Business":
    """
    Return ``request.tenant`` or raise :class:`TenantRequiredError`.

    The middleware already answers unknown hosts with a JSON 404 on every
    non-exempt path, so hitting this in a view means the endpoint was mounted
    on an exempt path *and* forgot to handle the platform/host-less case.
    """
    tenant = getattr(request, "tenant", None)
    if tenant is None:
        raise TenantRequiredError(
            f"No tenant resolved for this request "
            f"(host={getattr(request, 'tenant_host', None)!r}). "
            f"Endpoint must either be tenant-aware or use require_tenant()."
        )
    return tenant
