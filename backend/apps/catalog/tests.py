"""
Catalog API tests: public reads must be tenant-scoped, reviews must be gated.

Run with:  python backend/manage.py test apps.catalog
"""
from __future__ import annotations

from django.test import TestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.orders.models import Order, OrderItem
from apps.tenants.models import Business, Domain

from .models import Category, Product, ProductVariant, Review

CATEGORIES_URL = "/api/v1/catalog/categories/"
PRODUCTS_URL = "/api/v1/catalog/products/"
REVIEWS_URL = "/api/v1/catalog/reviews/"
ACME = "acme.local-saas.com"
NIKE = "nike.local-saas.com"
PASSWORD = "s3cret-pass-1"


def bearer(user) -> str:
    return f"Bearer {RefreshToken.for_user(user).access_token}"


class CatalogBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.accounts.models import BusinessMembership, User

        cls.acme = Business.objects.create(name="Acme Threads", slug="acme")
        cls.nike = Business.objects.create(name="Nike Store", slug="nike")
        Domain.objects.create(host=ACME, business=cls.acme, is_primary=True)
        Domain.objects.create(host=NIKE, business=cls.nike, is_primary=True)

        cls.shopper = User.objects.create_user(
            email="shopper@shop.test", password=PASSWORD
        )
        cls.reviewer = User.objects.create_user(
            email="rev@shop.test", password=PASSWORD, first_name="Rae"
        )
        cls.buyer = User.objects.create_user(
            email="buyer@shop.test", password=PASSWORD, first_name="Bea", last_name="Buyer"
        )
        cls.vendor = User.objects.create_user(
            email="vic@shop.test", password=PASSWORD, role=User.Role.VENDOR
        )
        BusinessMembership.objects.create(
            user=cls.vendor, business=cls.acme, role=BusinessMembership.Role.OWNER
        )

        cls.tes = Category.objects.create(
            business=cls.acme, name="Tees", slug="tees", is_active=True
        )
        Category.objects.create(
            business=cls.acme, name="Hidden", slug="hidden", is_active=False
        )
        Category.objects.create(
            business=cls.nike, name="Shoes", slug="shoes", is_active=True
        )

        cls.tee = Product.objects.create(
            business=cls.acme,
            category=cls.tes,
            name="Acme Tee",
            price="19.99",
            stock=5,
            is_featured=True,
        )
        Product.objects.create(
            business=cls.acme, name="Secret Hoodie", price="40.00", is_active=False
        )
        cls.hoodie = Product.objects.create(
            business=cls.acme, name="Acme Hoodie", price="40.00", stock=0
        )
        cls.size_m = ProductVariant.objects.create(
            product=cls.hoodie, size="M", color="Black", stock=5, price="35.00"
        )
        ProductVariant.objects.create(
            product=cls.hoodie, size="S", color="Red", stock=0
        )
        ProductVariant.objects.create(
            product=cls.hoodie, size="XL", color="Grey", stock=3, is_active=False
        )
        cls.shoe = Product.objects.create(
            business=cls.nike, name="Nike Shoe", price="99.00", stock=10
        )

        Review.objects.create(
            business=cls.acme,
            product=cls.tee,
            customer=cls.reviewer,   # not the buyer: buyer's own review is the test
            rating=5,
            title="Great",
            status=Review.Status.APPROVED,
            verified_purchase=True,
        )
        Review.objects.create(
            business=cls.acme,
            product=cls.tee,
            customer=cls.shopper,
            rating=3,
            status=Review.Status.PENDING,  # not public yet
        )
        cls.nike_review = Review.objects.create(
            business=cls.nike,
            product=cls.shoe,
            customer=cls.shopper,
            rating=1,
            status=Review.Status.APPROVED,
        )

        # Proof of purchase for the buyer on the acme tee.
        cls.purchase = Order.objects.create_for_tenant(
            cls.acme,
            customer=cls.buyer,
            customer_email=cls.buyer.email,
            shipping_name="Bea Buyer",
            shipping_address1="1 Main Street",
            shipping_city="Metropolis",
            shipping_postal_code="12345",
            shipping_country="IN",
            subtotal=cls.tee.price,
            total=cls.tee.price,
            status=Order.Status.PAID,
        )
        OrderItem.objects.create_for_tenant(
            cls.acme,
            order=cls.purchase,
            product=cls.tee,
            product_name=cls.tee.name,
            quantity=1,
            unit_price=cls.tee.price,
        )


