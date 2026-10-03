"""
Tests for the tenancy kernel:

    * hostname normalisation (port/case/trailing dot)
    * Domain -> Business resolution
    * RequestTenantMiddleware enforcement (JSON 404 / 403, exemptions, headers)
    * the data-isolation primitives (for_tenant / create_for_tenant / require_tenant)

Run with:  python backend/manage.py test apps.tenants
"""
from __future__ import annotations

from decimal import Decimal

from django.test import RequestFactory, TestCase

from apps.catalog.models import Product, Review
from apps.promotions.models import DiscountCode

from .models import Business, Domain, normalize_host
from .permissions import TenantRequiredError, require_tenant
from .resolvers import resolve_business, resolve_domain

INIT_URL = "/api/v1/storefront/init/"


class NormalizeHostTests(TestCase):
    def test_strips_port_and_lowercases(self):
        self.assertEqual(normalize_host("Acme.Local-SaaS.com:8000"), "acme.local-saas.com")

    def test_strips_trailing_dot(self):
        self.assertEqual(normalize_host("acme.local-saas.com."), "acme.local-saas.com")

    def test_takes_first_value_of_a_list(self):
        self.assertEqual(
            normalize_host("a.local-saas.com, b.local-saas.com"), "a.local-saas.com"
        )

    def test_tolerates_scheme_and_path(self):
        self.assertEqual(normalize_host("http://acme.local-saas.com/x"), "acme.local-saas.com")

    def test_handles_bracketed_ipv6(self):
        self.assertEqual(normalize_host("[::1]:8000"), "::1")

    def test_empty_input(self):
        self.assertEqual(normalize_host(None), "")
        self.assertEqual(normalize_host("   "), "")


class DomainModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.acme = Business.objects.create(name="Acme Threads", slug="acme")

    def test_host_is_normalised_on_save(self):
        domain = Domain.objects.create(host="ACME.local-saas.com:8000", business=self.acme)
        self.assertEqual(domain.host, "acme.local-saas.com")

    def test_slug_is_auto_generated_from_name(self):
        shop = Business.objects.create(name="Fresh Kicks & Co")
        self.assertEqual(shop.slug, "fresh-kicks-co")

    def test_slug_collisions_get_a_suffix(self):
        other = Business.objects.create(name="Acme Threads")
        self.assertNotEqual(other.slug, self.acme.slug)
        self.assertTrue(other.slug.startswith("acme-threads"))

    def test_resolver_returns_the_right_business(self):
        Domain.objects.create(host="acme.local-saas.com", business=self.acme)
        self.assertEqual(resolve_business("acme.local-saas.com:5173").pk, self.acme.pk)
        self.assertIsNone(resolve_domain("unknown.local-saas.com"))

    def test_inactive_domain_is_not_resolved(self):
        Domain.objects.create(host="acme.local-saas.com", business=self.acme, is_active=False)
        self.assertIsNone(resolve_domain("acme.local-saas.com"))


class MiddlewareTests(TestCase):
    """End-to-end through the real middleware chain (test client)."""

    @classmethod
    def setUpTestData(cls):
        cls.acme = Business.objects.create(name="Acme Threads", slug="acme")
        cls.nike = Business.objects.create(name="Nike Store", slug="nike")
        Domain.objects.create(host="acme.local-saas.com", business=cls.acme, is_primary=True)
        Domain.objects.create(host="nike.local-saas.com", business=cls.nike, is_primary=True)

    # -- happy path -----------------------------------------------------------
    def test_host_header_resolves_the_tenant(self):
        response = self.client.get(INIT_URL, HTTP_HOST="acme.local-saas.com:8000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["store"]["slug"], "acme")

    def test_forwarded_host_identifies_the_storefront_from_localhost(self):
        """The React app at localhost:5173 announces which store it renders."""
        response = self.client.get(
            INIT_URL,
            HTTP_HOST="localhost:8000",
            HTTP_X_FORWARDED_HOST="nike.local-saas.com:5173",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["store"]["slug"], "nike")

    def test_explicit_tenant_header_wins(self):
        response = self.client.get(
            INIT_URL,
            HTTP_HOST="localhost:8000",
            HTTP_X_FORWARDED_HOST="acme.local-saas.com",
            HTTP_X_TENANT_HOST="nike.local-saas.com",
        )
        self.assertEqual(response.json()["store"]["slug"], "nike")

    def test_response_varies_on_tenant_headers(self):
        response = self.client.get(INIT_URL, HTTP_HOST="acme.local-saas.com")
        self.assertIn("Host", response["Vary"])
        self.assertIn("X-Forwarded-Host", response["Vary"])

    # -- failures -------------------------------------------------------------
    def test_unknown_host_gets_json_404(self):
        response = self.client.get(INIT_URL, HTTP_HOST="nope.local-saas.com")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json()["error"], "store_not_found")
        self.assertEqual(response.json()["host"], "nope.local-saas.com")

    def test_localhost_without_tenant_header_gets_json_404(self):
        response = self.client.get(INIT_URL, HTTP_HOST="localhost:8000")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "store_not_found")

    def test_suspended_business_is_rejected_with_403(self):
        self.nike.status = Business.Status.SUSPENDED
        self.nike.save(update_fields=["status"])
        response = self.client.get(INIT_URL, HTTP_HOST="nike.local-saas.com")
        self.assertEqual(response.status_code, 403)
        payload = response.json()
        self.assertEqual(payload["error"], "store_unavailable")
        self.assertEqual(payload["store_status"], "suspended")

    def test_blocked_business_is_rejected_with_403(self):
        self.acme.status = Business.Status.BLOCKED
        self.acme.save(update_fields=["status"])
        response = self.client.get(INIT_URL, HTTP_HOST="acme.local-saas.com")
        self.assertEqual(response.status_code, 403)

    # -- exemptions -----------------------------------------------------------
    def test_admin_path_works_without_a_tenant(self):
        response = self.client.get("/admin/login/", HTTP_HOST="localhost:8000")
        self.assertEqual(response.status_code, 200)

    def test_admin_path_works_for_a_suspended_store(self):
        self.acme.status = Business.Status.SUSPENDED
        self.acme.save(update_fields=["status"])
        response = self.client.get("/admin/login/", HTTP_HOST="acme.local-saas.com")
        self.assertEqual(response.status_code, 200)

    def test_media_path_is_exempt_from_tenant_lookup(self):
        """Uploaded logos must load even when the host is unknown."""
        response = self.client.get("/media/brands/logos/missing.png", HTTP_HOST="localhost:8000")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"store_not_found", response.content)

    def test_tenant_is_still_attached_on_exempt_paths_when_resolvable(self):
        response = self.client.get("/admin/login/", HTTP_HOST="acme.local-saas.com")
        self.assertEqual(response.status_code, 200)


