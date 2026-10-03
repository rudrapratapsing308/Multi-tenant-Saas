"""
Storefront branding: what makes one tenant look different from the next.

    BrandConfig - 1:1 with Business (name, logo, theme colours)
    Banner      - active promotional banners returned by /storefront/init/

The React app never hard-codes a colour or a logo: it boots from the init
endpoint and styles itself from this data.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from apps.tenants.permissions import BusinessScopedModel

# #111827 / #fff - short or long hex, nothing else (keeps CSS injection out).
HEX_COLOR_VALIDATOR = RegexValidator(
    regex=r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$",
    message="Use a hex colour such as #111827.",
)

# Used by /storefront/init/ until a vendor uploads their own BrandConfig.
DEFAULT_THEME = {
    "primary_color": "#111827",
    "secondary_color": "#6b7280",
    "accent_color": "#f59e0b",
}


class BrandConfig(BusinessScopedModel):
    """Per-store brand identity (exactly one row per business)."""

    # Redefines the abstract FK as OneToOne -> business.brand_config
    business = models.OneToOneField(
        "tenants.Business",
        on_delete=models.CASCADE,
        related_name="brand_config",
    )
    brand_name = models.CharField(
        max_length=150,
        blank=True,
        help_text="Shown to shoppers; falls back to the business name.",
    )
    tagline = models.CharField(max_length=200, blank=True)

    logo = models.ImageField(upload_to="brands/logos/%Y/%m/", blank=True, null=True)
    favicon = models.ImageField(upload_to="brands/favicons/%Y/%m/", blank=True, null=True)

    primary_color = models.CharField(
        max_length=7, default=DEFAULT_THEME["primary_color"],
        validators=[HEX_COLOR_VALIDATOR],
    )
    secondary_color = models.CharField(
        max_length=7, default=DEFAULT_THEME["secondary_color"],
        validators=[HEX_COLOR_VALIDATOR],
    )
    accent_color = models.CharField(
        max_length=7, default=DEFAULT_THEME["accent_color"],
        validators=[HEX_COLOR_VALIDATOR],
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "brand configuration"

    @property
    def display_name(self) -> str:
        return self.brand_name or self.business.name

    @property
    def theme(self) -> dict:
        return {
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "accent_color": self.accent_color,
        }

    def __str__(self) -> str:
        return f"Brand of {self.business_id}"


class Banner(BusinessScopedModel):
    """Promotional banner shown on the storefront homepage."""

    title = models.CharField(max_length=150)
    subtitle = models.CharField(max_length=200, blank=True)
    image = models.ImageField(upload_to="brands/banners/%Y/%m/", blank=True, null=True)
    link_url = models.CharField(
        max_length=300,
        blank=True,
        help_text="Where the banner points: /products/teeshirt or a full URL.",
    )
    position = models.PositiveIntegerField(default=0, help_text="Sort order, lowest first.")
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "-created_at"]

    def clean(self) -> None:
        super().clean()
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError(
                {"ends_at": "The banner must end after it starts."}
            )

    def is_current(self, now=None) -> bool:
        """Active AND inside its scheduling window (used by /storefront/init/)."""
        if not self.is_active:
            return False
        now = now or timezone.now()
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True

    def __str__(self) -> str:
        return self.title