class CategoryTests(CatalogBase):
    def test_only_active_categories_of_this_store(self):
        response = self.client.get(CATEGORIES_URL, HTTP_HOST=ACME)
        self.assertEqual(response.status_code, 200)
        names = [c["name"] for c in response.json()]
        self.assertEqual(names, ["Tees"])  # hidden + nike excluded (KEY)

    def test_other_store_sees_its_own_categories(self):
        response = self.client.get(CATEGORIES_URL, HTTP_HOST=NIKE)
        self.assertEqual([c["name"] for c in response.json()], ["Shoes"])


class ProductListTests(CatalogBase):
    def _names(self, response):
        return [p["name"] for p in response.json()]

    def test_lists_only_active_products_of_this_store(self):
        response = self.client.get(PRODUCTS_URL, HTTP_HOST=ACME)
        self.assertEqual(response.status_code, 200)
        names = self._names(response)
        self.assertIn("Acme Tee", names)
        self.assertIn("Acme Hoodie", names)
        self.assertNotIn("Secret Hoodie", names)  # inactive
        self.assertNotIn("Nike Shoe", names)  # other tenant (KEY)

    def test_response_exposes_computed_fields(self):
        response = self.client.get(PRODUCTS_URL, HTTP_HOST=ACME)
        tee = next(p for p in response.json() if p["name"] == "Acme Tee")
        self.assertEqual(tee["starting_price"], "19.99")
        self.assertTrue(tee["in_stock"])
        self.assertFalse(tee["has_variants"])
        self.assertEqual(tee["category"]["name"], "Tees")
        self.assertTrue(tee["is_featured"])

    def test_filter_by_category_slug(self):
        response = self.client.get(
            PRODUCTS_URL + "?category=tees", HTTP_HOST=ACME
        )
        self.assertEqual(self._names(response), ["Acme Tee"])

    def test_filter_by_category_slug_from_another_store_yields_nothing(self):
        response = self.client.get(
            PRODUCTS_URL + "?category=shoes", HTTP_HOST=ACME
        )
        self.assertEqual(response.json(), [])  # nike's category is not ours

    def test_search_filter(self):
        response = self.client.get(PRODUCTS_URL + "?search=hoodie", HTTP_HOST=ACME)
        self.assertEqual(self._names(response), ["Acme Hoodie"])

    def test_featured_filter(self):
        response = self.client.get(PRODUCTS_URL + "?featured=true", HTTP_HOST=ACME)
        self.assertEqual(self._names(response), ["Acme Tee"])


