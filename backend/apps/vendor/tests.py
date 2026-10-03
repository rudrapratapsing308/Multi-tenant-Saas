"""
Vendor dashboard tests: role gate + membership gate + tenant-scoped queryset.

The flagship tests are ``test_vendor_token_from_store_a_cannot_read_store_b``
and ``test_detail_of_other_stores_order_is_404``.

Run with:  python backend/manage.py test apps.vendor
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.test.client import MULTIPART_CONTENT
from PIL import Image as PILImage
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import BusinessMembership, CustomerStoreLink, User
from apps.catalog.models import Category, Product
from apps.orders.models import Order, OrderItem
from apps.promotions.models import DiscountCode
from apps.storefront.models import BrandConfig
from apps.tenants.models import Business, Domain

VENDOR_ORDERS_URL = "/api/v1/vendor/orders/"
VENDOR_PRODUCTS_URL = "/api/v1/vendor/products/"
VENDOR_CATEGORIES_URL = "/api/v1/vendor/categories/"
VENDOR_PROMOTIONS_URL = "/api/v1/vendor/promotions/"
VENDOR_ANALYTICS_URL = "/api/v1/vendor/analytics/"
VENDOR_SETTINGS_URL = "/api/v1/vendor/settings/"
INIT_URL = "/api/v1/storefront/init/"
ACME = "acme.local-saas.com"
NIKE = "nike.local-saas.com"
PASSWORD = "s3cret-pass-1"

# A valid 1x1 GIF that Pillow decodes (DRF's ImageField accepts it).
TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
    b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)


def oversized_image() -> bytes:
    """A *valid* image that blows past the 2 MB cap (~2.4 MB of raw BMP)."""
    buffer = io.BytesIO()
    PILImage.new("RGB", (900, 900), (10, 20, 30)).save(buffer, format="BMP")
    return buffer.getvalue()


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


class VendorOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.acme = Business.objects.create(name="Acme Threads", slug="acme")
        cls.nike = Business.objects.create(name="Nike Store", slug="nike")
        Domain.objects.create(host=ACME, business=cls.acme, is_primary=True)
        Domain.objects.create(host=NIKE, business=cls.nike, is_primary=True)

        cls.owner = User.objects.create_user(
            email="owner@acme.test", password=PASSWORD, role=User.Role.VENDOR
        )
        BusinessMembership.objects.create(
            user=cls.owner, business=cls.acme,
            role=BusinessMembership.Role.OWNER,
        )
        cls.outsider = User.objects.create_user(
            email="owner@nike.test", password=PASSWORD, role=User.Role.VENDOR
        )
        BusinessMembership.objects.create(
            user=cls.outsider, business=cls.nike,
            role=BusinessMembership.Role.OWNER,
        )
        # Membership, but the WRONG role: must still be refused.
        cls.sales_clerk = User.objects.create_user(
            email="clerk@acme.test", password=PASSWORD  # role = customer
        )
        BusinessMembership.objects.create(
            user=cls.sales_clerk, business=cls.acme,
            role=BusinessMembership.Role.STAFF,
        )

        cls.ann = User.objects.create_user(
            email="ann@shop.test", password=PASSWORD, first_name="Ann"
        )
        cls.bob = User.objects.create_user(email="bob@shop.test", password=PASSWORD)
        cls.carol = User.objects.create_user(
            email="carol@shop.test", password=PASSWORD
        )

        cls.tee = Product.objects.create(
            business=cls.acme, name="Acme Tee", price="19.99", stock=50
        )
        cls.shoe = Product.objects.create(
            business=cls.nike, name="Nike Shoe", price="99.00", stock=50
        )

        cls.acme_order1 = make_order(cls.acme, cls.ann, cls.tee)
        cls.acme_order2 = make_order(
            cls.acme, cls.bob, cls.tee, status=Order.Status.PAID
        )
        cls.nike_order = make_order(cls.nike, cls.carol, cls.shoe)

    def _get(self, user, host=ACME, suffix=""):
        return self.client.get(
            VENDOR_ORDERS_URL + suffix,
            HTTP_HOST=host,
            HTTP_AUTHORIZATION=bearer(user),
        )

    # -- gates -----------------------------------------------------------------
    def test_anonymous_is_401(self):
        response = self.client.get(VENDOR_ORDERS_URL, HTTP_HOST=ACME)
        self.assertEqual(response.status_code, 401)

    def test_customer_role_is_rejected_even_with_membership(self):
        response = self._get(self.sales_clerk)
        self.assertEqual(response.status_code, 403)

    def test_vendor_token_from_store_a_cannot_read_store_b(self):
        """KEY: owner of acme against the nike host -> 403, no rows read."""
        response = self._get(self.owner, host=NIKE)
        self.assertEqual(response.status_code, 403)

    # -- reads -----------------------------------------------------------------
    def test_vendor_lists_only_their_stores_orders(self):
        """KEY: acme's vendor must not see nike's orders (or vice versa)."""
        response = self._get(self.owner, host=ACME)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(len(payload), 2)
        numbers = {o["order_number"] for o in payload}
        self.assertEqual(
            numbers, {self.acme_order1.order_number, self.acme_order2.order_number}
        )
        self.assertNotIn(self.nike_order.order_number, numbers)

    def test_the_other_vendor_sees_only_their_own(self):
        response = self._get(self.outsider, host=NIKE)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["order_number"], self.nike_order.order_number)

    def test_order_payload_contains_customer_contact(self):
        response = self._get(self.owner, host=ACME)
        first = response.json()[0]
        self.assertIn("customer_email", first)
        self.assertIn("items", first)
        self.assertEqual(first["items"][0]["product_name"], "Acme Tee")

    def test_detail_of_own_store_order(self):
        response = self._get(self.owner, suffix=f"{self.acme_order1.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["order_number"], self.acme_order1.order_number)

    def test_detail_of_other_stores_order_is_404(self):
        """KEY: knowing the id must not be enough (tenant-scoped queryset)."""
        response = self._get(self.owner, suffix=f"{self.nike_order.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_status_filter(self):
        response = self._get(self.owner, suffix="?status=paid")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["order_number"], self.acme_order2.order_number)

    def test_unknown_status_filter_is_400(self):
        response = self._get(self.owner, suffix="?status=bogus")
        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.json())


# ---------------------------------------------------------------------------
# Module 4.5: catalog/promotions CRUD, order status, analytics, settings
# ---------------------------------------------------------------------------

class TwoStoreVendorBase(TestCase):
    """
    Shared world for the Module 4.5 endpoints: two tenants, one OWNER vendor
    per store, and a plain customer - every test answers "can store A touch
    store B's rows?" with a resounding no.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.acme = Business.objects.create(name="Acme Threads", slug="acme")
        cls.nike = Business.objects.create(name="Nike Store", slug="nike")
        Domain.objects.create(host=ACME, business=cls.acme, is_primary=True)
        Domain.objects.create(host=NIKE, business=cls.nike, is_primary=True)

        cls.owner = User.objects.create_user(
            email="owner@acme.test", password=PASSWORD, role=User.Role.VENDOR
        )
        BusinessMembership.objects.create(
            user=cls.owner, business=cls.acme,
            role=BusinessMembership.Role.OWNER,
        )
        cls.outsider = User.objects.create_user(
            email="owner@nike.test", password=PASSWORD, role=User.Role.VENDOR
        )
        BusinessMembership.objects.create(
            user=cls.outsider, business=cls.nike,
            role=BusinessMembership.Role.OWNER,
        )
        cls.customer = User.objects.create_user(
            email="shopper@shop.test", password=PASSWORD
        )

    def call(self, method, url, *, user=None, host=ACME, data=None, multipart=False):
        kwargs = {"HTTP_HOST": host}
        if user is not None:
            kwargs["HTTP_AUTHORIZATION"] = bearer(user)
        if multipart:
            # Django's client only multipart-encodes inside post(); put/patch
            # send force_bytes(data) RAW - a dict would go out as its repr and
            # the server would parse an empty body. So encode the payload
            # ourselves exactly the way post() does, then hand over bytes.
            kwargs["content_type"] = MULTIPART_CONTENT
            body = (
                data
                if method == "post"  # post() encodes internally (identity check)
                else self.client._encode_data(data, MULTIPART_CONTENT)
            )
            return getattr(self.client, method)(url, body, **kwargs)
        if data is not None:
            kwargs["content_type"] = "application/json"
            return getattr(self.client, method)(url, json.dumps(data), **kwargs)
        return getattr(self.client, method)(url, **kwargs)


