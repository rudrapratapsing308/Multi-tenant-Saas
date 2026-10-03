"""
Checkout + order history tests: atomicity, vouchers, tenant isolation.

Run with:  python backend/manage.py test apps.orders
"""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomerStoreLink, User
from apps.cart.models import Cart, CartItem
from apps.catalog.models import Product
from apps.promotions.models import DiscountCode
from apps.tenants.models import Business, Domain

from .models import Order, OrderItem

CHECKOUT_URL = "/api/v1/orders/checkout/"
ORDERS_URL = "/api/v1/orders/"
ACME = "acme.local-saas.com"
NIKE = "nike.local-saas.com"
PASSWORD = "s3cret-pass-1"

SHIPPING = {
    "full_name": "Ann Buyer",
    "address1": "1 Main Street",
    "city": "Metropolis",
    "postal_code": "12345",
    "country": "in",  # deliberately lowercase -> serializer normalizes
    "phone": "+91 99999 00000",
}


class CheckoutBase(TestCase):
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
        cls.cap = Product.objects.create(
            business=cls.acme, name="Acme Cap", price="10.00", stock=1
        )
        cls.shoe = Product.objects.create(
            business=cls.nike, name="Nike Shoe", price="99.00", stock=10
        )

        # acme vouchers
        cls.save10 = DiscountCode.objects.create(
            business=cls.acme,
            code="SAVE10",
            discount_type=DiscountCode.DiscountType.PERCENTAGE,
            value=10,
        )
        DiscountCode.objects.create(
            business=cls.acme,
            code="MIN50",
            discount_type=DiscountCode.DiscountType.PERCENTAGE,
            value=20,
            min_order_amount="50.00",
        )
        DiscountCode.objects.create(
            business=cls.acme,
            code="EXPIRED",
            discount_type=DiscountCode.DiscountType.FLAT,
            value=5,
            ends_at=timezone.now() - timedelta(days=1),
        )
        DiscountCode.objects.create(
            business=cls.acme,
            code="ONCE",
            discount_type=DiscountCode.DiscountType.FLAT,
            value=5,
            max_uses=1,
            used_count=1,
        )
        # nike vouchers: SAME code name as acme's, different type/value; plus a
        # code that only exists on nike.
        DiscountCode.objects.create(
            business=cls.nike,
            code="SAVE10",
            discount_type=DiscountCode.DiscountType.FLAT,
            value=5,
        )
        DiscountCode.objects.create(
            business=cls.nike,
            code="FLAT5",
            discount_type=DiscountCode.DiscountType.FLAT,
            value=5,
        )

    # -- helpers ---------------------------------------------------------------
    def make_cart(self, product, quantity, business=None, variant=None):
        business = business or self.acme
        cart, _ = Cart.objects.get_or_create(business=business, customer=self.ann)
        CartItem.objects.create_for_tenant(
            business,
            cart=cart,
            product=product,
            variant=variant,
            quantity=quantity,
        )
        return cart

    def checkout(self, payload=None, host=ACME):
        body = {"shipping": dict(SHIPPING)}
        if payload:
            body.update(payload)
        # JSON, exactly like the React app sends it (nested objects survive).
        return self.client.post(
            CHECKOUT_URL,
            json.dumps(body),
            content_type="application/json",
            HTTP_HOST=host,
            HTTP_AUTHORIZATION=self.auth,
        )


class CheckoutTests(CheckoutBase):
    def test_happy_path_creates_order_and_empties_the_cart(self):
        cart = self.make_cart(self.tee, 2)  # 2 x 19.99 = 39.98
        response = self.checkout()
        self.assertEqual(response.status_code, 201, response.content)

        payload = response.json()
        self.assertTrue(payload["order_number"].startswith("ACME-"))
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["subtotal"], "39.98")
        self.assertEqual(payload["discount_amount"], "0.00")
        self.assertEqual(payload["total"], "39.98")
        self.assertEqual(payload["shipping_country"], "IN")  # normalized
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["product_name"], "Acme Tee")
        self.assertEqual(item["unit_price"], "19.99")
        self.assertEqual(item["line_total"], "39.98")

        cart.refresh_from_db()
        self.assertEqual(cart.items.count(), 0)  # emptied on success
        self.tee.refresh_from_db()
        self.assertEqual(self.tee.stock, 3)  # 5 - 2

        link = CustomerStoreLink.objects.get(customer=self.ann, business=self.acme)
        self.assertEqual(link.orders_count, 1)
        self.assertEqual(link.total_spent, Decimal("39.98"))

        order = Order.objects.get()
        self.assertEqual(order.business_id, self.acme.pk)
        self.assertEqual(order.customer_id, self.ann.pk)
        self.assertEqual(order.customer_email, "ann@shop.test")

    def test_country_must_be_a_two_letter_code(self):
        self.make_cart(self.tee, 1)
        response = self.checkout(
            {"shipping": {**SHIPPING, "country": "INDIA"}}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("shipping", response.json())
        self.assertEqual(Order.objects.count(), 0)

    def test_anonymous_checkout_is_401(self):
        response = self.client.post(
            CHECKOUT_URL, {"shipping": SHIPPING}, HTTP_HOST=ACME
        )
        self.assertEqual(response.status_code, 401)

    def test_empty_cart_is_rejected(self):
        response = self.checkout()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "empty_cart")

    def test_insufficient_stock_rolls_back_everything(self):
        cart = self.make_cart(self.cap, 5)  # stock is only 1
        response = self.checkout()
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"], "insufficient_stock")

        self.assertEqual(Order.objects.count(), 0)  # atomic: no partial order
        self.cap.refresh_from_db()
        self.assertEqual(self.cap.stock, 1)  # unchanged
        cart.refresh_from_db()
        line = cart.items.get()  # the line itself is untouched...
        self.assertEqual(line.quantity, 5)
        self.assertEqual(
            CustomerStoreLink.objects.filter(customer=self.ann).count(), 0
        )

    def test_foreign_cart_id_is_rejected(self):
        """KEY: a cart id from another store is indistinguishable from a typo."""
        nike_cart = self.make_cart(self.shoe, 1, business=self.nike)
        response = self.checkout({"cart_id": nike_cart.pk})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "cart_not_found")
        self.assertEqual(Order.objects.count(), 0)


