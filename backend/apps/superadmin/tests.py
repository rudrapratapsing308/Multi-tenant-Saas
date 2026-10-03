"""
Super admin (platform) API tests.

The contract under test:

  * ONLY the SUPER_ADMIN role passes ``IsSuperAdmin`` - a vendor (even a
    store OWNER), a customer or an anonymous caller is refused (KEY).
  * Business metrics are per-store aggregates: acme's revenue never
    includes nike's, and a cancelled order never counts as revenue.
  * ``/api/v1/superadmin/`` is middleware-exempt: the API answers on any
    host - including plain ``localhost:8000`` with no storefront behind it
    (without the exemption the middleware would404 ``store_not_found``).
  * The status switch feeds the Module-3 middleware: SUSPENDED/BLOCKED
    makes that store's storefront answer403 ``store_unavailable``, while
    every other store keeps serving.
  * Ban = ``is_active=False`` = credentials stop working; flags are
    AUDITED (flagged_by / flagged_at), never just a boolean flip.

Run with:  python backend/manage.py test apps.superadmin
"""
from __future__ import annotations

import json

from django.test import TestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import BusinessMembership, User
from apps.catalog.models import Product
from apps.orders.models import Order, OrderItem
from apps.tenants.models import Business, Domain

BUSINESSES_URL = "/api/v1/superadmin/businesses/"
USERS_URL = "/api/v1/superadmin/users/"
INIT_URL = "/api/v1/storefront/init/"
LOGIN_URL = "/api/v1/auth/login/"
ACME = "acme.local-saas.com"
NIKE = "nike.local-saas.com"
LOCAL = "localhost:8000"   # no storefront - only works because we're exempt
PASSWORD = "s3cret-pass-1"


def bearer(user) -> str:
    return f"Bearer {RefreshToken.for_user(user).access_token}"


def make_order(business, customer, product, status=Order.Status.PENDING):
    order = Order.objects.create_for_tenant(
        business,
        customer=customer,
        customer_email=customer.email,
        customer_name=customer.get_full_name(),
        shipping_name="A Buyer",
        shipping_address1="1 Main Street",
        shipping_city="Metropolis",
        shipping_postal_code="12345",
        shipping_country="IN",
        subtotal=product.price,
        total=product.price,
        status=status,
    )
    OrderItem.objects.create_for_tenant(
        business,
        order=order,
        product=product,
        product_name=product.name,
        quantity=1,
        unit_price=product.price,
    )
    return order


