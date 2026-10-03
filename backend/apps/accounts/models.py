"""
Accounts: the three user roles of the platform.

    CUSTOMER    - shops on one or more storefronts (cart, orders, reviews)
    VENDOR      - manages the dashboard of the store(s) they belong to
    SUPER_ADMIN - platform owner: oversees every business

Login identity is **email** (``USERNAME_FIELD = "email"``), which is what a
micro-business shopper expects; ``username`` stays optional for tooling.

Isolation rule enforced here: a vendor only sees a store through
:class:`BusinessMembership`, and a customer's per-store footprint is recorded
in :class:`CustomerStoreLink` - so "which stores did this customer interact
with?" is a first-class query, not a log dive.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.tenants.permissions import BusinessScopedModel


class UserManager(BaseUserManager):
    """
    Manager for the email-identified user model.

    Django's stock ``UserManager`` takes ``username`` as its first positional
    argument regardless of ``USERNAME_FIELD``, which is exactly backwards for
    this project - so it is replaced with an email-first API::

        User.objects.create_user("shopper@example.com", "s3cret")
        User.objects.create_superuser("root@example.com", "s3cret")
    """

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", self.model.Role.SUPER_ADMIN)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra_fields)

    def _create_user(self, email, password, **extra_fields):
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)  # respects database routing
        return user


class User(AbstractUser):
    """Single user table for all three roles (role column discriminates)."""

    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        VENDOR = "vendor", "Vendor"
        SUPER_ADMIN = "super_admin", "Super Admin"

    # Email is the login field, so it must be unique and never blank.
    email = models.EmailField("email address", unique=True)
    # Kept optional: it is a handle for staff/tooling, not the identity.
    username = models.CharField(
        max_length=150,
        unique=True,
        null=True,
        blank=True,
        help_text="Optional handle; email is the login field.",
    )

    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.CUSTOMER,
        db_index=True,
    )
    phone = models.CharField(max_length=32, blank=True)

    # Super admin moderation flags (spec: "flag a customer").
    is_flagged = models.BooleanField(default=False, db_index=True)
    flagged_reason = models.TextField(blank=True)
    flagged_at = models.DateTimeField(null=True, blank=True)
    # SET_NULL so unflagging/auditing survives the flagger's account removal.
    flagged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="flagged_users",
    )

    # Login happens with the email address.
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []  # createsuperuser asks email + password only

    objects = UserManager()

    class Meta:
        ordering = ["-date_joined"]

    def save(self, *args, **kwargs) -> None:
        if not self.email:
            raise ValidationError({"email": "Email is required (it is the login field)."})
        # Lower-case the domain part only (local parts are case sensitive).
        self.email = self.__class__.objects.normalize_email(self.email)
        super().save(*args, **kwargs)

    # -- role helpers ---------------------------------------------------------
    @property
    def is_customer(self) -> bool:
        return self.role == self.Role.CUSTOMER

    @property
    def is_vendor(self) -> bool:
        return self.role == self.Role.VENDOR

    @property
    def is_super_admin(self) -> bool:
        return self.role == self.Role.SUPER_ADMIN or self.is_superuser

    def flag(self, reason: str, by: "User | None" = None) -> None:
        """Flag this account (super admin action)."""
        self.is_flagged = True
        self.flagged_reason = reason
        self.flagged_at = timezone.now()
        self.flagged_by = by
        self.save(update_fields=["is_flagged", "flagged_reason", "flagged_at", "flagged_by"])

    def unflag(self) -> None:
        self.is_flagged = False
        self.flagged_reason = ""
        self.flagged_at = None
        self.flagged_by = None
        self.save(update_fields=["is_flagged", "flagged_reason", "flagged_at", "flagged_by"])


class BusinessMembership(TimeStampedModel):
    """
    Grants a vendor access to a store.

    Keeps the vendor<->store graph explicit: the dashboard authorises against
    *this* table (active membership + role), never against a claim in a JWT.
    """

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"
        STAFF = "staff", "Staff"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="business_memberships",
    )
    business = models.ForeignKey(
        "tenants.Business",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["business", "user"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "business"],
                name="membership_unique_per_user_business",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.business_id} ({self.role})"


class CustomerStoreLink(BusinessScopedModel):
    """
    "This customer has interacted with this store."

    Created on first contact (registration/cart/checkout) and refreshed on
    every order - it is how a vendor dashboard answers *which customers are
    mine* and how the platform answers *which stores did this customer visit*.
    """

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="store_links",
    )
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    orders_count = models.PositiveIntegerField(default=0)
    total_spent = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        ordering = ["-last_seen"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "business"],
                name="customer_store_link_unique",
            ),
        ]

    @classmethod
    def touch(cls, customer, business, *, spent=None) -> "CustomerStoreLink":
        """
        Idempotent 'record an interaction' helper.

        Checkout calls this with ``spent=<order total>``; everything else
        (cart add, review, storefront visit) calls it bare. Counters are
        updated with F() expressions so two concurrent checkouts cannot lose
        an increment, and ``update()`` sets ``last_seen`` explicitly because
        auto_now only fires on save().
        """
        link, _created = cls.objects.get_or_create(customer=customer, business=business)
        updates = {"last_seen": timezone.now()}
        if spent is not None:
            updates["orders_count"] = F("orders_count") + 1
            updates["total_spent"] = F("total_spent") + spent
        cls.objects.filter(pk=link.pk).update(**updates)
        link.refresh_from_db()
        return link

    @property
    def average_order_value(self) -> Decimal:
        if not self.orders_count:
            return Decimal("0.00")
        return (self.total_spent / self.orders_count).quantize(Decimal("0.01"))

    def __str__(self) -> str:
        return f"{self.customer_id} @ {self.business_id}"
