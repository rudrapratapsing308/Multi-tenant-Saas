"""
Tests for GET /api/v1/storefront/init/ - the payload the React frontend
boots from.

Run with:  python backend/manage.py test apps.storefront
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.tenants.models import Business, Domain

from .models import DEFAULT_THEME, Banner, BrandConfig

INIT_URL = "/api/v1/storefront/init/"


class StorefrontInitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.acme = Business.objects.create(name="Acme Threads", slug="acme")
        cls.nike = Business.objects.create(name="Nike Store", slug="nike")
        cls.plain = Business.objects.create(name="Plain Shop", slug="plain")
        Domain.objects.create(host="acme.local-saas.com", business=cls.acme, is_primary=True)
        Domain.objects.create(host="nike.local-saas.com", business=cls.nike, is_primary=True)
        Domain.objects.create(host="plain.local-saas.com", business=cls.plain, is_primary=True)

        cls.brand = BrandConfig.objects.create(
            business=cls.acme,
            brand_name="Acme Threads",
            tagline="Wear it proud",
            primary_color="#ff6600",
            secondary_color="#222222",
            accent_color="#00aa55",
        )
        now = timezone.now()
        Banner.objects.create(
            business=cls.acme, title="Summer Sale", is_active=True, position=1
        )
        Banner.objects.create(
            business=cls.acme,
            title="Expired deal",
            is_active=True,
            starts_at=now - timedelta(days=30),
            ends_at=now - timedelta(days=1),
        )
        Banner.objects.create(
            business=cls.acme,
            title="Upcoming deal",
            is_active=True,
            starts_at=now + timedelta(days=7),
        )
        Banner.objects.create(
            business=cls.acme, title="Turned off", is_active=False
        )
        Banner.objects.create(
            business=cls.nike, title="Nike only banner", is_active=True
        )

    def test_url_resolves(self):
        self.assertEqual(reverse("storefront:init"), INIT_URL)

    def test_returns_brand_identity(self):
        payload = self.client.get(INIT_URL, HTTP_HOST="acme.local-saas.com").json()
        self.assertEqual(payload["brand"]["brand_name"], "Acme Threads")
        self.assertEqual(payload["brand"]["tagline"], "Wear it proud")
        self.assertIsNone(payload["brand"]["logo_url"])  # none uploaded yet

    def test_returns_theme_colors(self):
        payload = self.client.get(INIT_URL, HTTP_HOST="acme.local-saas.com").json()
        self.assertEqual(
            payload["theme"],
            {
                "primary_color": "#ff6600",
                "secondary_color": "#222222",
                "accent_color": "#00aa55",
            },
        )

    def test_returns_store_identity(self):
        payload = self.client.get(INIT_URL, HTTP_HOST="acme.local-saas.com:8000").json()
        self.assertEqual(payload["store"]["slug"], "acme")
        self.assertEqual(payload["store"]["name"], "Acme Threads")
        self.assertEqual(payload["store"]["host"], "acme.local-saas.com")
        self.assertEqual(payload["store"]["currency"], "USD")
        self.assertIn("server_time", payload)

    def test_only_current_banners_are_returned(self):
        payload = self.client.get(INIT_URL, HTTP_HOST="acme.local-saas.com").json()
        titles = [banner["title"] for banner in payload["banners"]]
        self.assertEqual(titles, ["Summer Sale"])  # expired/upcoming/off excluded

    def test_banners_of_other_stores_never_leak(self):
        payload = self.client.get(INIT_URL, HTTP_HOST="acme.local-saas.com").json()
        titles = [banner["title"] for banner in payload["banners"]]
        self.assertNotIn("Nike only banner", titles)

    def test_store_without_brand_config_still_boots_with_defaults(self):
        payload = self.client.get(INIT_URL, HTTP_HOST="plain.local-saas.com").json()
        self.assertEqual(payload["brand"]["brand_name"], "Plain Shop")
        self.assertEqual(payload["theme"], dict(DEFAULT_THEME))
        self.assertEqual(payload["banners"], [])

    def test_unknown_host_is_404_json(self):
        response = self.client.get(INIT_URL, HTTP_HOST="ghost.local-saas.com")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "store_not_found")

    def test_never_renders_html(self):
        response = self.client.get(INIT_URL, HTTP_HOST="acme.local-saas.com")
        self.assertNotIn("text/html", response["Content-Type"])
