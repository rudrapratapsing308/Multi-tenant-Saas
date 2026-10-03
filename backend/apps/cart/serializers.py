"""
Cart serializers: a read shape for the whole cart + write shapes for its
three mutations (add / set quantity / remove).

Line totals are *computed*, not stored: ``unit_price`` and ``line_total`` are
model properties that read the live product/variant price, so a vendor price
edit is reflected in the cart on the next request. The authoritative price
snapshot happens in OrderItem at checkout.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.catalog.models import Product, ProductVariant

from .models import Cart, CartItem


class LineProductSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True)
    has_variants = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = ("id", "name", "slug", "image", "price", "has_variants")


class LineVariantSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = ProductVariant
        fields = ("id", "size", "color", "display_name", "stock")


class CartItemSerializer(serializers.ModelSerializer):
    product = LineProductSerializer(read_only=True)
    variant = LineVariantSerializer(read_only=True)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    available_stock = serializers.IntegerField(read_only=True)

    class Meta:
        model = CartItem
        fields = (
            "id",
            "product",
            "variant",
            "quantity",
            "unit_price",
            "line_total",
            "available_stock",
        )


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    item_count = serializers.IntegerField(read_only=True)
    store = serializers.CharField(source="business.slug", read_only=True)

    class Meta:
        model = Cart
        fields = ("id", "store", "items", "subtotal", "item_count", "updated_at")


class CartAddSerializer(serializers.Serializer):
    """POST /api/v1/cart/ - add a line, or top up an existing one."""

    product_id = serializers.IntegerField()
    variant_id = serializers.IntegerField(
        required=False, allow_null=True, default=None
    )
    quantity = serializers.IntegerField(min_value=1, max_value=999, default=1)

    def validate(self, attrs):
        request = self.context["request"]
        cart = self.context["cart"]
        tenant = request.tenant

        # Scoped lookup: a product id from another store fails right here.
        product = (
            Product.objects.for_tenant(tenant)
            .filter(pk=attrs["product_id"], is_active=True)
            .first()
        )
        if product is None:
            raise serializers.ValidationError(
                {"product_id": "No such product in this store."}
            )

        variant = None
        if attrs.get("variant_id"):
            variant = (
                ProductVariant.objects.for_tenant(tenant)
                .filter(pk=attrs["variant_id"], product=product, is_active=True)
                .first()
            )
            if variant is None:
                raise serializers.ValidationError(
                    {"variant_id": "No such option for this product."}
                )
        elif product.has_variants:
            raise serializers.ValidationError(
                {"variant_id": "Choose one of the available options."}
            )

        available = variant.stock if variant is not None else product.stock
        existing = cart.items.filter(product=product, variant=variant).first()
        target = (existing.quantity if existing else 0) + attrs["quantity"]
        if target > available:
            raise serializers.ValidationError(
                {"quantity": f"Only {available} left in stock."}
            )

        attrs["product"] = product
        attrs["variant"] = variant
        attrs["existing"] = existing
        return attrs

    def save(self, **kwargs):
        cart = self.context["cart"]
        data = self.validated_data
        existing = data.pop("existing")
        product = data.pop("product")
        variant = data.pop("variant")

        if existing is not None:
            existing.quantity += data["quantity"]
            existing.save(update_fields=["quantity", "updated_at"])
            return existing
        return CartItem.objects.create_for_tenant(
            cart.business,
            cart=cart,
            product=product,
            variant=variant,
            quantity=data["quantity"],
        )


class CartItemUpdateSerializer(serializers.Serializer):
    """PATCH /api/v1/cart/ - set a line's quantity (0 removes the line)."""

    item_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=0, max_value=999)
