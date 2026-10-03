"""
Auth API tests: registration (tenant linking), login (role payload), JWT flow.

Run with:  python backend/manage.py test apps.accounts
"""
from __future__ import annotations

from django.test import TestCase

from apps.tenants.models import Business, Domain

from .models import BusinessMembership, CustomerStoreLink, User

REGISTER_URL = "/api/v1/auth/register/"
LOGIN_URL = "/api/v1/auth/login/"
REFRESH_URL = "/api/v1/auth/token/refresh/"
ME_URL = "/api/v1/auth/me/"
PASSWORD = "s3cret-pass-1"


class RegistrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.acme = Business.objects.create(name="Acme Threads", slug="acme")
        cls.nike = Business.objects.create(name="Nike Store", slug="nike")
        Domain.objects.create(
            host="acme.local-saas.com", business=cls.acme, is_primary=True
        )
        Domain.objects.create(
            host="nike.local-saas.com", business=cls.nike, is_primary=True
        )

    def _register(self, payload, host="acme.local-saas.com"):
        return self.client.post(REGISTER_URL, payload, HTTP_HOST=host)

    def test_customer_registration_returns_tokens_and_role(self):
        response = self._register(
            {"email": "ann@shop.test", "password": PASSWORD, "first_name": "Ann"}
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertIn("access", payload)
        self.assertIn("refresh", payload)
        self.assertEqual(payload["role"], "customer")
        self.assertEqual(payload["user"]["email"], "ann@shop.test")

    def test_customer_registration_links_to_the_browsed_store_only(self):
        """Spec: a customer registration must link them to request.tenant."""
        self._register({"email": "ann@shop.test", "password": PASSWORD})
        ann = User.objects.get(email="ann@shop.test")
        links = list(
            CustomerStoreLink.objects.filter(customer=ann).values_list(
                "business_id", flat=True
            )
        )
        self.assertEqual(links, [self.acme.pk])  # acme - and never nike

    def test_registration_without_resolvable_tenant_creates_no_link(self):
        response = self._register(
            {"email": "bob@shop.test", "password": PASSWORD}, host="localhost:8000"
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertFalse(
            CustomerStoreLink.objects.filter(customer__email="bob@shop.test").exists()
        )

    def test_super_admin_cannot_be_self_registered(self):
        response = self._register(
            {
                "email": "evil@shop.test",
                "password": PASSWORD,
                "role": "super_admin",
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("role", response.json())
        self.assertFalse(User.objects.filter(email="evil@shop.test").exists())

    def test_vendor_registration_can_bring_a_new_store(self):
        response = self._register(
            {
                "email": "vendor@fresh.test",
                "password": PASSWORD,
                "role": "vendor",
                "store_name": "Fresh Kicks",
            },
            host="localhost:8000",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["role"], "vendor")

        business = Business.objects.get(name="Fresh Kicks")
        self.assertEqual(business.owner.email, "vendor@fresh.test")
        domain = business.domains.get(host="fresh-kicks.local-saas.com")
        self.assertTrue(domain.is_primary)
        membership = BusinessMembership.objects.get(
            user=business.owner, business=business
        )
        self.assertEqual(membership.role, BusinessMembership.Role.OWNER)

    def test_duplicate_email_is_rejected(self):
        self._register({"email": "ann@shop.test", "password": PASSWORD})
        response = self._register({"email": "ann@shop.test", "password": PASSWORD})
        self.assertEqual(response.status_code, 400)

    def test_password_too_short_is_rejected(self):
        response = self._register({"email": "ann@shop.test", "password": "123"})
        self.assertEqual(response.status_code, 400)

    def test_numeric_password_is_rejected(self):
        response = self._register({"email": "ann@shop.test", "password": "12345678"})
        self.assertEqual(response.status_code, 400)


class LoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = User.objects.create_user(
            email="ann@shop.test", password=PASSWORD, first_name="Ann"
        )
        cls.vendor = User.objects.create_user(
            email="vic@shop.test", password=PASSWORD, role=User.Role.VENDOR
        )
        cls.superadmin = User.objects.create_user(
            email="root@platform.test",
            password=PASSWORD,
            role=User.Role.SUPER_ADMIN,
        )

    def _login(self, email, password=PASSWORD):
        return self.client.post(
            LOGIN_URL,
            {"email": email, "password": password},
            HTTP_HOST="localhost:8000",
        )

    def test_login_as_customer_returns_role(self):
        response = self._login("ann@shop.test")
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["role"], "customer")
        self.assertEqual(payload["user"]["id"], self.customer.pk)
        self.assertTrue(payload["access"])
        self.assertTrue(payload["refresh"])

    def test_login_as_vendor_returns_role(self):
        """React routes on this: vendor -> /admin."""
        response = self._login("vic@shop.test")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["role"], "vendor")

    def test_login_as_super_admin_returns_role(self):
        """React routes on this: super admin -> /superadmin."""
        response = self._login("root@platform.test")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["role"], "super_admin")

    def test_wrong_password_is_401(self):
        response = self._login("ann@shop.test", password="nope-nope-1")
        self.assertEqual(response.status_code, 401)

    def test_unknown_email_is_401(self):
        response = self._login("ghost@shop.test")
        self.assertEqual(response.status_code, 401)

    def test_me_endpoint_accepts_a_bearer_token(self):
        login = self._login("ann@shop.test").json()
        response = self.client.get(
            ME_URL, HTTP_AUTHORIZATION=f"Bearer {login['access']}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "ann@shop.test")

    def test_me_endpoint_without_token_is_401(self):
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, 401)

    def test_refresh_endpoint_issues_a_new_access_token(self):
        login = self._login("ann@shop.test").json()
        response = self.client.post(REFRESH_URL, {"refresh": login["refresh"]})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["access"])

    def test_password_is_hashed_not_stored_in_clear(self):
        self._login("ann@shop.test")  # keep the test honest about the flow
        user = User.objects.get(email="ann@shop.test")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))
