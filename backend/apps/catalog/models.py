"""
Catalog: categories, products, variants and reviews.

Every model extends ``BusinessScopedModel`` (see tenants/permissions.py), so
``business_id`` is part of the schema from day one and every queryset can be
scoped with ``.for_tenant(request.tenant)``.

Inventory strategy (deliberate, documented once):

    * A product WITHOUT variants keeps its stock in ``Product.stock``.
    * A product WITH variants keeps stock per ``ProductVariant.stock``;
      ``Product.total_stock`` abstracts over both so the storefront never
      has to care which shape a product has.

Variant options: ``size`` and ``color`` are first-class columns (they are the
axes shoppers filter on, so they deserve indexes); anything exotic (material,
pattern, ...) lives in the free-form ``attributes`` JSON.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify

from apps.tenants.permissions import BusinessScopedModel

MONEY_MAX_DIGITS = 10
MONEY_DECIMAL_PLACES = 2

positive_money = MinValueValidator(Decimal("0.01"), "Must be greater than zero.")


class Category(BusinessScopedModel):
    """Flat-or-nested category tree, scoped to one store."""

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0, help_text="Menu order.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "slug"],
                name="category_slug_per_business",
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        # Cross-tenant leakage guard: a sub-category must live in the same
        # store as its parent, otherwise filtering by business would split a tree.
        if self.parent_id and self.business_id and self.parent.business_id != self.business_id:
            raise ValidationError({"parent": "Parent category belongs to another store."})
        # NOTE: parent_id must be checked explicitly - on CREATE both
        # parent_id and pk are None, and `None == None` would reject every
        # new category with "cannot be its own parent".
        if self.parent_id is not None and self.parent_id == self.pk:
            raise ValidationError({"parent": "A category cannot be its own parent."})

    @property
    def full_path(self) -> str:
        parts, node = [self.name], self.parent
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return " / ".join(reversed(parts))

    def __str__(self) -> str:
        return self.name


class Product(BusinessScopedModel):
    """A sellable item of one store."""

    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,      # deleting a category must not kill sales
        null=True,
        blank=True,
        related_name="products",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    description = models.TextField(blank=True)
    sku = models.CharField(max_length=64, blank=True, help_text="Merchant stock code.")
    # Uploaded by the vendor dashboard; optional so seeding stays easy.
    image = models.ImageField(upload_to="products/%Y/%m/", blank=True, null=True)

    price = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        validators=[positive_money],
        help_text="Base price; used directly when the product has no variants.",
    )
    compare_at_price = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        null=True,
        blank=True,
        help_text="Optional 'was' price shown struck through.",
    )
    # Only consulted while the product has no variants (see module docstring).
    stock = models.PositiveIntegerField(default=0)

    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "slug"],
                name="product_slug_per_business",
            ),
        ]
        indexes = [
            models.Index(fields=["business", "is_active"], name="product_tenant_active_idx"),
        ]

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            base = slugify(self.name)[:200] or "product"
            slug, attempt = base, 1
            while (
                Product.objects.filter(business_id=self.business_id, slug=slug)
                .exclude(pk=self.pk)
                .exists()
            ):
                attempt += 1
                slug = f"{base}-{attempt}"
            self.slug = slug
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if self.category_id and self.business_id and self.category.business_id != self.business_id:
            raise ValidationError({"category": "Category belongs to another store."})
        if (
            self.compare_at_price is not None
            and self.price is not None
            and self.compare_at_price < self.price
        ):
            raise ValidationError(
                {"compare_at_price": "The 'was' price cannot be lower than the price."}
            )

    # -- inventory ------------------------------------------------------------
    @property
    def total_stock(self) -> int:
        """Stock across the shape the product actually uses (see docstring)."""
        variants = list(self.variants.all())
        if not variants:
            return self.stock
        return sum(v.stock for v in variants if v.is_active)

    @property
    def in_stock(self) -> bool:
        return self.total_stock > 0

    @property
    def starting_price(self) -> Decimal:
        """Lowest payable price (variants may undercut the base price)."""
        variants = list(self.variants.filter(is_active=True))
        if not variants:
            return self.price
        return min(v.effective_price for v in variants)

    @property
    def has_variants(self) -> bool:
        return self.variants.exists()

    def __str__(self) -> str:
        return self.name


class ProductVariant(BusinessScopedModel):
    """One purchasable combination of options (size/color/...)."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=64, blank=True)

    size = models.CharField(max_length=32, blank=True)
    color = models.CharField(max_length=32, blank=True)
    # Extra options: {"material": "cotton", "pattern": "striped"}
    attributes = models.JSONField(default=dict, blank=True)

    price = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS,
        decimal_places=MONEY_DECIMAL_PLACES,
        null=True,
        blank=True,
        validators=[positive_money],
        help_text="Leave empty to inherit Product.price.",
    )
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["size", "color"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "product", "size", "color"],
                name="variant_options_per_product",
            ),
        ]

    @property
    def effective_price(self) -> Decimal:
        return self.price if self.price is not None else self.product.price

    @property
    def display_name(self) -> str:
        """'Large / Black' - falls back to the parent product's name."""
        parts = [p for p in (self.size, self.color) if p]
        if parts:
            return " / ".join(parts)
        label = self.attributes.get("label")
        return str(label) if label else self.product.name

    def save(self, *args, **kwargs) -> None:
        # The product is the source of truth for tenancy: a variant can never
        # end up tagged with a different store than the product it belongs to.
        if self.product_id:
            self.business_id = self.product.business_id
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if self.product_id and self.business_id and self.product.business_id != self.business_id:
            raise ValidationError(
                {"business": "Variant and product must belong to the same store."}
            )

    def __str__(self) -> str:
        return f"{self.product.name} [{self.display_name}]"


class Review(BusinessScopedModel):
    """
    1-5 star review left by a customer on a product of this store.

    Moderation is part of the model (spec: vendors *approve/hide* reviews):
    only APPROVED rows are public, PENDING/REJECTED stay in the vendor queue.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1 (worst) to 5 (stars).",
    )
    title = models.CharField(max_length=150, blank=True)
    body = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    verified_purchase = models.BooleanField(
        default=False,
        help_text="Set when the reviewer actually bought the product.",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "customer"],
                name="one_review_per_customer_per_product",
            ),
        ]
        indexes = [
            models.Index(fields=["business", "status"], name="review_tenant_status_idx"),
        ]

    @property
    def is_visible(self) -> bool:
        """What the storefront shows."""
        return self.status == self.Status.APPROVED

    def save(self, *args, **kwargs) -> None:
        # Same rule as variants: the product decides the tenant.
        if self.product_id:
            self.business_id = self.product.business_id
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if self.product_id and self.business_id and self.product.business_id != self.business_id:
            raise ValidationError(
                {"business": "Review and product must belong to the same store."}
            )
        if self.rating is not None and not 1 <= int(self.rating) <= 5:
            raise ValidationError({"rating": "Rating must be between 1 and 5 stars."})

    def __str__(self) -> str:
        return f"{self.rating}★ by {self.customer_id} on {self.product_id}"
