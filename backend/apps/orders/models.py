"""
Orders: the durable record of a completed checkout.

Design notes
------------
* Money fields (``subtotal`` / ``discount_amount`` / ``total``) are computed
  once by ``apps.orders.services.place_order`` and stored - history must not
  move when a vendor later edits a product price.
* ``OrderItem`` snapshots name, variant and unit price, and keeps the product
  FK as SET_NULL: deleting a product can never destroy financial history.
* Everything is tenant-scoped (``business_id``), so vendor dashboards query
  ``Order.objects.for_tenant(request.tenant)`` and customers add
  ``customer=request.user`` on top.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string

from apps.tenants.permissions import BusinessScopedModel

MONEY_MAX_DIGITS = 12
MONEY_DECIMAL_PLACES = 2

# Characters that are unambiguous in an order number read over the phone.
ORDER_TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class Order(BusinessScopedModel):
    """One checkout performed by one customer on one store."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"           # placed, awaiting payment
        PAID = "paid", "Paid"
        PROCESSING = "processing", "Processing"  # vendor is preparing it
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    order_number = models.CharField(max_length=40, unique=True, blank=True)

    # SET_NULL: deleting a customer account must not delete order history.
    customer = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="orders",
    )
    # Snapshots so the vendor sees who ordered even after account changes.
    customer_email = models.EmailField(blank=True)
    customer_name = models.CharField(max_length=150, blank=True)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    # Shipping snapshot (checked out from the storefront form).
    shipping_name = models.CharField(max_length=150)
    shipping_address1 = models.CharField(max_length=255)
    shipping_address2 = models.CharField(max_length=255, blank=True)
    shipping_city = models.CharField(max_length=100)
    shipping_postal_code = models.CharField(max_length=20)
    shipping_country = models.CharField(
        max_length=2, help_text="ISO-3166 alpha-2, e.g. IN, US."
    )
    shipping_phone = models.CharField(max_length=32, blank=True)

    currency = models.CharField(max_length=3, default="USD")
    subtotal = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        default=0,
        validators=[MinValueValidator(0)],
    )
    discount_amount = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        default=0,
        validators=[MinValueValidator(0)],
    )
    total = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        default=0,
        validators=[MinValueValidator(0)],
    )
    # SET_NULL keeps the numeric snapshot below if a code is ever deleted.
    voucher = models.ForeignKey(
        "promotions.DiscountCode",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    voucher_code = models.CharField(max_length=40, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["business", "status"], name="order_tenant_status_idx"
            ),
            models.Index(
                fields=["business", "-created_at"], name="order_tenant_date_idx"
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        if not self.order_number:
            stamp = timezone.now().strftime("%Y%m%d")
            prefix = "ORD"
            if self.business_id:
                # 'acme' -> 'ACME' (keeps the number readable per store)
                prefix = self.business.slug.upper().replace("-", "")[:12] or "ORD"
            while not self.order_number:
                token = get_random_string(6, ORDER_TOKEN_ALPHABET)
                candidate = f"{prefix}-{stamp}-{token}"
                if not Order.objects.filter(order_number=candidate).exists():
                    self.order_number = candidate
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if self.discount_amount > self.subtotal:
            raise ValidationError(
                {"discount_amount": "Discount cannot exceed the subtotal."}
            )
        if self.total != max(self.subtotal - self.discount_amount, 0):
            raise ValidationError(
                {"total": "Total must equal subtotal minus discount."}
            )

    @property
    def is_paid(self) -> bool:
        return self.status in (
            self.Status.PAID,
            self.Status.PROCESSING,
            self.Status.SHIPPED,
            self.Status.DELIVERED,
        )

    # -- lifecycle state machine ----------------------------------------------
    # Enforced by the vendor status endpoint: Pending -> Processing ->
    # Shipped -> Delivered, with PAID/CANCELLED exits along the way. Jumps
    # (pending -> delivered) and no-ops (shipped -> shipped) are rejected so
    # the fulfilment trail stays trustworthy.
    TRANSITIONS = {
        Status.PENDING: {Status.PAID, Status.PROCESSING, Status.CANCELLED},
        Status.PAID: {Status.PROCESSING, Status.CANCELLED},
        Status.PROCESSING: {Status.SHIPPED, Status.CANCELLED},
        Status.SHIPPED: {Status.DELIVERED},
        Status.DELIVERED: set(),
        Status.CANCELLED: set(),
    }

    def can_transition_to(self, new_status: str) -> bool:
        """True when ``new_status`` is a legal next step (no-ops are not)."""
        if new_status == self.status:
            return False
        return new_status in self.TRANSITIONS.get(self.status, set())

    def __str__(self) -> str:
        return self.order_number or f"Order #{self.pk}"


class OrderItem(BusinessScopedModel):
    """A purchased line with all values snapshotted at checkout time."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    # SET_NULL + snapshots: product removal never erases what was sold.
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=200)
    variant_name = models.CharField(max_length=200, blank=True)
    sku = models.CharField(max_length=64, blank=True)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        validators=[MinValueValidator(0)],
        help_text="Price at the moment of purchase.",
    )

    class Meta:
        ordering = ["created_at"]

    @property
    def line_total(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"))

    def save(self, *args, **kwargs) -> None:
        # The order decides the tenant (defence in depth with create_for_tenant).
        if self.order_id:
            self.business_id = self.order.business_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.product_name} x{self.quantity}"
