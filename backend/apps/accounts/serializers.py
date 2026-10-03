"""
Auth serializers: registration, JWT login, current user.

The login payload carries ``role`` at the top level so React can route
immediately (vendor -> /admin, super admin -> /superadmin, else storefront).
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.tenants.models import Business, Domain

from .models import BusinessMembership, CustomerStoreLink, User


class UserSerializer(serializers.ModelSerializer):
    """Profile shape returned to the SPA (never any secret material)."""

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
            "is_flagged",
            "date_joined",
        )
        read_only_fields = ("id", "email", "role", "is_flagged", "date_joined")


class RegisterSerializer(serializers.ModelSerializer):
    """
    Self-registration.

    * Customer  -> linked to the storefront currently being browsed
                   (``request.tenant``), so the vendor's dashboard shows them
                   after their first visit.
    * Vendor    -> may optionally bring a brand-new store along via
                   ``store_name`` (creates Business + ``<slug>.zone`` Domain +
                   OWNER membership atomically).
    * SUPER_ADMIN is deliberately NOT a choice: platform accounts are created
      by the operator, never through the public API.
    """

    password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )
    role = serializers.ChoiceField(
        # Deliberately a SUBSET of User.Role.choices: super_admin must never
        # be reachable through self-registration.
        choices=[
            (User.Role.CUSTOMER, User.Role.CUSTOMER.label),
            (User.Role.VENDOR, User.Role.VENDOR.label),
        ],
        default=User.Role.CUSTOMER,
        help_text="'customer' or 'vendor'; super admin accounts cannot self-register.",
    )
    store_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=150,
        help_text="Vendor only: creates a new store and its domain.",
    )

    class Meta:
        model = User
        fields = (
            "email",
            "password",
            "first_name",
            "last_name",
            "phone",
            "role",
            "store_name",
        )

    def validate_password(self, value):
        # Validate against the profile being typed (blocks password == email).
        provisional = User(
            email=str(self.initial_data.get("email", "")),
            first_name=str(self.initial_data.get("first_name", "")),
            last_name=str(self.initial_data.get("last_name", "")),
        )
        validate_password(value, user=provisional)
        return value

    @transaction.atomic
    def create(self, validated_data):
        role = validated_data.pop("role", User.Role.CUSTOMER)
        store_name = validated_data.pop("store_name", "").strip()
        password = validated_data.pop("password")
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) if request is not None else None

        user = User.objects.create_user(password=password, role=role, **validated_data)

        if role == User.Role.CUSTOMER and tenant is not None:
            # First interaction: remember which store this shopper signed up on.
            CustomerStoreLink.touch(user, tenant)

        if role == User.Role.VENDOR and store_name:
            zone = getattr(settings, "TENANT_DOMAIN_ZONE", "local-saas.com")
            business = Business.objects.create(
                name=store_name, owner=user, contact_email=user.email
            )
            Domain.register(
                host=f"{business.slug}.{zone}", business=business, primary=True
            )
            BusinessMembership.objects.create(
                user=user, business=business, role=BusinessMembership.Role.OWNER
            )

        return user


class LoginSerializer(TokenObtainPairSerializer):
    """
    JWT login keyed on ``email`` (our USERNAME_FIELD).

    Extends the standard ``{refresh, access}`` response with ``role`` (route
    the user) and ``user`` (hydrate the UI).
    """

    def validate(self, attrs):
        data = super().validate(attrs)  # {"refresh": ..., "access": ...}
        data["role"] = self.user.role
        data["user"] = UserSerializer(self.user).data
        return data
