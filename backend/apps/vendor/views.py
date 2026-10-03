"""
Vendor dashboard API.

    GET/PATCH/DELETE  /api/v1/vendor/products/      full catalog CRUD
    GET/POST          /api/v1/vendor/categories/    full category CRUD
    GET/POST          /api/v1/vendor/promotions/    discount code CRUD
    GET               /api/v1/vendor/orders/        order list + detail
    PATCH             /api/v1/vendor/orders/<id>/status/
    GET               /api/v1/vendor/analytics/
    GET/PATCH         /api/v1/vendor/settings/      storefront branding

Two gates run before any row is read (and they stack):

  1. ``IsVendorForTenant`` - role must be Vendor AND the user must hold an
     active membership on ``request.tenant``. A vendor token from store A
     presented against store B gets 403 *before a queryset exists*.
  2. ``get_queryset()``     - always ``Model.objects.for_tenant(tenant)``, so
     even a missed permission check could not widen the scope: a foreign id
     is simply not in the queryset -> 404.

Analytics are computed with ORM aggregates (``Sum``/``Count`` over the
tenant's orders) - two indexed queries, database-agnostic, no raw SQL, and
``Order.Meta.indexes`` (business, status) keeps them on an index.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum
from rest_framework import mixins
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from apps.accounts.models import CustomerStoreLink
from apps.accounts.permissions import IsVendorForTenant
from apps.catalog.models import Category, Product
from apps.orders.models import Order
from apps.promotions.models import DiscountCode
from apps.storefront.models import BrandConfig
from apps.tenants.permissions import require_tenant

from .serializers import (
    BrandConfigSerializer,
    OrderStatusSerializer,
    VendorCategorySerializer,
    VendorDiscountCodeSerializer,
    VendorOrderSerializer,
    VendorProductSerializer,
    cleanup_media_file,
)

CENTS = Decimal("0.01")


class _VendorScopedModelViewSet(ModelViewSet):
    """CRUD ViewSet whose queryset + create both default to this store."""

    permission_classes = [IsAuthenticated, IsVendorForTenant]

    def perform_create(self, serializer):
        serializer.save(business=self.request.tenant)


class VendorProductViewSet(_VendorScopedModelViewSet):
    serializer_class = VendorProductSerializer

    def get_queryset(self):
        tenant = require_tenant(self.request)
        return (
            Product.objects.for_tenant(tenant)
            .select_related("category")
            .prefetch_related("variants")
        )

    def perform_destroy(self, instance):
        image = instance.image  # capture before the row (and path) vanish
        instance.delete()
        cleanup_media_file(image)  # no orphaned photos on disk


class VendorCategoryViewSet(_VendorScopedModelViewSet):
    serializer_class = VendorCategorySerializer

    def get_queryset(self):
        tenant = require_tenant(self.request)
        return Category.objects.for_tenant(tenant).select_related("parent")


class VendorDiscountCodeViewSet(_VendorScopedModelViewSet):
    serializer_class = VendorDiscountCodeSerializer

    def get_queryset(self):
        return DiscountCode.objects.for_tenant(require_tenant(self.request))


class VendorOrderViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, GenericViewSet
):
    """
    GET /api/v1/vendor/orders/       - every order of the store the vendor manages
    GET /api/v1/vendor/orders/<id>/  - one of them
    PATCH .../orders/<id>/status/    - advance the fulfilment state machine
    """

    serializer_class = VendorOrderSerializer
    permission_classes = [IsAuthenticated, IsVendorForTenant]

    def get_queryset(self):
        # Guaranteed non-None by IsVendorForTenant (it ran first).
        tenant = require_tenant(self.request)
        queryset = (
            Order.objects.for_tenant(tenant)
            .select_related("customer")
            .prefetch_related("items")
        )

        status_param = self.request.query_params.get("status")
        if status_param:
            valid = {value for value, _ in Order.Status.choices}
            if status_param not in valid:
                raise ValidationError(
                    {"status": f"Must be one of: {', '.join(sorted(valid))}."}
                )
            queryset = queryset.filter(status=status_param)
        return queryset

    @action(detail=True, methods=["patch"], url_path="status")
    def status(self, request, pk=None):
        """
        Advance one order: pending -> processing -> shipped -> delivered
        (plus paid/cancelled exits). Illegal jumps and no-ops are rejected by
        ``Order.can_transition_to`` so the fulfilment trail stays trustworthy.
        """
        order = self.get_object()  # tenant-scoped -> foreign id is a 404
        serializer = OrderStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["status"]

        if not order.can_transition_to(new_status):
            allowed = sorted(Order.TRANSITIONS.get(order.status, set()))
            message = (
                f"An order cannot go from '{order.status}' to '{new_status}'."
            )
            if allowed:
                message += f" Allowed next: {', '.join(allowed)}."
            else:
                message += " This is a final state."
            raise ValidationError({"status": message})

        order.status = new_status
        order.save(update_fields=["status", "updated_at"])
        return Response(VendorOrderSerializer(order).data)


class VendorAnalyticsView(APIView):
    """GET /api/v1/vendor/analytics/ - money & volumes for THIS store only."""

    permission_classes = [IsAuthenticated, IsVendorForTenant]

    def get(self, request):
        tenant = require_tenant(request)
        orders = Order.objects.for_tenant(tenant)
        # Cancelled orders are not revenue and not "sales".
        live = orders.exclude(status=Order.Status.CANCELLED)

        totals = live.aggregate(revenue=Sum("total"), order_count=Count("id"))
        revenue = (totals["revenue"] or Decimal("0")).quantize(CENTS)
        order_count = totals["order_count"] or 0
        average = (revenue / order_count).quantize(CENTS) if order_count else Decimal("0")

        # Distinct customers who ever ordered here, across all statuses.
        customers = (
            orders.filter(customer__isnull=False)
            .values("customer")
            .distinct()
            .count()
        )
        # Shoppers linked to this store (registration / first visit).
        linked = CustomerStoreLink.objects.for_tenant(tenant).count()

        by_status = {value: 0 for value, _ in Order.Status.choices}
        by_status.update(
            {
                row["status"]: row["n"]
                for row in orders.values("status").annotate(n=Count("id"))
            }
        )

        return Response(
            {
                "currency": tenant.currency,
                "total_revenue": str(revenue),
                "total_orders": order_count,
                "total_customers": customers,
                "linked_customers": linked,
                "average_order_value": str(average.quantize(CENTS)),
                "orders_by_status": by_status,
            }
        )


class BrandConfigView(APIView):
    """
    GET/PATCH /api/v1/vendor/settings/ - storefront branding of this store.

    The row is created lazily on first read so the dashboard always has a
    form to show (defaults come from the model). No id in the URL: the store
    IS ``request.tenant``, which makes cross-tenant edits structurally
    impossible.
    """

    permission_classes = [IsAuthenticated, IsVendorForTenant]

    @staticmethod
    def _config(request) -> BrandConfig:
        tenant = require_tenant(request)
        config, _created = BrandConfig.objects.get_or_create(business=tenant)
        return config

    @staticmethod
    def _payload(config, request) -> dict:
        # context={"request"} makes uploaded logo/favicon URLs absolute,
        # matching how /storefront/init/ and the product endpoints answer.
        return BrandConfigSerializer(config, context={"request": request}).data

    def get(self, request):
        return Response(self._payload(self._config(request), request))

    def patch(self, request):
        config = self._config(request)
        serializer = BrandConfigSerializer(
            config, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(self._payload(config, request))