class SuperAdminBase(TestCase):
    """
    Two stores, three roles, deterministic revenue numbers:

        acme: ann pending 19.99 + ann paid 19.99 + bob CANCELLED 19.99
              -> revenue 39.98, orders 2, distinct non-cancelled buyers 1
        nike: carol paid 99.00 -> revenue 99.00, orders 1, buyers 1
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.acme = Business.objects.create(name="Acme Threads", slug="acme")
        cls.nike = Business.objects.create(name="Nike Store", slug="nike")
        Domain.objects.create(host=ACME, business=cls.acme, is_primary=True)
        Domain.objects.create(host=NIKE, business=cls.nike, is_primary=True)

        cls.platform = User.objects.create_user(
            email="boss@platform.test", password=PASSWORD,
            role=User.Role.SUPER_ADMIN,
        )
        cls.owner = User.objects.create_user(
            email="owner@acme.test", password=PASSWORD, role=User.Role.VENDOR
        )
        BusinessMembership.objects.create(
            user=cls.owner, business=cls.acme,
            role=BusinessMembership.Role.OWNER,
        )
        cls.acme.owner = cls.owner
        cls.acme.save(update_fields=["owner"])

        cls.customer = User.objects.create_user(
            email="shopper@shop.test", password=PASSWORD
        )
        cls.ann = User.objects.create_user(email="ann@shop.test", password=PASSWORD)
        cls.bob = User.objects.create_user(email="bob@shop.test", password=PASSWORD)
        cls.carol = User.objects.create_user(
            email="carol@shop.test", password=PASSWORD
        )

        cls.tee = Product.objects.create(
            business=cls.acme, name="Acme Tee", price="19.99", stock=50
        )
        cls.shoe = Product.objects.create(
            business=cls.nike, name="Nike Shoe", price="99.00", stock=10
        )

        make_order(cls.acme, cls.ann, cls.tee)                                # pending
        make_order(cls.acme, cls.ann, cls.tee, status=Order.Status.PAID)      # paid
        make_order(cls.acme, cls.bob, cls.tee, status=Order.Status.CANCELLED) # excluded
        make_order(cls.nike, cls.carol, cls.shoe, status=Order.Status.PAID)   # nike

    def call(self, method, url, *, user=None, host=LOCAL, data=None):
        """JSON request helper. Superadmin calls default to a tenant-less host."""
        kwargs = {"HTTP_HOST": host}
        if user is not None:
            kwargs["HTTP_AUTHORIZATION"] = bearer(user)
        if data is not None:
            kwargs["content_type"] = "application/json"
            return getattr(self.client, method)(url, json.dumps(data), **kwargs)
        return getattr(self.client, method)(url, **kwargs)

    def login(self, email: str, password: str = PASSWORD):
        return self.client.post(
            LOGIN_URL,
            json.dumps({"email": email, "password": password}),
            content_type="application/json",
            HTTP_HOST=LOCAL,
        )


class SuperAdminPermissionTests(SuperAdminBase):
    """IsSuperAdmin: strict, role-only, tenant-agnostic."""

    def test_anonymous_is_401(self):
        response = self.client.get(BUSINESSES_URL, HTTP_HOST=LOCAL)
        self.assertEqual(response.status_code, 401)

    def test_vendor_cannot_reach_platform_endpoints(self):
        """KEY: even a store OWNER gets403 on every platform control."""
        attempts = (
            ("get", BUSINESSES_URL, None),
            ("get", USERS_URL, None),
            (
                "patch",
                f"{BUSINESSES_URL}{self.nike.pk}/status/",
                {"status": "suspended"},
            ),
            (
                "patch",
                f"{USERS_URL}{self.customer.pk}/",
                {"is_active": False},
            ),
        )
        for method, url, data in attempts:
            response = self.call(method, url, user=self.owner, data=data)
            self.assertEqual(
                response.status_code, 403, (method, url, response.content)
            )

    def test_customer_cannot_reach_platform_endpoints(self):
        for url in (BUSINESSES_URL, USERS_URL):
            response = self.call("get", url, user=self.customer)
            self.assertEqual(response.status_code, 403, response.content)

    def test_platform_api_works_without_any_tenant_host(self):
        """KEY: tenant-exempt path - localhost:8000 has no storefront, yet
        the endpoint answers instead of404 store_not_found."""
        response = self.call("get", BUSINESSES_URL, user=self.platform)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()), 2)


class SuperAdminBusinessTests(SuperAdminBase):
    """Business list metrics + the suspend/activate control switch."""

    def test_business_list_carries_per_store_metrics(self):
        """KEY: aggregates are per business and join-safe (no fan-out)."""
        response = self.call("get", BUSINESSES_URL, user=self.platform, host=ACME)
        self.assertEqual(response.status_code, 200, response.content)
        by_slug = {b["slug"]: b for b in response.json()}

        acme = by_slug["acme"]
        self.assertEqual(acme["revenue"], "39.98")     # cancelled order excluded
        self.assertEqual(acme["order_count"], 2)
        self.assertEqual(acme["customer_count"], 1)    # ann only
        self.assertEqual(acme["primary_domain"], ACME)
        self.assertEqual(acme["owner_email"], "owner@acme.test")

        nike = by_slug["nike"]
        self.assertEqual(nike["revenue"], "99.00")     # acme's money stays out
        self.assertEqual(nike["order_count"], 1)
        self.assertEqual(nike["customer_count"], 1)
        self.assertEqual(nike["primary_domain"], NIKE)
        self.assertIsNone(nike["owner_email"])

    def test_status_filter(self):
        suspended = self.call(
            "get", f"{BUSINESSES_URL}?status=suspended", user=self.platform
        )
        self.assertEqual(suspended.status_code, 200)
        self.assertEqual(suspended.json(), [])

        active = self.call("get", f"{BUSINESSES_URL}?status=active", user=self.platform)
        self.assertEqual(active.status_code, 200)
        self.assertEqual(len(active.json()), 2)

    def test_unknown_status_filter_is_400(self):
        response = self.call("get", f"{BUSINESSES_URL}?status=nope", user=self.platform)
        self.assertEqual(response.status_code, 400)

    def test_suspend_blocks_storefront_and_activate_restores_it(self):
        """KEY: the status switch is exactly what the Module-3 middleware
        enforces - nike goes dark, acme keeps serving, nike comes back."""
        response = self.call(
            "patch",
            f"{BUSINESSES_URL}{self.nike.pk}/status/",
            user=self.platform,
            data={"status": "suspended"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "suspended")

        blocked = self.client.get(INIT_URL, HTTP_HOST=NIKE)
        self.assertEqual(blocked.status_code, 403)
        self.assertIn("store_unavailable", blocked.content.decode())

        untouched = self.client.get(INIT_URL, HTTP_HOST=ACME)
        self.assertEqual(untouched.status_code, 200)   # suspending nike != acme

        response = self.call(
            "patch",
            f"{BUSINESSES_URL}{self.nike.pk}/status/",
            user=self.platform,
            data={"status": "active"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        restored = self.client.get(INIT_URL, HTTP_HOST=NIKE)
        self.assertEqual(restored.status_code, 200)

    def test_invalid_status_value_is_400(self):
        response = self.call(
            "patch",
            f"{BUSINESSES_URL}{self.acme.pk}/status/",
            user=self.platform,
            data={"status": "obliterated"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.json())


class SuperAdminUserTests(SuperAdminBase):
    """Global user list + moderation (flag / ban), with privilege-escalation rails."""

    def test_user_list_exposes_roles(self):
        response = self.call("get", USERS_URL, user=self.platform)
        self.assertEqual(response.status_code, 200, response.content)
        roles = {u["email"]: u["role"] for u in response.json()}
        self.assertEqual(roles["boss@platform.test"], User.Role.SUPER_ADMIN)
        self.assertEqual(roles["owner@acme.test"], User.Role.VENDOR)
        self.assertEqual(roles["shopper@shop.test"], User.Role.CUSTOMER)

    def test_flagging_records_who_and_when(self):
        """KEY: flags are AUDITED (flagged_by/flagged_at), not bare booleans."""
        response = self.call(
            "patch",
            f"{USERS_URL}{self.customer.pk}/",
            user=self.platform,
            data={"is_flagged": True, "flagged_reason": "Chargeback dispute"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload["is_flagged"])
        self.assertIsNotNone(payload["flagged_at"])

        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_flagged)
        self.assertEqual(self.customer.flagged_reason, "Chargeback dispute")
        self.assertEqual(self.customer.flagged_by_id, self.platform.pk)
        self.assertIsNotNone(self.customer.flagged_at)

    def test_flag_without_reason_is_400(self):
        response = self.call(
            "patch",
            f"{USERS_URL}{self.customer.pk}/",
            user=self.platform,
            data={"is_flagged": True},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("flagged_reason", response.json())

    def test_unflag_clears_the_audit_trail(self):
        self.customer.flag("old reason", by=self.platform)
        response = self.call(
            "patch",
            f"{USERS_URL}{self.customer.pk}/",
            user=self.platform,
            data={"is_flagged": False},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_flagged)
        self.assertEqual(self.customer.flagged_reason, "")
        self.assertIsNone(self.customer.flagged_at)
        self.assertIsNone(self.customer.flagged_by_id)

    def test_ban_prevents_login(self):
        """KEY: ban = is_active=False -> the credentials stop working."""
        before = self.login(self.customer.email)
        self.assertEqual(before.status_code, 200, before.content)

        response = self.call(
            "patch",
            f"{USERS_URL}{self.customer.pk}/",
            user=self.platform,
            data={"is_active": False},
        )
        self.assertEqual(response.status_code, 200, response.content)

        after = self.login(self.customer.email)
        self.assertEqual(after.status_code, 401, after.content)

    def test_superadmin_cannot_deactivate_own_account(self):
        """Safety rail: the platform cannot lock itself out by accident."""
        response = self.call(
            "patch",
            f"{USERS_URL}{self.platform.pk}/",
            user=self.platform,
            data={"is_active": False},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("is_active", response.json())

    def test_role_and_email_are_not_writable(self):
        """KEY: no privilege escalation through the moderation endpoint."""
        response = self.call(
            "patch",
            f"{USERS_URL}{self.customer.pk}/",
            user=self.platform,
            data={"role": User.Role.SUPER_ADMIN, "email": "hijacked@evil.test"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.role, User.Role.CUSTOMER)
        self.assertEqual(self.customer.email, "shopper@shop.test")

    def test_put_and_delete_are_not_allowed(self):
        """Moderation is GET+PATCH only: ban/flag, never delete/replace."""
        url = f"{USERS_URL}{self.customer.pk}/"
        put = self.call("put", url, user=self.platform, data={})
        self.assertEqual(put.status_code, 405)
        delete = self.call("delete", url, user=self.platform)
        self.assertEqual(delete.status_code, 405)
