"""
Promotions: per-store discount codes and vouchers.

Isolation is structural, not a runtime check: ``business`` is a required
column and the code itself is unique **per business**, so
``DiscountCode.objects.for_tenant(tenant).get(code="SAVE10")`` can only ever
return that store's SAVE10 - another tenant's identically named code is
invisible by construction (spec: "validate that a voucher belongs to the
specific store the customer is visiting").

The arithmetic lives here (not in the view/serializer) so the cart, the
checkout and the vendor dashboard all quote the same numbers.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

from apps.tenants.permissions import BusinessScopedModel

MONEY_MAX_DIGITS = 10
MONEY_DECIMAL_PLACES = 2

code_validator = RegexValidator(
    regex=r"^[A-Za-z0-9_-]{3,40}$",
    message="3-40 characters: letters, digits, '-' or '_'.",
)


class DiscountCode(BusinessScopedModel):
    """A voucher / discount code that belongs to exactly one store."""

    class DiscountType(models.TextChoices):
        PERCENTAGE = "percentage", "Percentage off"
        FLAT = "flat", "Fixed amount off"

    code = models.CharField(max_length=40, validators=[code_validator])
    name = models.CharField(max_length=120, blank=True, help_text="Internal label.")
    description = models.CharField(max_length=255, blank=True)

    discount_type = models.CharField(
        max_length=16, choices=DiscountType.choices, default=DiscountType.PERCENTAGE
    )
    value = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Percentage (0-100) or fixed amount in the store currency.",
    )
    min_order_amount = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        null=True,
        blank=True,
        help_text="Subtotal required for the code to apply.",
    )

    max_uses = models.PositiveIntegerField(
        null=True, blank=True, help_text="Store-wide redemption cap (blank = unlimited)."
    )
    used_count = models.PositiveIntegerField(default=0)

    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Same code may exist in other stores - never here twice.
            models.UniqueConstraint(
                fields=["business", "code"],
                name="discount_code_per_business",
            ),
        ]
        indexes = [
            models.Index(fields=["business", "is_active"], name="discount_tenant_active_idx"),
        ]

    # -- lifecycle ------------------------------------------------------------
    def save(self, *args, **kwargs) -> None:
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if self.discount_type == self.DiscountType.PERCENTAGE:
            if self.value is not None and self.value > 100:
                raise ValidationError(
                    {"value": "A percentage discount cannot exceed 100%."}
                )
        elif self.value is not None and self.value <= 0:
            raise ValidationError({"value": "A fixed discount must be greater than zero."})
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError({"ends_at": "The code must end after it starts."})

    # -- validation used by cart/checkout (next modules) -----------------------
    def rejection_reason(
        self, subtotal: Decimal | None = None, now: Optional[datetime] = None
    ) -> Optional[str]:
        """
        ``None`` when the code may be applied, otherwise a machine-readable
        code explaining why not - checkout maps these to user-facing messages::

            voucher_inactive | voucher_not_started | voucher_expired
            voucher_exhausted | voucher_min_order_not_met
        """
        if not self.is_active:
            return "voucher_inactive"
        now = now or timezone.now()
        if self.starts_at and now < self.starts_at:
            return "voucher_not_started"
        if self.ends_at and now > self.ends_at:
            return "voucher_expired"
        if self.max_uses is not None and self.used_count >= self.max_uses:
            return "voucher_exhausted"
        if (
            subtotal is not None
            and self.min_order_amount is not None
            and subtotal < self.min_order_amount
        ):
            return "voucher_min_order_not_met"
        return None

    def is_currently_valid(self, now: Optional[datetime] = None) -> bool:
        """Active, inside its time window and not exhausted."""
        return self.rejection_reason(now=now) is None

    def is_applicable(self, subtotal: Decimal, now: Optional[datetime] = None) -> bool:
        """True when the code may be applied to this cart subtotal."""
        return self.rejection_reason(subtotal, now) is None

    def calculate_discount(self, subtotal: Decimal) -> Decimal:
        """
        Amount taken off ``subtotal`` (never more than the subtotal itself).

        Assumes ``is_applicable`` passed - callers should check it first so the
        rejection reason (min order, expired, ...) can be shown to the shopper.
        """
        subtotal = Decimal(subtotal)
        if self.discount_type == self.DiscountType.PERCENTAGE:
            amount = (subtotal * self.value / Decimal("100")).quantize(Decimal("0.01"))
        else:
            amount = self.value
        return min(amount, subtotal)

    @property
    def display_value(self) -> str:
        if self.discount_type == self.DiscountType.PERCENTAGE:
            return f"{self.value:g}%"
        return str(self.value)

    def __str__(self) -> str:
        return f"{self.code} ({self.display_value})"