class IsolationPrimitivesTests(TestCase):
    """Queries must never be able to widen beyond one business."""

    @classmethod
    def setUpTestData(cls):
        cls.acme = Business.objects.create(name="Acme Threads", slug="acme")
        cls.nike = Business.objects.create(name="Nike Store", slug="nike")
        cls.product_acme = Product.objects.create(
            business=cls.acme, name="Acme Tee", price=Decimal("19.99")
        )
        cls.product_nike = Product.objects.create(
            business=cls.nike, name="Nike Tee", price=Decimal("29.99")
        )
        # Same code, two stores - isolation must keep them apart.
        cls.code_acme = DiscountCode.objects.create(
            business=cls.acme, code="SAVE10", discount_type="percentage", value=Decimal("10")
        )
        cls.code_nike = DiscountCode.objects.create(
            business=cls.nike, code="SAVE10", discount_type="flat", value=Decimal("5")
        )

    def test_for_tenant_returns_only_that_store(self):
        names = list(Product.objects.for_tenant(self.acme).values_list("name", flat=True))
        self.assertEqual(names, ["Acme Tee"])

    def test_for_tenant_none_returns_nothing(self):
        self.assertEqual(list(Product.objects.for_tenant(None)), [])

    def test_create_for_tenant_none_refuses(self):
        with self.assertRaises(TenantRequiredError):
            Product.objects.create_for_tenant(None, name="orphan", price=Decimal("1.00"))

    def test_create_for_tenant_stamps_the_business(self):
        product = Product.objects.create_for_tenant(
            self.nike, name="Forced Nike", price=Decimal("5.00")
        )
        self.assertEqual(product.business_id, self.nike.pk)

    def test_create_for_tenant_rejects_mismatched_business(self):
        with self.assertRaises(TenantRequiredError):
            Product.objects.create_for_tenant(
                self.acme, business_id=self.nike.pk, name="spoof", price=Decimal("1.00")
            )

    def test_voucher_is_scoped_to_its_store(self):
        code = DiscountCode.objects.for_tenant(self.acme).get(code="SAVE10")
        self.assertEqual(code.pk, self.code_acme.pk)
        self.assertEqual(code.discount_type, DiscountCode.DiscountType.PERCENTAGE)

    def test_same_code_in_another_store_is_invisible(self):
        self.assertFalse(
            DiscountCode.objects.for_tenant(self.acme).filter(pk=self.code_nike.pk).exists()
        )

    def test_require_tenant_raises_without_context(self):
        request = RequestFactory().get("/")
        with self.assertRaises(TenantRequiredError):
            require_tenant(request)

    def test_require_tenant_returns_the_business(self):
        request = RequestFactory().get("/")
        request.tenant = self.acme
        self.assertEqual(require_tenant(request).pk, self.acme.pk)

    def test_review_is_scoped_to_its_store(self):
        from apps.accounts.models import User

        customer = User.objects.create_user(email="shopper@example.com", password="x")
        Review.objects.create(product=self.product_acme, customer=customer, rating=5)
        self.assertEqual(Review.objects.for_tenant(self.acme).count(), 1)
        self.assertEqual(Review.objects.for_tenant(self.nike).count(), 0)
