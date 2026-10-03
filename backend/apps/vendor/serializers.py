"""
Vendor dashboard serializers.

Two principles run through this module:

1. **Scoping** - every writable FK (``category``, ``parent``, ...) has its
   queryset re-pointed at ``Model.objects.for_tenant(request.tenant)`` in
   ``__init__``, so an id belonging to another store fails *field validation*
   with a 400 - it can never be written into a row of the wrong tenant.
2. **One source of validation truth** - DRF does not call ``Model.clean()``,
   so create/update run through :class:`ValidatedModelSerializer`, which calls
   ``full_clean()`` and translates Django's ``ValidationError`` back into DRF
   format. Model rules (percentage <= 100, same-store parent, compare-at
   price, slug/code uniqueness *per business*) therefore behave identically
   for the API, the admin and the ORM.

Image uploads: Pillow (via DRF's ``ImageField``) rejects anything that is not
a decodable image, and ``validate_<field>`` enforces a 2 MB cap *after*
decoding - small enough for a dashboard, big enough for a product photo.
Replaced/deleted image files are cleaned off disk (see ``cleanup_fields``).
"""
from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.text import slugify
from rest_framework import serializers

from apps.catalog.models import Category, Product
from apps.orders.models import Order
from apps.orders.serializers import OrderItemSerializer
from apps.promotions.models import DiscountCode
from apps.storefront.models import BrandConfig

# Per-image upload cap for vendor media (logo, favicon, product photos).
MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB


def cleanup_media_file(field_file) -> None:
    """Best-effort removal of a replaced/deleted media file from storage."""
    if not field_file:
        return
    try:
        if field_file.storage.exists(field_file.name):
            field_file.storage.delete(field_file.name)
    except OSError:  # storage hiccup must never fail the API call
        pass


def check_upload_size(value):
    """Shared 2 MB cap for image uploads (runs after Pillow decoded them)."""
    if value is not None and getattr(value, "size", 0) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise serializers.ValidationError(
            f"Image too large - maximum {limit_mb} MB per upload."
        )
    return value


class ValidatedModelSerializer(serializers.ModelSerializer):
    """
    ModelSerializer that persists only after ``Model.full_clean()`` passes.

    ``cleanup_fields`` names image fields whose *previous* file is deleted
    from storage once an update replaces them (orphans never pile up).
    """

    cleanup_fields: tuple = ()

    def create(self, validated_data):
        instance = self.Meta.model(**validated_data)
        self._full_clean(instance)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        stale_files = [
            getattr(instance, name)
            for name in self.cleanup_fields
            if name in validated_data and getattr(instance, name)
        ]
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        self._full_clean(instance)
        instance.save()
        for field_file in stale_files:
            cleanup_media_file(field_file)
        return instance

    @staticmethod
    def _full_clean(instance) -> None:
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            if hasattr(exc, "message_dict"):
                raise serializers.ValidationError(exc.message_dict) from None
            raise serializers.ValidationError(exc.messages) from None


class TenantScopedFieldsMixin:
    """Re-point the given writable FK fields at the current tenant's rows."""

    scoped_fields: tuple = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) if request is not None else None
        for name in self.scoped_fields:
            model = self.Meta.model._meta.get_field(name).related_model
            self.fields[name].queryset = model.objects.for_tenant(tenant)


class VendorProductSerializer(TenantScopedFieldsMixin, ValidatedModelSerializer):
    """Full product CRUD payload for the vendor dashboard."""

    image = serializers.ImageField(required=False, allow_null=True)
    total_stock = serializers.IntegerField(read_only=True)
    starting_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    scoped_fields = ("category",)
    cleanup_fields = ("image",)

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "sku",
            "category",
            "price",
            "compare_at_price",
            "stock",
            "is_active",
            "is_featured",
            "image",
            "total_stock",
            "starting_price",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_image(self, value):
        return check_upload_size(value)

    def create(self, validated_data):
        # ``Product.save()`` only slugifies a *blank* slug, and it runs AFTER
        # ``full_clean()`` - pre-generate here so a duplicate name answers a
        # clean 400 (per-tenant unique constraint) instead of silently
        # appending "-2" or hitting the database with an IntegrityError.
        if not validated_data.get("slug"):
            name = validated_data.get("name", "")
            validated_data["slug"] = slugify(name)[:200] or "product"
        return super().create(validated_data)


class VendorCategorySerializer(TenantScopedFieldsMixin, ValidatedModelSerializer):
    """Category CRUD; ``parent`` may only point inside this store."""

    scoped_fields = ("parent",)
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "position",
            "parent",
            "is_active",
            "product_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def get_product_count(self, obj) -> int:
        return obj.products.count()

    def create(self, validated_data):
        # See VendorProductSerializer.create - Category.save() has NO
        # uniquifier, so without a pre-generated slug a duplicate name would
        # raise IntegrityError (500) instead of answering 400.
        if not validated_data.get("slug"):
            name = validated_data.get("name", "")
            validated_data["slug"] = slugify(name)[:140] or "category"
        return super().create(validated_data)


class VendorDiscountCodeSerializer(ValidatedModelSerializer):
    """Discount/voucher CRUD (codes are uppercased by the model's save())."""

    display_value = serializers.CharField(read_only=True)

    class Meta:
        model = DiscountCode
        fields = (
            "id",
            "code",
            "name",
            "description",
            "discount_type",
            "value",
            "min_order_amount",
            "max_uses",
            "used_count",
            "starts_at",
            "ends_at",
            "is_active",
            "display_value",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "used_count", "created_at", "updated_at")

    def validate_code(self, value):
        # The model uppercases on save(); normalise BEFORE full_clean() so the
        # per-store unique check compares the same shape that will be stored
        # (otherwise a lowercase duplicate sails past validation and dies with
        # IntegrityError/500 on INSERT).
        return value.strip().upper()


class VendorOrderSerializer(serializers.ModelSerializer):
    """
    Vendor-facing order payload: fulfilment state + who bought what.

    Read-only: order rows are created by checkout and only their ``status``
    moves (via the status action in views.py).
    """

    items = OrderItemSerializer(many=True, read_only=True)
    customer = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "order_number",
            "status",
            "created_at",
            "customer",
            "customer_email",
            "customer_name",
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


class OrderStatusSerializer(serializers.Serializer):
    """Body of ``PATCH /api/v1/vendor/orders/<id>/status/``."""

    status = serializers.ChoiceField(choices=Order.Status.choices)


class BrandConfigSerializer(ValidatedModelSerializer):
    """
    Storefront settings: brand name, tagline, theme colours, logo/favicon.

    Colours are hex-validated by the model field (``HEX_COLOR_VALIDATOR``)
    and again by ``full_clean()``; the API never accepts raw CSS, which is
    what keeps React's theme injection-safe.
    """

    logo = serializers.ImageField(required=False, allow_null=True)
    favicon = serializers.ImageField(required=False, allow_null=True)
    display_name = serializers.CharField(read_only=True)
    cleanup_fields = ("logo", "favicon")

    class Meta:
        model = BrandConfig
        fields = (
            "brand_name",
            "tagline",
            "logo",
            "favicon",
            "primary_color",
            "secondary_color",
            "accent_color",
            "is_active",
            "display_name",
        )

    def validate_logo(self, value):
        return check_upload_size(value)

    def validate_favicon(self, value):
        return check_upload_size(value)
