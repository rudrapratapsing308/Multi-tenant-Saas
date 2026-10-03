"""
The authenticated customer's cart for the current tenant.

    GET    /api/v1/cart/             current cart (created on first access)
    POST   /api/v1/cart/             add {product_id, variant_id?, quantity}
    PATCH  /api/v1/cart/             set {item_id, quantity} (0 = remove line)
    DELETE /api/v1/cart/?item_id=3   remove one line; omit to empty the cart

Anonymous shoppers keep their cart in localStorage (frontend concern); this
endpoint only ever exists per (customer, store) pair, so the same token can
never see another store's cart - they are different rows entirely.
"""
from __future__ import annotations

from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenants.permissions import require_tenant

from .models import Cart
from .serializers import CartAddSerializer, CartItemUpdateSerializer, CartSerializer


class CartView(APIView):
    permission_classes = [IsAuthenticated]

    # -- helpers ---------------------------------------------------------------
    def _cart(self, request) -> Cart:
        # Non-exempt path -> the middleware guarantees a tenant; require_tenant
        # turns any future regression into a loud error instead of a data leak.
        tenant = require_tenant(request)
        cart, _created = Cart.objects.get_or_create(
            business=tenant, customer=request.user
        )
        return cart

    def _payload(self, request, cart) -> dict:
        return CartSerializer(cart, context={"request": request}).data

    def _line(self, cart, item_id):
        """Fetch a line *through the cart* (cart is already tenant-scoped)."""
        try:
            item_id = int(item_id)
        except (TypeError, ValueError):
            raise ValidationError({"item_id": "Not a valid cart item id."})
        item = cart.items.filter(pk=item_id).first()
        if item is None:
            raise ValidationError({"item_id": "This item is not in your cart."})
        return item

    # -- verbs -----------------------------------------------------------------
    def get(self, request):
        cart = self._cart(request)
        return Response(self._payload(request, cart))

    def post(self, request):
        cart = self._cart(request)
        serializer = CartAddSerializer(
            data=request.data, context={"request": request, "cart": cart}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(self._payload(request, cart))

    def patch(self, request):
        cart = self._cart(request)
        serializer = CartItemUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = self._line(cart, serializer.validated_data["item_id"])
        quantity = serializer.validated_data["quantity"]

        if quantity == 0:
            item.delete()
        else:
            if quantity > item.available_stock:
                raise ValidationError(
                    {"quantity": f"Only {item.available_stock} left in stock."}
                )
            item.quantity = quantity
            item.save(update_fields=["quantity", "updated_at"])
        return Response(self._payload(request, cart))

    def delete(self, request):
        cart = self._cart(request)
        item_id = request.query_params.get("item_id")
        if item_id is None and isinstance(request.data, dict):
            item_id = request.data.get("item_id")

        if item_id is not None:
            self._line(cart, item_id).delete()
        else:
            cart.clear()
        return Response(self._payload(request, cart))
