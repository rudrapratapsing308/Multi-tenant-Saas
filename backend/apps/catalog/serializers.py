"""
Catalog serializers: categories, products (list + detail) and reviews.

Public payloads expose storefront-safe fields only. The isolation trick worth
knowing: ``ReviewSerializer.__init__`` re-points the writable ``product`` FK at
``Product.objects.for_tenant(request.tenant)``, so a review can physically
never be attached to another store's product - the field's own validation
rejects foreign ids with a 400.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.orders.models import Order, OrderItem

from .models import Category, Product, ProductVariant, Review


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug", "description", "position", "parent")


class ProductVariantSerializer(serializers.ModelSerializer):
    # A variant may not override the price -> fall back to the product's price.
    price = serializers.DecimalField(
        source="effective_price", max_digits=10, decimal_places=2, read_only=True
    )
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = ProductVariant
        fields = (
            "id",
            "sku",
            "size",
            "color",
            "attributes",
            "price",
            "stock",
            "display_name",
        )


class ReviewSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = (
            "id",
            "product",
            "rating",
            "title",
            "body",
            "status",
            "verified_purchase",
            "customer_name",
            "created_at",
        )
        read_only_fields = (
            "status",
            "verified_purchase",
            "customer_name",
            "created_at",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Tenant-scoped queryset for the writable FK (see module docstring).
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) if request is not None else None
        self.fields["product"].queryset = Product.objects.for_tenant(tenant).filter(
            is_active=True
        )

    def get_customer_name(self, obj) -> str:
        return obj.customer.get_full_name() or "Customer"

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        tenant = request.tenant
        product = attrs["product"]

        # Spec: only customers who actually bought the product may review it.
        bought = (
            OrderItem.objects.for_tenant(tenant)
            .filter(product=product, order__customer=user)
            .exclude(order__status=Order.Status.CANCELLED)
            .exists()
        )
        if not bought:
            raise serializers.ValidationError(
                {"product": "You can only review products you have purchased."}
            )

        if (
            Review.objects.for_tenant(tenant)
            .filter(product=product, customer=user)
            .exists()
        ):
            raise serializers.ValidationError(
                {"product": "You have already reviewed this product."}
            )

        attrs["customer"] = user
        attrs["business"] = tenant  # model save() re-derives it from the product
        attrs["verified_purchase"] = True  # purchase proven above
        return attrs


class ProductListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    image = serializers.ImageField(read_only=True)
    starting_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    in_stock = serializers.BooleanField(read_only=True)
    total_stock = serializers.IntegerField(read_only=True)
    has_variants = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "slug",
            "category",
            "price",
            "compare_at_price",
            "starting_price",
            "image",
            "in_stock",
            "total_stock",
            "has_variants",
            "is_featured",
        )


class ProductDetailSerializer(ProductListSerializer):
    variants = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    rating_average = serializers.SerializerMethodField()
    rating_count = serializers.SerializerMethodField()

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + (
            "description",
            "sku",
            "variants",
            "reviews",
            "rating_average",
            "rating_count",
            "created_at",
        )

    # -- helpers ---------------------------------------------------------------
    def _approved(self, obj):
        """Approved reviews, preferring the prefetch done by the detail view."""
        reviews = getattr(obj, "approved_reviews", None)
        if reviews is None:
            reviews = (
                obj.reviews.for_tenant(obj.business_id)
                .filter(status=Review.Status.APPROVED)
                .select_related("customer")
                .order_by("-created_at")
            )
        return reviews

    def get_variants(self, obj):
        variants = getattr(obj, "active_variants", None)
        if variants is None:
            variants = obj.variants.for_tenant(obj.business_id).filter(is_active=True)
        return ProductVariantSerializer(variants, many=True).data

    def get_reviews(self, obj):
        return ReviewSerializer(
            self._approved(obj), many=True, context=self.context
        ).data

    def get_rating_average(self, obj):
        reviews = list(self._approved(obj))
        if not reviews:
            return None
        return round(sum(r.rating for r in reviews) / len(reviews), 2)

    def get_rating_count(self, obj):
        return len(list(self._approved(obj)))