class ProductDetailTests(CatalogBase):
    def test_detail_includes_variants_but_not_inactive_ones(self):
        response = self.client.get(
            PRODUCTS_URL + f"{self.hoodie.pk}/", HTTP_HOST=ACME
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        sizes = {v["size"] for v in payload["variants"]}
        self.assertEqual(sizes, {"M", "S"})  # XL variant is inactive
        prices = {v["size"]: v["price"] for v in payload["variants"]}
        self.assertEqual(prices["M"], "35.00")  # override
        self.assertEqual(prices["S"], "40.00")  # inherits product price

    def test_detail_shows_only_approved_reviews(self):
        response = self.client.get(PRODUCTS_URL + f"{self.tee.pk}/", HTTP_HOST=ACME)
        payload = response.json()
        self.assertEqual(len(payload["reviews"]), 1)  # pending one hidden (KEY)
        self.assertEqual(payload["reviews"][0]["status"], "approved")
        self.assertEqual(
            payload["reviews"][0]["customer_name"], "Rae"
        )  # first_name fallback path
        self.assertNotIn(self.nike_review.pk, [r["id"] for r in payload["reviews"]])
        self.assertEqual(payload["rating_average"], 5.0)
        self.assertEqual(payload["rating_count"], 1)

    def test_another_stores_product_is_404(self):
        """Knowing the id must not be enough (KEY isolation)."""
        response = self.client.get(PRODUCTS_URL + f"{self.shoe.pk}/", HTTP_HOST=ACME)
        self.assertEqual(response.status_code, 404)

    def test_inactive_product_is_404(self):
        hidden = Product.objects.get(slug="secret-hoodie")
        response = self.client.get(PRODUCTS_URL + f"{hidden.pk}/", HTTP_HOST=ACME)
        self.assertEqual(response.status_code, 404)


class ReviewTests(CatalogBase):
    def _post(self, payload, user=None, host=ACME, **extra):
        kwargs = {"HTTP_HOST": host, **extra}
        if user is not None:
            kwargs["HTTP_AUTHORIZATION"] = bearer(user)
        return self.client.post(REVIEWS_URL, payload, **kwargs)

    def test_anonymous_review_is_401(self):
        response = self._post({"product": self.tee.pk, "rating": 5})
        self.assertEqual(response.status_code, 401)

    def test_review_without_a_purchase_is_rejected(self):
        response = self._post(
            {"product": self.tee.pk, "rating": 5, "body": "nice"},
            user=self.shopper,
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("purchased", response.json()["product"][0])

    def test_review_with_a_purchase_succeeds(self):
        response = self._post(
            {"product": self.tee.pk, "rating": 4, "title": "Solid", "body": "ok"},
            user=self.buyer,
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload["status"], "pending")  # awaits vendor approval
        self.assertTrue(payload["verified_purchase"])
        self.assertEqual(payload["customer_name"], "Bea Buyer")

        review = Review.objects.get(pk=payload["id"])
        self.assertEqual(review.business_id, self.acme.pk)
        self.assertEqual(review.customer_id, self.buyer.pk)

    def test_pending_review_is_not_public_yet(self):
        self._post({"product": self.tee.pk, "rating": 4}, user=self.buyer)
        response = self.client.get(
            PRODUCTS_URL + f"{self.tee.pk}/", HTTP_HOST=ACME
        )
        self.assertEqual(len(response.json()["reviews"]), 1)

    def test_duplicate_review_is_rejected(self):
        self._post({"product": self.tee.pk, "rating": 4}, user=self.buyer)
        response = self._post({"product": self.tee.pk, "rating": 2}, user=self.buyer)
        self.assertEqual(response.status_code, 400)

    def test_product_from_another_store_is_rejected(self):
        """Spec: review POST must not cross tenants (KEY)."""
        response = self._post({"product": self.shoe.pk, "rating": 5}, user=self.buyer)
        self.assertEqual(response.status_code, 400)
        self.assertIn("product", response.json())
        self.assertFalse(
            Review.objects.for_tenant(self.nike)
            .filter(product=self.shoe, customer=self.buyer)
            .exists()
        )

    def test_vendor_role_cannot_review(self):
        response = self._post(
            {"product": self.tee.pk, "rating": 5}, user=self.vendor
        )
        self.assertEqual(response.status_code, 403)

    def test_new_review_only_lands_in_the_current_tenant(self):
        response = self._post({"product": self.tee.pk, "rating": 4}, user=self.buyer)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            Review.objects.for_tenant(self.acme)
            .filter(customer=self.buyer, product=self.tee)
            .count(),
            1,
        )
        self.assertFalse(
            Review.objects.for_tenant(self.nike)
            .filter(customer=self.buyer)
            .exists()
        )
