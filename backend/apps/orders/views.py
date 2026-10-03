"""Order endpoints: checkout (create) + the customer's own order history."""
from __future__ import annotations

from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cart.models import Cart
from apps.tenants.permissions import require_tenant

from .models import Order
from .serializers import CheckoutSerializer, OrderSerializer
from .services import CheckoutError, place_order


class CheckoutView(APIView):
    """
    POST /api/v1/orders/checkout/

    Body: ``{cart_id?, voucher_code?, shipping: {...}, notes?}``.
    Resolves the cart (tenant + owner scoped), validates the voucher against
    THIS store, creates Order/OrderItems, empties the cart -> 201 Order.
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _resolve_cart(request, tenant, cart_id) -> Cart:
        scope = Cart.objects.for_tenant(tenant).filter(customer=request.user)
        if cart_id:
            cart = scope.filter(pk=cart_id).first()
            if cart is None:
                # Unknown id, another customer's, or another store's cart:
                # deliberately indistinguishable.
                raise CheckoutError(
                    "cart_not_found", "That cart does not exist for this store."
                )
            return cart
        cart = scope.first()
        if cart is None:
            raise CheckoutError("empty_cart", "Your cart is empty.")
        return cart

    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = require_tenant(request)

        try:
            cart = self._resolve_cart(request, tenant, data.get("cart_id"))
            order = place_order(
                cart=cart,
                customer=request.user,
                shipping=data["shipping"],
                voucher_code=data.get("voucher_code", ""),
                notes=data.get("notes") or "",
            )
        except CheckoutError as exc:
            return Response(
                {"error": exc.code, "detail": exc.message, **exc.extra},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class OrderListView(ListAPIView):
    """GET /api/v1/orders/ - this customer's orders for the CURRENT store."""

    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Order.objects.for_tenant(self.request.tenant)
            .filter(customer=self.request.user)
            .prefetch_related("items")
        )
