"""
Tenancy kernel models.

Two tables describe "who is a tenant":

    Business  - the store itself (brand owner, status, currency, owner)
    Domain    - a hostname that routes to a Business. One business can own
                several domains (``acme.local-saas.com`` + ``shop.acme.com``),
                and the middleware maps ``Host`` -> Domain -> Business.

This is what makes the platform multi-tenant instead of multi-site: the
*same* Django process, the *same* tables, and a single discriminator column
(``business_id``) that every other app filters on (see permissions.py).
"""
from __future__ import annotations

import re
from typing import Optional

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.text import slugify

from apps.core.models import TimeStampedModel

# RFC 1035: a full host name is at most 253 characters.
MAX_HOST_LENGTH = 253

# A DNS label must be letters/digits/hyphens; underscores are tolerated by
# browsers but break resolvers, so subdomain slugs are stricter than SlugField.
subdomain_validator = RegexValidator(
    regex=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    message="Use lowercase letters, digits and hyphens only "
            "(this becomes <value>.local-saas.com).",
)


def normalize_host(raw: Optional[str]) -> str:
    """
    Canonicalise anything that looks like a hostname.

        "HTTPS://Acme.Local-SaaS.com.:8000 "  ->  "acme.local-saas.com"
        "a.local-saas.com, b.local-saas.com"  ->  "a.local-saas.com"
        "[::1]:8000"                          ->  "::1"

    Used by both the middleware (incoming request) and Domain.save()
    (stored value), so lookups can never drift from what is persisted.
    """
    if not raw:
        return ""

    host = raw.strip().lower()

    # X-Forwarded-Host may legally carry several values; the first is the client's.
    host = host.split(",")[0].strip()

    # Defensive: tolerate a scheme/path pasted into the header.
    if "//" in host:
        host = host.split("//", 1)[1]
    host = host.split("/")[0].strip()

    if host.startswith("["):
        # [2001:db8::1]:8000 -> 2001:db8::1
        host = host[1:].partition("]")[0]
    elif host.count(":") == 1:
        # example.com:8000 -> example.com  (a bare IPv6 has >= 2 colons)
        host = host.split(":")[0]

    return host.rstrip(".")


class Business(TimeStampedModel):
    """A single tenant: one micro-business / one storefront."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PENDING = "pending", "Pending review"
        SUSPENDED = "suspended", "Suspended"   # temporary freeze
        BLOCKED = "blocked", "Blocked"         # hard block by super admin

    name = models.CharField("business name", max_length=150)
    slug = models.SlugField(
        max_length=63,
        unique=True,
        validators=[subdomain_validator],
        help_text="Subdomain label: 'acme' -> acme.local-saas.com",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
        help_text="Super admin can suspend or block a store.",
    )
    # SET_NULL: deleting a user must not delete every store row they own.
    owner = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_businesses",
        help_text="Vendor account that manages this store.",
    )
    currency = models.CharField(
        max_length=3, default="USD", help_text="ISO-4217 code shown at checkout."
    )
    timezone = models.CharField(max_length=64, default="UTC")
    contact_email = models.EmailField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "businesses"
        indexes = [
            models.Index(fields=["status", "name"], name="business_status_name_idx"),
        ]

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            base = (slugify(self.name)[:50] or "store").strip("-")
            slug, attempt = base, 1
            while Business.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                attempt += 1
                slug = f"{base}-{attempt}"
            self.slug = slug
        self.currency = (self.currency or "").upper() or "USD"
        super().save(*args, **kwargs)

    @property
    def is_active(self) -> bool:
        """Only an ACTIVE store may serve traffic (middleware enforces it)."""
        return self.status == self.Status.ACTIVE

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class Domain(TimeStampedModel):
    """A hostname that resolves to exactly one :class:`Business`."""

    host = models.CharField(
        max_length=MAX_HOST_LENGTH,
        unique=True,
        help_text="FQDN, e.g. acme.local-saas.com (port is stripped on save).",
    )
    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="domains"
    )
    is_primary = models.BooleanField(
        default=False, help_text="Main storefront host of this business."
    )
    is_active = models.BooleanField(
        default=True, help_text="Uncheck to take a hostname out of rotation."
    )

    class Meta:
        ordering = ["host"]

    def save(self, *args, **kwargs) -> None:
        self.host = normalize_host(self.host)
        if not self.host:
            raise ValidationError({"host": "A domain needs a non-empty hostname."})
        if len(self.host) > MAX_HOST_LENGTH:
            raise ValidationError({"host": "Hostname is too long (max 253)."})
        if self.is_primary:
            # Only one primary per business - partial unique index avoided on
            # purpose so SQLite/MySQL behave identically; cheap and explicit.
            (
                Domain.objects.filter(business_id=self.business_id, is_primary=True)
                .exclude(pk=self.pk)
                .update(is_primary=False)
            )
        super().save(*args, **kwargs)

    def clean(self) -> None:
        self.host = normalize_host(self.host)
        if self.host and not re.fullmatch(
            r"\[[0-9a-f:]+\]|[^:\s]+", self.host  # IPv6 literal or a normal name
        ):
            raise ValidationError({"host": "Invalid hostname."})

    @classmethod
    def register(
        cls,
        host: str,
        business: Business,
        *,
        primary: bool = False,
        active: bool = True,
    ) -> "Domain":
        """Convenience used by seed scripts / onboarding flows."""
        obj = cls(host=host, business=business, is_primary=primary, is_active=active)
        obj.full_clean()
        obj.save()
        return obj

    def __str__(self) -> str:
        return f"{self.host} -> {self.business_id}"
