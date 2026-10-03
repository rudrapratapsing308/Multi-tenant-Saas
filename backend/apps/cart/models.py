"""
Server-side cart: one cart per (customer, store).

The React app keeps an *anonymous* cart in localStorage and syncs it here once
the shopper logs in (POST the merged lines). The unique constraint below means
exactly one cart exists per customer per store, so a token obtained while
browsing acme.local-saas.com can only ever reach the acme cart - the nike cart
is a different row behind a different ``business_id``.

Prices are NOT stored on the cart: ``unit_price`` / ``line_total`` read the
current product/variant price every time, so an edit by the vendor shows up
immediately. The authoritative price snapshot happens at checkout (OrderItem).
"""
from __future__ import annotations

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.tenants.permissions import BusinessScopedModel


class Cart(BusinessScopedModel):
    """A customer's shopping cart for exactly one store."""

    customer = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="carts",
        help_text="Authenticated shopper; anonymous carts live in localStorage.",
    )

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "customer"],
                name="cart_unique_per_customer_store",
            ),
        ]

    # -- totals ---------------------------------------------------------------
    @property
    def subtotal(self) -> Decimal:
        """Sum of live line totals (money, always 2 decimal places)."""
        return sum(
            (item.line_total for item in self.items.all()), Decimal("0.00")
        )

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items.all())

    def clear(self) -> None:
        self.items.all().delete()

    def __str__(self) -> str:
        return f"Cart #{self.pk} ({self.business_id})"


class CartItem(BusinessScopedModel):
    """One line: a product (optionally a variant) and a quantity."""

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="cart_items"
    )
    # Null only for products that have no variants at all.
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cart_items",
    )
    quantity = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)]
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product", "variant"],
                name="cart_line_unique",
            ),
        ]

    # -- live pricing ---------------------------------------------------------
    @property
    def unit_price(self) -> Decimal:
        if self.variant_id:
            return self.variant.effective_price
        return self.product.price

    @property
    def line_total(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"))

    @property
    def available_stock(self) -> int:
        """Stock for the exact combination on this line."""
        if self.variant_id:
            return self.variant.stock
        # Product without variants: its own counter is the source of truth.
        return self.product.stock

    @property
    def product_name(self) -> str:
        return self.product.name

    @property
    def variant_name(self) -> str:
        return self.variant.display_name if self.variant_id else ""

    def save(self, *args, **kwargs) -> None:
        # The cart decides the tenant - a line can never belong elsewhere.
        if self.cart_id:
            self.business_id = self.cart.business_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.product_name} x{self.quantity}"