class VendorCatalogCRUDTests(TwoStoreVendorBase):
    """Products & categories: full CRUD, every query scoped to request.tenant."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tees = Category.objects.create(business=cls.acme, name="Tees")
        cls.kicks = Category.objects.create(business=cls.nike, name="Kicks")
        cls.tee = Product.objects.create(
            business=cls.acme, name="Acme Tee", price="19.99", stock=40,
            category=cls.tees,
        )
        cls.shoe = Product.objects.create(
            business=cls.nike, name="Nike Shoe", price="99.00", stock=10,
            category=cls.kicks,
        )

    # -- products --------------------------------------------------------------
    def test_product_list_is_scoped_to_own_store(self):
        """KEY: acme's vendor must never see nike's products (or vice versa)."""
        response = self.call("get", VENDOR_PRODUCTS_URL, user=self.owner)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["name"], "Acme Tee")

    def test_retrieve_foreign_product_is_404(self):
        response = self.call(
            "get", f"{VENDOR_PRODUCTS_URL}{self.shoe.pk}/", user=self.owner
        )
        self.assertEqual(response.status_code, 404)

    def test_create_product_auto_slugs_and_defaults(self):
        response = self.call(
            "post", VENDOR_PRODUCTS_URL, user=self.owner,
            data={
                "name": "Acme Hoodie", "price": "49.99", "stock": 12,
                "category": self.tees.pk,
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload["slug"], "acme-hoodie")
        self.assertTrue(payload["is_active"])
        product = Product.objects.get(pk=payload["id"])
        self.assertEqual(product.business_id, self.acme.pk)
        self.assertEqual(product.category_id, self.tees.pk)

    def test_create_product_with_foreign_category_is_rejected(self):
        """KEY: an id from another store fails FIELD validation (400)."""
        response = self.call(
            "post", VENDOR_PRODUCTS_URL, user=self.owner,
            data={
                "name": "Mole Item", "price": "1.00", "stock": 1,
                "category": self.kicks.pk,
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("category", response.json())
        self.assertFalse(Product.objects.filter(name="Mole Item").exists())

    def test_duplicate_product_name_is_rejected_in_the_same_store(self):
        """KEY: slugs are per-tenant unique - duplicates answer 400, not -2."""
        response = self.call(
            "post", VENDOR_PRODUCTS_URL, user=self.owner,
            data={"name": "Acme Tee", "price": "9.99", "stock": 3},
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_identical_name_is_allowed_in_another_store(self):
        """KEY: the SAME name/slug may exist on a different tenant."""
        response = self.call(
            "post", VENDOR_PRODUCTS_URL, user=self.outsider, host=NIKE,
            data={"name": "Acme Tee", "price": "9.99", "stock": 3},
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload["slug"], "acme-tee")
        self.assertEqual(
            Product.objects.get(pk=payload["id"]).business_id, self.nike.pk
        )

    def test_update_own_product(self):
        response = self.call(
            "patch", f"{VENDOR_PRODUCTS_URL}{self.tee.pk}/", user=self.owner,
            data={"price": "24.99", "is_featured": True},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.tee.refresh_from_db()
        self.assertEqual(str(self.tee.price), "24.99")
        self.assertTrue(self.tee.is_featured)

    def test_vendor_cannot_update_another_stores_product(self):
        """KEY: store A's vendor PATCHes store B's product id -> 404, no write."""
        response = self.call(
            "patch", f"{VENDOR_PRODUCTS_URL}{self.shoe.pk}/", user=self.owner,
            data={"price": "1.00"},
        )
        self.assertEqual(response.status_code, 404)
        self.shoe.refresh_from_db()
        self.assertEqual(str(self.shoe.price), "99.00")

    def test_vendor_cannot_delete_another_stores_product(self):
        """KEY: same gate on DELETE - the row stays untouched."""
        response = self.call(
            "delete", f"{VENDOR_PRODUCTS_URL}{self.shoe.pk}/", user=self.owner
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Product.objects.filter(pk=self.shoe.pk).exists())

    def test_delete_product_keeps_order_history(self):
        """KEY: OrderItem snapshots survive product deletion (SET_NULL)."""
        order = make_order(self.acme, self.customer, self.tee)
        response = self.call(
            "delete", f"{VENDOR_PRODUCTS_URL}{self.tee.pk}/", user=self.owner
        )
        self.assertEqual(response.status_code, 204, response.content)
        item = OrderItem.objects.get(order=order)
        self.assertIsNone(item.product_id)          # link gone...
        self.assertEqual(item.product_name, "Acme Tee")   # ...history intact
        self.assertEqual(str(item.unit_price), "19.99")

    def test_compare_at_price_below_price_is_rejected(self):
        """Model rule (clean()) enforced through the API via full_clean()."""
        response = self.call(
            "patch", f"{VENDOR_PRODUCTS_URL}{self.tee.pk}/", user=self.owner,
            data={"compare_at_price": "5.00"},
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("compare_at_price", response.json())

    def test_customer_role_is_rejected_on_vendor_crud(self):
        """KEY: customers get403 on the whole vendor surface."""
        for method, url, data in (
            ("get", VENDOR_PRODUCTS_URL, None),
            ("post", VENDOR_PRODUCTS_URL, {"name": "Nope", "price": "1.00"}),
            ("get", VENDOR_CATEGORIES_URL, None),
        ):
            response = self.call(method, url, user=self.customer, data=data)
            self.assertEqual(response.status_code, 403, (url, response.content))

    def test_anonymous_is_401(self):
        response = self.call("get", VENDOR_PRODUCTS_URL)
        self.assertEqual(response.status_code, 401)

    # -- categories ------------------------------------------------------------
    def test_category_list_is_scoped_to_own_store(self):
        response = self.call("get", VENDOR_CATEGORIES_URL, user=self.owner)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["name"], "Tees")
        self.assertEqual(payload[0]["product_count"], 1)   # the tee

    def test_create_category_auto_slugs(self):
        response = self.call(
            "post", VENDOR_CATEGORIES_URL, user=self.owner,
            data={"name": "Summer Drop"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload["slug"], "summer-drop")
        self.assertEqual(
            Category.objects.get(pk=payload["id"]).business_id, self.acme.pk
        )

    def test_foreign_parent_category_is_rejected(self):
        """KEY: sub-categories cannot cross the tenant line (400)."""
        response = self.call(
            "post", VENDOR_CATEGORIES_URL, user=self.owner,
            data={"name": "Sub", "parent": self.kicks.pk},
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("parent", response.json())

    def test_duplicate_category_name_is_rejected_without_crashing(self):
        """Regression guard: Category.save has no uniquifier - a missed
        duplicate would surface as IntegrityError (500), not400."""
        response = self.call(
            "post", VENDOR_CATEGORIES_URL, user=self.owner, data={"name": "Tees"}
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_same_category_name_allowed_in_another_store(self):
        response = self.call(
            "post", VENDOR_CATEGORIES_URL, user=self.outsider, host=NIKE,
            data={"name": "Tees"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["slug"], "tees")

    def test_delete_category_unassigns_products(self):
        """KEY: Product.category is SET_NULL - deleting 'Tees' keeps sales."""
        response = self.call(
            "delete", f"{VENDOR_CATEGORIES_URL}{self.tees.pk}/", user=self.owner
        )
        self.assertEqual(response.status_code, 204, response.content)
        self.tee.refresh_from_db()
        self.assertIsNone(self.tee.category_id)
        self.assertTrue(Product.objects.filter(pk=self.tee.pk).exists())

    def test_category_cannot_be_its_own_parent(self):
        """Model rule still enforced after the create-path clean() fix."""
        response = self.call(
            "patch", f"{VENDOR_CATEGORIES_URL}{self.tees.pk}/", user=self.owner,
            data={"parent": self.tees.pk},
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("parent", response.json())


class VendorPromotionCRUDTests(TwoStoreVendorBase):
    """Discount codes: full CRUD, unique PER STORE, model rules enforced."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.save10 = DiscountCode.objects.create(
            business=cls.acme, code="SAVE10",
            discount_type=DiscountCode.DiscountType.PERCENTAGE, value=10,
        )
        cls.secret5 = DiscountCode.objects.create(
            business=cls.nike, code="SECRET5",
            discount_type=DiscountCode.DiscountType.FLAT, value=5,
        )

    def test_voucher_list_is_scoped_to_own_store(self):
        """KEY: codes with the same name can exist per store; lists don't mix."""
        mine = self.call("get", VENDOR_PROMOTIONS_URL, user=self.owner)
        self.assertEqual(mine.status_code, 200, mine.content)
        self.assertEqual([v["code"] for v in mine.json()], ["SAVE10"])

        theirs = self.call(
            "get", VENDOR_PROMOTIONS_URL, user=self.outsider, host=NIKE
        )
        self.assertEqual(theirs.status_code, 200, theirs.content)
        self.assertEqual([v["code"] for v in theirs.json()], ["SECRET5"])

    def test_create_voucher_uppercases_the_code(self):
        response = self.call(
            "post", VENDOR_PROMOTIONS_URL, user=self.owner,
            data={"code": "spring10", "discount_type": "percentage", "value": "15"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload["code"], "SPRING10")   # model save() normalises
        self.assertEqual(payload["display_value"], "15.00%")
        self.assertEqual(
            DiscountCode.objects.get(pk=payload["id"]).business_id, self.acme.pk
        )

    def test_duplicate_code_in_same_store_is_rejected(self):
        response = self.call(
            "post", VENDOR_PROMOTIONS_URL, user=self.owner,
            data={"code": "SAVE10", "discount_type": "percentage", "value": "10"},
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_lowercase_duplicate_code_is_rejected(self):
        """KEY: save() uppercases codes, so validation must compare the
        NORMALISED form - raw lowercase would slip past full_clean() and
        explode as IntegrityError (500) on insert."""
        response = self.call(
            "post", VENDOR_PROMOTIONS_URL, user=self.owner,
            data={"code": "  save10  ", "discount_type": "percentage", "value": "10"},
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_same_code_allowed_in_another_store(self):
        """KEY: nike may register SAVE10 even though acme owns it there."""
        response = self.call(
            "post", VENDOR_PROMOTIONS_URL, user=self.outsider, host=NIKE,
            data={"code": "SAVE10", "discount_type": "percentage", "value": "10"},
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_percentage_over_100_is_rejected(self):
        """Model clean() runs through full_clean() - value rule preserved."""
        response = self.call(
            "post", VENDOR_PROMOTIONS_URL, user=self.owner,
            data={"code": "MAXED", "discount_type": "percentage", "value": "150"},
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("value", response.json())

    def test_window_must_end_after_it_starts(self):
        response = self.call(
            "post", VENDOR_PROMOTIONS_URL, user=self.owner,
            data={
                "code": "BACKWARDS", "discount_type": "percentage", "value": "10",
                "starts_at": "2026-02-01T00:00:00Z",
                "ends_at": "2026-01-01T00:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("ends_at", response.json())

    def test_update_value_while_used_count_stays_protected(self):
        response = self.call(
            "patch", f"{VENDOR_PROMOTIONS_URL}{self.save10.pk}/", user=self.owner,
            data={"value": "12.50", "used_count": 99},
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["value"], "12.50")
        self.assertEqual(payload["used_count"], 0)     # read-only, ignored
        self.save10.refresh_from_db()
        self.assertEqual(str(self.save10.value), "12.50")
        self.assertEqual(self.save10.used_count, 0)

    def test_delete_voucher(self):
        response = self.call(
            "delete", f"{VENDOR_PROMOTIONS_URL}{self.save10.pk}/", user=self.owner
        )
        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(DiscountCode.objects.filter(pk=self.save10.pk).exists())

    def test_customer_cannot_manage_vouchers(self):
        response = self.call("get", VENDOR_PROMOTIONS_URL, user=self.customer)
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_401(self):
        response = self.call("get", VENDOR_PROMOTIONS_URL)
        self.assertEqual(response.status_code, 401)


class VendorOrderStatusTests(TwoStoreVendorBase):
    """PATCH orders/<id>/status/ walks the lifecycle state machine."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tee = Product.objects.create(
            business=cls.acme, name="Acme Tee", price="19.99", stock=40
        )
        cls.shoe = Product.objects.create(
            business=cls.nike, name="Nike Shoe", price="99.00", stock=10
        )
        cls.order = make_order(cls.acme, cls.customer, cls.tee)
        cls.foreign_order = make_order(cls.nike, cls.customer, cls.shoe)

    def _status_url(self, order) -> str:
        return f"{VENDOR_ORDERS_URL}{order.pk}/status/"

    def test_status_chain_walks_pending_to_delivered(self):
        for step in ("processing", "shipped", "delivered"):
            response = self.call(
                "patch", self._status_url(self.order), user=self.owner,
                data={"status": step},
            )
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["status"], step)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)

    def test_illegal_jump_is_rejected(self):
        """KEY: no pending -> delivered shortcut; the trail stays honest."""
        response = self.call(
            "patch", self._status_url(self.order), user=self.owner,
            data={"status": "delivered"},
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("status", response.json())
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)

    def test_no_op_and_unknown_status_are_400(self):
        same = self.call(
            "patch", self._status_url(self.order), user=self.owner,
            data={"status": "pending"},
        )
        self.assertEqual(same.status_code, 400, same.content)
        unknown = self.call(
            "patch", self._status_url(self.order), user=self.owner,
            data={"status": "teleported"},
        )
        self.assertEqual(unknown.status_code, 400, unknown.content)

    def test_vendor_cannot_advance_another_stores_order(self):
        """KEY: foreign order id -> 404, status untouched."""
        response = self.call(
            "patch", self._status_url(self.foreign_order), user=self.owner,
            data={"status": "processing"},
        )
        self.assertEqual(response.status_code, 404)
        self.foreign_order.refresh_from_db()
        self.assertEqual(self.foreign_order.status, Order.Status.PENDING)

    def test_customers_cannot_advance_orders(self):
        denied = self.call(
            "patch", self._status_url(self.order), user=self.customer,
            data={"status": "processing"},
        )
        self.assertEqual(denied.status_code, 403)
        anonymous = self.call(
            "patch", self._status_url(self.order), data={"status": "processing"}
        )
        self.assertEqual(anonymous.status_code, 401)


class VendorAnalyticsTests(TwoStoreVendorBase):
    """GET analytics/ - revenue, orders and customers for THIS store only."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tee = Product.objects.create(
            business=cls.acme, name="Acme Tee", price="19.99", stock=40
        )
        cls.shoe = Product.objects.create(
            business=cls.nike, name="Nike Shoe", price="99.00", stock=10
        )
        cls.ann = User.objects.create_user(email="ann@shop.test", password=PASSWORD)
        cls.bob = User.objects.create_user(email="bob@shop.test", password=PASSWORD)
        cls.carol = User.objects.create_user(
            email="carol@shop.test", password=PASSWORD
        )
        cls.dave = User.objects.create_user(email="dave@shop.test", password=PASSWORD)

        # acme: 4 orders - two count, two are cancelled.
        make_order(cls.acme, cls.ann, cls.tee)                                  # pending
        make_order(cls.acme, cls.ann, cls.tee, status=Order.Status.PAID)        # paid
        make_order(cls.acme, cls.bob, cls.tee, status=Order.Status.CANCELLED)   # excluded
        make_order(cls.acme, cls.carol, cls.tee, status=Order.Status.CANCELLED) # excluded
        # nike: one paid order of a different magnitude.
        make_order(cls.nike, cls.dave, cls.shoe, status=Order.Status.PAID)

        CustomerStoreLink.touch(customer=cls.ann, business=cls.acme)
        CustomerStoreLink.touch(customer=cls.dave, business=cls.nike)

    def test_analytics_are_scoped_and_exclude_cancelled(self):
        """KEY: revenue = non-cancelled orders of THIS tenant, nothing else."""
        response = self.call("get", VENDOR_ANALYTICS_URL, user=self.owner)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["total_revenue"], "39.98")   # 19.99 x 2
        self.assertEqual(payload["total_orders"], 2)
        self.assertEqual(payload["total_customers"], 3)       # ann, bob, carol
        self.assertEqual(payload["linked_customers"], 1)      # ann (dave is nike's)
        self.assertEqual(payload["average_order_value"], "19.99")
        self.assertEqual(payload["currency"], self.acme.currency)
        self.assertEqual(payload["orders_by_status"]["pending"], 1)
        self.assertEqual(payload["orders_by_status"]["paid"], 1)
        self.assertEqual(payload["orders_by_status"]["cancelled"], 2)
        self.assertEqual(payload["orders_by_status"]["delivered"], 0)

    def test_other_vendor_sees_only_their_own_numbers(self):
        """KEY: nike's dashboard never contains acme's revenue."""
        response = self.call(
            "get", VENDOR_ANALYTICS_URL, user=self.outsider, host=NIKE
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["total_revenue"], "99.00")
        self.assertEqual(payload["total_orders"], 1)
        self.assertEqual(payload["total_customers"], 1)
        self.assertEqual(payload["linked_customers"], 1)

    def test_customers_cannot_read_analytics(self):
        denied = self.call("get", VENDOR_ANALYTICS_URL, user=self.customer)
        self.assertEqual(denied.status_code, 403)
        anonymous = self.call("get", VENDOR_ANALYTICS_URL)
        self.assertEqual(anonymous.status_code, 401)


class VendorSettingsTests(TwoStoreVendorBase):
    """GET/PATCH settings/ - storefront branding, per tenant, no id in URL."""

    def test_get_creates_defaults_lazily(self):
        response = self.call("get", VENDOR_SETTINGS_URL, user=self.owner)
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        # Blank brand_name falls back to the business name for display.
        self.assertEqual(payload["display_name"], "Acme Threads")
        self.assertTrue(payload["primary_color"].startswith("#"))
        self.assertTrue(BrandConfig.objects.for_tenant(self.acme).exists())

    def test_patch_reaches_the_storefront_and_stays_in_store(self):
        """KEY: settings edits flow into /storefront/init/ for THIS store only."""
        response = self.call(
            "patch", VENDOR_SETTINGS_URL, user=self.owner,
            data={"brand_name": "Fresh Threads", "primary_color": "#123456"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["brand_name"], "Fresh Threads")

        mine = self.client.get(INIT_URL, HTTP_HOST=ACME)
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(mine.json()["brand"]["brand_name"], "Fresh Threads")
        self.assertEqual(mine.json()["theme"]["primary_color"], "#123456")

        theirs = self.client.get(INIT_URL, HTTP_HOST=NIKE)
        self.assertEqual(theirs.status_code, 200)
        self.assertEqual(theirs.json()["brand"]["brand_name"], "Nike Store")
        self.assertNotEqual(theirs.json()["theme"]["primary_color"], "#123456")

    def test_invalid_hex_colour_is_rejected(self):
        """Colours are hex-only: raw CSS never reaches the React theme."""
        response = self.call(
            "patch", VENDOR_SETTINGS_URL, user=self.owner,
            data={"primary_color": "red"},
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("primary_color", response.json())

    def test_customers_cannot_change_settings(self):
        denied = self.call(
            "patch", VENDOR_SETTINGS_URL, user=self.customer,
            data={"brand_name": "Hijacked"},
        )
        self.assertEqual(denied.status_code, 403)
        anonymous = self.call("get", VENDOR_SETTINGS_URL)
        self.assertEqual(anonymous.status_code, 401)


class VendorImageUploadTests(TwoStoreVendorBase):
    """Uploads: Pillow-gated, 2 MB cap, and no orphaned files on disk."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tee = Product.objects.create(
            business=cls.acme, name="Acme Tee", price="19.99", stock=5
        )

    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp(prefix="pbl-media-")
        self._media = override_settings(MEDIA_ROOT=self.media_root)
        self._media.enable()

    def tearDown(self):
        self._media.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)
        super().tearDown()

    def test_image_upload_replace_and_delete_lifecycle(self):
        """KEY: replaced/deleted images leave disk too - no orphans."""
        response = self.call(
            "post", VENDOR_PRODUCTS_URL, user=self.owner, multipart=True,
            data={
                "name": "Photo Tee", "price": "10.00", "stock": 5,
                "image": SimpleUploadedFile("tee.gif", TINY_GIF, "image/gif"),
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIn("products/", response.json()["image"])

        product = Product.objects.get(name="Photo Tee")
        old_name = product.image.name
        self.assertTrue(product.image.storage.exists(old_name))

        replaced = self.call(
            "patch", f"{VENDOR_PRODUCTS_URL}{product.pk}/", user=self.owner,
            multipart=True,
            data={"image": SimpleUploadedFile("tee2.gif", TINY_GIF, "image/gif")},
        )
        self.assertEqual(replaced.status_code, 200, replaced.content)
        product.refresh_from_db()
        new_name = product.image.name
        self.assertNotEqual(old_name, new_name)
        self.assertFalse(product.image.storage.exists(old_name))  # old cleaned
        self.assertTrue(product.image.storage.exists(new_name))

        deleted = self.call(
            "delete", f"{VENDOR_PRODUCTS_URL}{product.pk}/", user=self.owner
        )
        self.assertEqual(deleted.status_code, 204, deleted.content)
        self.assertFalse(product.image.storage.exists(new_name))  # gone for good

    def test_non_image_upload_is_rejected(self):
        response = self.call(
            "post", VENDOR_PRODUCTS_URL, user=self.owner, multipart=True,
            data={
                "name": "Text Product", "price": "5.00", "stock": 1,
                "image": SimpleUploadedFile("notes.txt", b"just text", "text/plain"),
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("image", response.json())

    def test_oversized_image_is_rejected(self):
        """Valid image, > 2 MB ->400 from the size validator."""
        response = self.call(
            "post", VENDOR_PRODUCTS_URL, user=self.owner, multipart=True,
            data={
                "name": "Huge Product", "price": "5.00", "stock": 1,
                "image": SimpleUploadedFile(
                    "huge.bmp", oversized_image(), "image/bmp"
                ),
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("image", response.json())
        self.assertIn("large", str(response.json()).lower())

    def test_logo_upload_via_settings(self):
        response = self.call(
            "patch", VENDOR_SETTINGS_URL, user=self.owner, multipart=True,
            data={"logo": SimpleUploadedFile("logo.gif", TINY_GIF, "image/gif")},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("brands/logos/", response.json()["logo"])
        config = BrandConfig.objects.for_tenant(self.acme).get()
        self.assertIn("brands/logos/", config.logo.name)
