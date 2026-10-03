"""
Cart API tests: auth-gated, live-priced and strictly per-store.

The flagship test is ``test_same_token_gets_a_different_cart_per_store``: one
logged-in customer, one token, two stores -> two independent carts.

Run with:  python backend/manage.py test apps.cart
"""
from __future__ import annotations

import json

from django.test import TestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.catalog.models import Product, ProductVariant
from apps.tenants.models import Business, Domain

from .models import Cart, CartItem

CART_URL = "/api/v1/cart/"
ACME = "acme.local-saas.com"
NIKE = "nike.local-saas.com"
PASSWORD = "s3cret-pass-1"


class CartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.acme = Business.objects.create(name="Acme Threads", slug="acme")
        cls.nike = Business.objects.create(name="Nike Store", slug="nike")
        Domain.objects.create(host=ACME, business=cls.acme, is_primary=True)
        Domain.objects.create(host=NIKE, business=cls.nike, is_primary=True)

        cls.ann = User.objects.create_user(
            email="ann@shop.test", password=PASSWORD, first_name="Ann"
        )
        cls.auth = f"Bearer {RefreshToken.for_user(cls.ann).access_token}"

        cls.tee = Product.objects.create(
            business=cls.acme, name="Acme Tee", price="19.99", stock=5
        )
        cls.hoodie = Product.objects.create(
            business=cls.acme, name="Acme Hoodie", price="40.00", stock=0
        )
        cls.size_m = ProductVariant.objects.create(
            product=cls.hoodie, size="M", color="Black", stock=2
        )
        cls.sold_out = ProductVariant.objects.create(
            product=cls.hoodie, size="S", color="Red", stock=0
        )
        cls.shoe = Product.objects.create(
            business=cls.nike, name="Nike Shoe", price="99.00", stock=10
        )

    # -- helpers ---------------------------------------------------------------
    def _headers(self, host=ACME, auth=True):
        headers = {"HTTP_HOST": host}
        if auth:
            headers["HTTP_AUTHORIZATION"] = self.auth
        return headers

    def _get(self, **kwargs):
        return self.client.get(CART_URL, **self._headers(**kwargs))

    def _add(self, payload, **kwargs):
        return self.client.post(CART_URL, payload, **self._headers(**kwargs))

    def _patch(self, payload, **kwargs):
        # JSON body: Django's test client otherwise defaults PATCH to
        # application/octet-stream, which DRF (rightly) refuses.
        return self.client.patch(
            CART_URL,
            json.dumps(payload),
            content_type="application/json",
            **self._headers(**kwargs),
        )

    def _delete(self, query="", **kwargs):
        return self.client.delete(CART_URL + query, **self._headers(**kwargs))

    # -- tests -----------------------------------------------------------------
    def test_anonymous_cannot_touch_the_cart(self):
        response = self._get(auth=False)
        self.assertEqual(response.status_code, 401)

    def test_first_get_creates_an_empty_cart_for_this_store(self):
        response = self._get()
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["subtotal"], "0.00")
        self.assertEqual(payload["item_count"], 0)
        self.assertEqual(payload["store"], "acme")
        cart = Cart.objects.get(customer=self.ann)
        self.assertEqual(cart.business_id, self.acme.pk)

    def test_add_line_calculates_totals(self):
        response = self._add({"product_id": self.tee.pk, "quantity": 2})
        self.assertEqual(response.status_code, 200, response.content)
        line = response.json()["items"][0]
        self.assertEqual(line["quantity"], 2)
        self.assertEqual(line["unit_price"], "19.99")
        self.assertEqual(line["line_total"], "39.98")
        self.assertEqual(line["available_stock"], 5)
        payload = response.json()
        self.assertEqual(payload["subtotal"], "39.98")
        self.assertEqual(payload["item_count"], 2)

    def test_adding_the_same_line_twice_accumulates(self):
        self._add({"product_id": self.tee.pk, "quantity": 1})
        response = self._add({"product_id": self.tee.pk, "quantity": 1})
        line = response.json()["items"][0]
        self.assertEqual(line["quantity"], 2)
        self.assertEqual(len(response.json()["items"]), 1)

    def test_adding_more_than_stock_is_rejected(self):
        response = self._add({"product_id": self.tee.pk, "quantity": 10})
        self.assertEqual(response.status_code, 400)
        self.assertIn("quantity", response.json())

    def test_variant_product_requires_a_variant(self):
        response = self._add({"product_id": self.hoodie.pk})
        self.assertEqual(response.status_code, 400)
        self.assertIn("variant_id", response.json())

    def test_sold_out_variant_is_rejected(self):
        response = self._add(
            {"product_id": self.hoodie.pk, "variant_id": self.sold_out.pk}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("quantity", response.json())

    def test_product_from_another_store_is_rejected(self):
        """KEY: a nike product id is meaningless on acme.local-saas.com."""
        response = self._add({"product_id": self.shoe.pk})
        self.assertEqual(response.status_code, 400)
        self.assertIn("product_id", response.json())
        self.assertFalse(CartItem.objects.filter(product=self.shoe).exists())

    def test_patch_updates_quantity_and_totals(self):
        self._add({"product_id": self.tee.pk, "quantity": 2})
        item_id = self._get().json()["items"][0]["id"]
        response = self._patch({"item_id": item_id, "quantity": 4})
        self.assertEqual(response.status_code, 200, response.content)
        line = response.json()["items"][0]
        self.assertEqual(line["quantity"], 4)
        self.assertEqual(line["line_total"], "79.96")

    def test_patch_quantity_zero_removes_the_line(self):
        self._add({"product_id": self.tee.pk, "quantity": 2})
        item_id = self._get().json()["items"][0]["id"]
        response = self._patch({"item_id": item_id, "quantity": 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])

    def test_patch_unknown_item_is_rejected(self):
        response = self._patch({"item_id": 99999, "quantity": 1})
        self.assertEqual(response.status_code, 400)

    def test_delete_removes_a_single_line(self):
        self._add({"product_id": self.tee.pk, "quantity": 1})
        self._add({"product_id": self.hoodie.pk, "variant_id": self.size_m.pk})
        items = self._get().json()["items"]
        self.assertEqual(len(items), 2)
        tee_line = next(i for i in items if i["product"]["name"] == "Acme Tee")
        response = self._delete(query=f"?item_id={tee_line['id']}")
        self.assertEqual(response.status_code, 200)
        remaining = [i["product"]["name"] for i in response.json()["items"]]
        self.assertEqual(remaining, ["Acme Hoodie"])

    def test_delete_without_item_id_clears_the_cart(self):
        self._add({"product_id": self.tee.pk, "quantity": 1})
        response = self._delete()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(Cart.objects.get(customer=self.ann).items.count(), 0)

    def test_same_token_gets_a_different_cart_per_store(self):
        """KEY isolation: one customer, two stores, two separate carts."""
        self._add({"product_id": self.tee.pk, "quantity": 2}, host=ACME)

        on_nike = self._get(host=NIKE).json()
        self.assertEqual(on_nike["items"], [])  # acme's line does not leak
        self.assertEqual(on_nike["store"], "nike")

        on_acme = self._get(host=ACME).json()
        self.assertEqual(len(on_acme["items"]), 1)

        carts = Cart.objects.filter(customer=self.ann)
        self.assertEqual(carts.count(), 2)
        self.assertEqual(
            set(carts.values_list("business_id", flat=True)),
            {self.acme.pk, self.nike.pk},
        )

    def test_price_changes_are_reflected_dynamically(self):
        self._add({"product_id": self.tee.pk, "quantity": 2})
        Product.objects.filter(pk=self.tee.pk).update(price="25.00")
        payload = self._get().json()
        line = payload["items"][0]
        self.assertEqual(line["unit_price"], "25.00")
        self.assertEqual(line["line_total"], "50.00")
        self.assertEqual(payload["subtotal"], "50.00")
