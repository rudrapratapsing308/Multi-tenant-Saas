"""
Order serializers.

Everything on an Order is read-only for API consumers: orders are *created*
by the checkout service, never patched into existence by clients.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = OrderItem
        fields = (
            "id",
            "product",
            "variant",
            "product_name",
            "variant_name",
            "sku",
            "quantity",
            "unit_price",
            "line_total",
        )


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "order_number",
            "status",
            "created_at",
            "currency",
            "subtotal",
            "discount_amount",
            "total",
            "voucher_code",
            "shipping_name",
            "shipping_address1",
            "shipping_address2",
            "shipping_city",
            "shipping_postal_code",
            "shipping_country",
            "shipping_phone",
            "notes",
            "items",
        )
        read_only_fields = fields


class ShippingAddressSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    address1 = serializers.CharField(max_length=255)
    address2 = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    city = serializers.CharField(max_length=100)
    postal_code = serializers.CharField(max_length=20)
    country = serializers.CharField(max_length=2)
    phone = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )

    def validate_country(self, value):
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha():
            raise serializers.ValidationError(
                "Use a 2-letter ISO-3166 country code (e.g. IN, US)."
            )
        return value


class CheckoutSerializer(serializers.Serializer):
    """
    POST /api/v1/orders/checkout/

    ``cart_id`` is optional: omit it to check out the caller's own cart for
    this store. When supplied it is still filtered by tenant AND owner, so a
    foreign cart id simply doesn't exist (400 cart_not_found).
    """

    cart_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    voucher_code = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    shipping = ShippingAddressSerializer()
    notes = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=""
    )

    def validate_voucher_code(self, value):
        return (value or "").strip().upper()