class VoucherTests(CheckoutBase):
    def test_percentage_voucher_applies(self):
        self.make_cart(self.tee, 2)  # 39.98
        response = self.checkout({"voucher_code": "save10"})  # lowercase input
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload["voucher_code"], "SAVE10")
        self.assertEqual(payload["subtotal"], "39.98")
        self.assertEqual(payload["discount_amount"], "4.00")  # 10% of 39.98
        self.assertEqual(payload["total"], "35.98")

        self.save10.refresh_from_db()
        self.assertEqual(self.save10.used_count, 1)

    def test_code_from_another_store_is_not_usable(self):
        """KEY: FLAT5 exists only on nike -> acme reports voucher_not_found."""
        self.make_cart(self.tee, 1)
        response = self.checkout({"voucher_code": "FLAT5"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "voucher_not_found")
        self.assertEqual(Order.objects.count(), 0)

    def test_same_code_applies_each_stores_own_version(self):
        """KEY: 'SAVE10' is two different vouchers - each store gets its own."""
        self.make_cart(self.tee, 2)  # acme: 10% of 39.98
        acme_order = self.checkout({"voucher_code": "SAVE10"})
        self.assertEqual(acme_order.status_code, 201, acme_order.content)
        self.assertEqual(acme_order.json()["discount_amount"], "4.00")

        self.make_cart(self.shoe, 1, business=self.nike)  # nike: flat 5
        nike_order = self.checkout(
            {"voucher_code": "SAVE10"}, host=NIKE
        )
        self.assertEqual(nike_order.status_code, 201, nike_order.content)
        nike_payload = nike_order.json()
        self.assertEqual(nike_payload["discount_amount"], "5.00")
        self.assertEqual(nike_payload["subtotal"], "99.00")
        self.assertEqual(nike_payload["total"], "94.00")

        # Each store's own row was redeemed exactly once.
        self.assertEqual(
            DiscountCode.objects.for_tenant(self.acme)
            .get(code="SAVE10")
            .used_count,
            1,
        )
        self.assertEqual(
            DiscountCode.objects.for_tenant(self.nike)
            .get(code="SAVE10")
            .used_count,
            1,
        )

    def test_below_minimum_order_is_rejected(self):
        self.make_cart(self.tee, 1)  # 19.99 < 50.00
        response = self.checkout({"voucher_code": "MIN50"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"], "voucher_min_order_not_met"
        )
        self.assertEqual(Order.objects.count(), 0)

    def test_expired_code_is_rejected(self):
        self.make_cart(self.tee, 1)
        response = self.checkout({"voucher_code": "EXPIRED"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "voucher_expired")

    def test_exhausted_code_is_rejected(self):
        self.make_cart(self.tee, 1)
        response = self.checkout({"voucher_code": "ONCE"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "voucher_exhausted")
        self.assertEqual(Order.objects.count(), 0)


def _make_order(business, customer, product, quantity=1, status=Order.Status.PENDING):
    order = Order.objects.create_for_tenant(
        business,
        customer=customer,
        customer_email=customer.email,
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
        quantity=quantity,
        unit_price=product.price,
    )
    return order


class OrderHistoryTests(CheckoutBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other = User.objects.create_user(
            email="other@shop.test", password=PASSWORD
        )
        cls.mine_acme = _make_order(cls.acme, cls.ann, cls.tee)
        cls.theirs_acme = _make_order(cls.acme, cls.other, cls.tee)
        cls.mine_nike = _make_order(cls.nike, cls.ann, cls.shoe)

    def test_returns_only_my_orders_for_this_store(self):
        response = self.client.get(
            ORDERS_URL, HTTP_HOST=ACME, HTTP_AUTHORIZATION=self.auth
        )
        self.assertEqual(response.status_code, 200)
        numbers = [o["order_number"] for o in response.json()]
        self.assertEqual(numbers, [self.mine_acme.order_number])  # KEY

    def test_nike_host_returns_only_nike_orders(self):
        response = self.client.get(
            ORDERS_URL, HTTP_HOST=NIKE, HTTP_AUTHORIZATION=self.auth
        )
        self.assertEqual(response.status_code, 200)
        numbers = [o["order_number"] for o in response.json()]
        self.assertEqual(numbers, [self.mine_nike.order_number])  # KEY

    def test_anonymous_is_401(self):
        response = self.client.get(ORDERS_URL, HTTP_HOST=ACME)
        self.assertEqual(response.status_code, 401)

    def test_order_numbers_are_unique_and_prefixed(self):
        second = _make_order(self.acme, self.ann, self.cap)
        self.assertNotEqual(
            second.order_number, self.mine_acme.order_number
        )
        self.assertTrue(second.order_number.startswith("ACME-"))
