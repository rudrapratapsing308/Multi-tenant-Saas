"""
Checkout service: turn a cart into an Order - atomically.

Everything happens inside ONE transaction: order + line snapshots, stock
decrements (guarded UPDATEs), voucher redemption, the customer/store link and
emptying the cart. Any rule violation raises :class:`CheckoutError`, the
transaction rolls back completely, and the view answers 400 - a half-created
order can never exist.

Tenant isolation note: the voucher is looked up with
``DiscountCode.objects.for_tenant(business)``, so a code that only exists in
another store reports ``voucher_not_found`` - identical names across stores
can never cross over.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q

from apps.accounts.models import CustomerStoreLink
from apps.cart.models import Cart, CartItem
from apps.catalog.models import Product, ProductVariant
from apps.promotions.models import DiscountCode

from .models import Order, OrderItem

# Machine-readable reason -> what the shopper sees.
VOUCHER_MESSAGES = {
    "voucher_inactive": "This voucher is no longer active.",
    "voucher_not_started": "This voucher is not active yet.",
    "voucher_expired": "This voucher has expired.",
    "voucher_exhausted": "This voucher has reached its usage limit.",
    "voucher_min_order_not_met": (
        "Your cart does not meet the minimum order for this voucher."
    ),
}


class CheckoutError(Exception):
    """Business-rule failure during checkout; views map it to HTTP 400."""

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


def place_order(
    *,
    cart: Cart,
    customer,
    shipping: dict,
    voucher_code: str = "",
    notes: str = "",
) -> Order:
    """
    Create the order for ``cart`` (already resolved + tenant-checked by the
    view). Returns the created Order with its items.
    """
    items = list(cart.items.select_related("product", "variant"))
    if not items:
        raise CheckoutError("empty_cart", "Your cart is empty.")

    business = cart.business
    subtotal = sum(
        (item.line_total for item in items), Decimal("0.00")
    ).quantize(Decimal("0.01"))

    with transaction.atomic():
        # -- voucher ------------------------------------------------------------
        voucher = None
        discount = Decimal("0.00")
        if voucher_code:
            try:
                voucher = DiscountCode.objects.for_tenant(business).get(
                    code=voucher_code
                )
            except DiscountCode.DoesNotExist:
                # Includes codes that exist only in ANOTHER store.
                raise CheckoutError(
                    "voucher_not_found",
                    "This voucher code is not valid for this store.",
                ) from None
            reason = voucher.rejection_reason(subtotal)
            if reason is not None:
                raise CheckoutError(reason, VOUCHER_MESSAGES[reason])
            discount = voucher.calculate_discount(subtotal)

        total = max(subtotal - discount, Decimal("0.00")).quantize(Decimal("0.01"))

        # -- order + snapshot lines --------------------------------------------
        order = Order.objects.create_for_tenant(
            business,
            customer=customer,
            customer_email=customer.email,
            customer_name=customer.get_full_name(),
            currency=business.currency,
            subtotal=subtotal,
            discount_amount=discount,
            total=total,
            voucher=voucher,
            voucher_code=voucher.code if voucher else "",
            shipping_name=shipping["full_name"],
            shipping_address1=shipping["address1"],
            shipping_address2=shipping.get("address2", ""),
            shipping_city=shipping["city"],
            shipping_postal_code=shipping["postal_code"],
            shipping_country=shipping["country"],
            shipping_phone=shipping.get("phone", ""),
            notes=notes or "",
        )

        for item in items:
            OrderItem.objects.create_for_tenant(
                business,
                order=order,
                product=item.product,
                variant=item.variant,
                product_name=item.product.name,
                variant_name=item.variant_name,
                sku=(item.variant.sku or item.product.sku) if item.variant_id
                else item.product.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
            _decrement_stock(item)

        # -- voucher redemption (guarded against concurrent use) ----------------
        if voucher is not None:
            redeemed = (
                DiscountCode.objects.filter(pk=voucher.pk, is_active=True)
                .filter(Q(max_uses__isnull=True) | Q(used_count__lt=F("max_uses")))
                .update(used_count=F("used_count") + 1)
            )
            if not redeemed:
                raise CheckoutError(
                    "voucher_exhausted", VOUCHER_MESSAGES["voucher_exhausted"]
                )

        # -- side effects --------------------------------------------------------
        CustomerStoreLink.touch(customer, business, spent=total)
        cart.items.all().delete()

    return order


def _decrement_stock(item: CartItem) -> None:
    """
    Subtract with a ``stock >= quantity`` guard so two concurrent checkouts
    cannot sell the same unit twice (the loser gets insufficient_stock and the
    whole transaction rolls back).
    """
    if item.variant_id:
        sold = ProductVariant.objects.filter(
            pk=item.variant_id, stock__gte=item.quantity
        ).update(stock=F("stock") - item.quantity)
    else:
        sold = Product.objects.filter(
            pk=item.product_id, stock__gte=item.quantity
        ).update(stock=F("stock") - item.quantity)

    if not sold:
        raise CheckoutError(
            "insufficient_stock",
            f"Not enough stock left for {item.product_name}.",
            product_id=item.product_id,
        )
