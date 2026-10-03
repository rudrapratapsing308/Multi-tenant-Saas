"""
Super admin (platform) API.

    GET   /api/v1/superadmin/businesses/            all stores + revenue metrics
    PATCH /api/v1/superadmin/businesses/<id>/status/ activate / suspend / block
    GET   /api/v1/superadmin/users/                 every user and their role
    PATCH /api/v1/superadmin/users/<id>/            flag (audit) or ban (is_active)

Isolation flips here: the platform sees EVERY tenant, so ``IsSuperAdmin``
replaces ``request.tenant`` scoping entirely - the middleware treats
``/api/v1/superadmin/`` as tenant-exempt. Everything else (vendor endpoints)
remains as strict as before; this app never weakens those rules, it simply
operates above them.

Status changes flow straight into the Module-3 middleware: flipping a
business to SUSPENDED/BLOCKED makes its storefront and API return 403
``store_unavailable`` on the next request.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import mixins
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.models import User
from apps.orders.models import Order
from apps.tenants.models import Business

from .permissions import IsSuperAdmin
from .serializers import (
    BusinessSerializer,
    BusinessStatusSerializer,
    PlatformUserSerializer,
)

# One aggregate pass over all businesses: revenue excludes cancelled orders,
# customer_count counts distinct buyers. All three expressions traverse the
# SAME single relation (orders), so they share one join - no fan-out.
STORE_METRICS = dict(
    revenue=Coalesce(
        Sum(
            "orders__total",
            filter=~Q(orders__status=Order.Status.CANCELLED),
        ),
        Value(Decimal("0.00")),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    ),
    order_count=Count(
        "orders", filter=~Q(orders__status=Order.Status.CANCELLED)
    ),
    customer_count=Count(
        "orders__customer",
        distinct=True,
        filter=~Q(orders__status=Order.Status.CANCELLED),
    ),
)


class BusinessViewSet(mixins.ListModelMixin, GenericViewSet):
    """Platform-wide business list with per-store revenue metrics."""

    serializer_class = BusinessSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        queryset = (
            Business.objects.annotate(**STORE_METRICS)
            .select_related("owner")
            .prefetch_related("domains")
            .order_by("name")
        )
        status_param = self.request.query_params.get("status")
        if status_param:
            valid = {value for value, _ in Business.Status.choices}
            if status_param not in valid:
                raise ValidationError(
                    {"status": f"Must be one of: {', '.join(sorted(valid))}."}
                )
            queryset = queryset.filter(status=status_param)
        return queryset

    @action(detail=True, methods=["patch"], url_path="status")
    def status(self, request, pk=None):
        """
        Activate / suspend / block a store.

        This is the switch that feeds ``RequestTenantMiddleware``: any status
        other than ACTIVE makes the whole storefront answer 403
        ``store_unavailable`` (and 404 for unknown hosts is unrelated - hosts
        are looked up independently of status).
        """
        business = self.get_object()
        serializer = BusinessStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        business.status = serializer.validated_data["status"]
        business.save(update_fields=["status", "updated_at"])
        return Response(BusinessSerializer(business).data)


class PlatformUserViewSet(
    mixins.ListModelMixin, mixins.UpdateModelMixin, GenericViewSet
):
    """
    Global user list + moderation.

    Only GET and PATCH are wired (no PUT/DELETE): banning is ``is_active=false``
    and flagging is an *audited* mark, never a deletion.
    """

    serializer_class = PlatformUserSerializer
    permission_classes = [IsSuperAdmin]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return User.objects.all().order_by("-date_joined")

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.pk == request.user.pk:
            raw = request.data.get("is_active")
            if raw is not None and str(raw).lower() in ("false", "0", "no"):
                raise ValidationError(
                    {"is_active": "You cannot deactivate your own account."}
                )
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
