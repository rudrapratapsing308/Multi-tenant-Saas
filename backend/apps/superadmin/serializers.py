"""
Super admin serializers: platform-wide reads and control writes.

Design notes:

* ``BusinessSerializer`` consumes *annotated* metrics (revenue, order and
  customer counts) produced by the view's queryset - one aggregate query
  over all businesses instead of N+1 per row.
* ``PlatformUserSerializer`` exposes exactly the moderation surface the spec
  asks for (view role, flag, ban) and keeps ``role``/``email`` read-only:
  platform accounts are operator-created, and promoting yourself through a
  PATCH would be a privilege-escalation hole.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.accounts.models import User
from apps.tenants.models import Business


class BusinessSerializer(serializers.ModelSerializer):
    """Read model for the platform dashboard (all fields read-only)."""

    owner_email = serializers.EmailField(
        source="owner.email", read_only=True, allow_null=True
    )
    primary_domain = serializers.SerializerMethodField()
    revenue = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    order_count = serializers.IntegerField(read_only=True)
    customer_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Business
        fields = (
            "id",
            "name",
            "slug",
            "status",
            "contact_email",
            "currency",
            "owner",
            "owner_email",
            "primary_domain",
            "revenue",
            "order_count",
            "customer_count",
            "created_at",
        )
        read_only_fields = fields  # list-only; status changes go via /status/

    def get_primary_domain(self, obj) -> str | None:
        # ``domains`` is a related MANAGER - list() consumes the prefetch
        # cache in one query instead of N+1 lookups per business.
        domains = list(obj.domains.all())
        primary = next((d for d in domains if d.is_primary), None)
        if primary is None and domains:
            primary = domains[0]
        return primary.host if primary else None


class BusinessStatusSerializer(serializers.Serializer):
    """Body of ``PATCH /api/v1/superadmin/businesses/<id>/status/``."""

    status = serializers.ChoiceField(choices=Business.Status.choices)


class PlatformUserSerializer(serializers.ModelSerializer):
    """
    Global user list + moderation (flag / ban).

    ``flagged_at``/``flagged_by`` are stamped by ``User.flag()`` in
    ``update()``, never accepted from the client.
    """

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "is_flagged",
            "flagged_reason",
            "flagged_at",
            "flagged_by",
            "is_superuser",
            "date_joined",
        )
        read_only_fields = (
            "id",
            "email",
            "role",
            "flagged_at",
            "flagged_by",
            "is_superuser",
            "date_joined",
        )

    def update(self, instance, validated_data):
        flag_state = validated_data.pop("is_flagged", None)
        reason = validated_data.pop("flagged_reason", None)

        if flag_state is True and not (reason or "").strip():
            raise serializers.ValidationError(
                {"flagged_reason": "A reason is required when flagging a user."}
            )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Route flagging through the model helper so flagged_at/flagged_by
        # stay consistent no matter which surface sets the flag.
        if flag_state is True:
            instance.flag(reason.strip(), by=self.context["request"].user)
        elif flag_state is False:
            instance.unflag()
        elif reason is not None:
            instance.flagged_reason = reason
            instance.save(update_fields=["flagged_reason"])

        return instance
