#!/usr/bin/env python3
"""
seed_demo.py
============
Idempotent demo-data seeder for local development.

    python backend/manage.py migrate    # schema first (start_dev.bat does both)
    python seed_demo.py                 # safe to re-run at any time

Creates ONLY what does not exist yet:

    super admin   boss@platform.test     password: s3cret-pass-1
    vendor        owner@acme.test        password: s3cret-pass-1  (owns Acme)
    stores        Acme Threads, Nike Store
    hostnames     acme.local-saas.com, nike.local-saas.com
                  localhost -> Acme  (so http://localhost:5173 serves the demo
                  storefront WITHOUT running the DNS simulator)
    catalog       a couple of demo products per store

Your own data (orders, carts, extra users, products you created) is never
touched: every insert is guarded by get_or_create on a stable natural key.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
sys.path.insert(0, str(ROOT / "backend"))

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.utils.text import slugify  # noqa: E402

from apps.accounts.models import BusinessMembership  # noqa: E402
from apps.catalog.models import Category, Product  # noqa: E402
from apps.tenants.models import Business, Domain  # noqa: E402

DEMO_PASSWORD = "s3cret-pass-1"

User = get_user_model()
created_items: list[str] = []


def ensure_user(email: str, role: str, *, first: str = "", last: str = "",
                superuser: bool = False):
    defaults: dict = {"role": role, "first_name": first, "last_name": last}
    if superuser:
        defaults.update(is_staff=True, is_superuser=True)
    user, created = User.objects.get_or_create(email=email, defaults=defaults)
    if created:
        user.set_password(DEMO_PASSWORD)
        user.save(update_fields=["password"])
        created_items.append(f"user {email} ({role})")
    return user


def ensure_business(slug: str, name: str, *, owner=None, contact: str = ""):
    biz, created = Business.objects.get_or_create(
        slug=slug,
        defaults={"name": name, "owner": owner, "contact_email": contact},
    )
    if created:
        created_items.append(f"store {name!r} ({slug}.local-saas.com)")
    if owner is not None and biz.owner_id is None:
        # Older dev databases were seeded before the owner link existed.
        biz.owner = owner
        biz.save(update_fields=["owner"])
        created_items.append(f"owner link for {name!r} -> {owner.email}")
    return biz


def ensure_domain(host: str, biz: Business, *, primary: bool) -> None:
    dom, created = Domain.objects.get_or_create(
        host=host,
        defaults={"business": biz, "is_primary": primary},
    )
    if created:
        created_items.append(f"domain {host} -> {biz.name}")


def ensure_category(biz: Business, name: str) -> Category:
    cat, created = Category.objects.get_or_create(
        business=biz,
        slug=slugify(name),
        defaults={"name": name},
    )
    if created:
        created_items.append(f"category {name!r} for {biz.name}")
    return cat


def ensure_product(biz: Business, name: str, *, category: Category,
                   price: Decimal, stock: int, sku: str,
                   compare_at: Decimal | None = None,
                   featured: bool = False, description: str = "") -> Product:
    product, created = Product.objects.get_or_create(
        business=biz,
        slug=slugify(name),
        defaults={
            "name": name,
            "category": category,
            "description": description,
            "sku": sku,
            "price": price,
            "compare_at_price": compare_at,
            "stock": stock,
            "is_featured": featured,
        },
    )
    if created:
        created_items.append(f"product {name!r} for {biz.name}")
    return product


def main() -> int:
    # -- people ------------------------------------------------------------
    boss = ensure_user(
        "boss@platform.test", User.Role.SUPER_ADMIN,
        first="Platform", last="Boss", superuser=True,
    )
    owner = ensure_user(
        "owner@acme.test", User.Role.VENDOR,
        first="Acme", last="Owner",
    )

    # -- stores + hostnames ------------------------------------------------
    acme = ensure_business(
        "acme", "Acme Threads", owner=owner, contact="hello@acme.test",
    )
    nike = ensure_business("nike", "Nike Store", contact="hello@nike.test")

    ensure_domain("acme.local-saas.com", acme, primary=True)
    ensure_domain("nike.local-saas.com", nike, primary=True)
    # Dev convenience: the demo storefront answers on plain localhost so the
    # quick start works with zero DNS setup. Non-primary, like production
    # aliases would be.
    ensure_domain("localhost", acme, primary=False)

    membership, m_created = BusinessMembership.objects.get_or_create(
        user=owner,
        business=acme,
        defaults={"role": BusinessMembership.Role.OWNER, "is_active": True},
    )
    if m_created:
        created_items.append("membership owner@acme.test -> Acme Threads")

    # -- demo catalog ------------------------------------------------------
    acme_tees = ensure_category(acme, "Tees")
    acme_hoodies = ensure_category(acme, "Hoodies")
    ensure_product(
        acme, "Acme Tee", category=acme_tees,
        price=Decimal("19.99"), compare_at=Decimal("24.99"), stock=50,
        sku="ACM-TEE-001", featured=True,
        description="Our flagship cotton tee - soft, sturdy, and printed in "
                    "small batches. Runs true to size.",
    )
    ensure_product(
        acme, "Weekend Hoodie", category=acme_hoodies,
        price=Decimal("49.99"), stock=25, sku="ACM-HOOD-001",
        description="Heavyweight fleece hoodie for slow Sundays and cold "
                    "studios. Brushed inside, kangaroo pocket.",
    )
    nike_tees = ensure_category(nike, "Tees")
    ensure_product(
        nike, "Sport Tee", category=nike_tees,
        price=Decimal("29.99"), stock=40, sku="NKE-TEE-001", featured=True,
        description="Lightweight training tee with a breathable knit and "
                    "sweat-wicking finish.",
    )

    # -- report ------------------------------------------------------------
    if created_items:
        print("[seed] created:")
        for item in created_items:
            print(f"       - {item}")
    else:
        print("[seed] demo data already present - nothing to do.")

    print(
        f"[seed] totals: {Business.objects.count()} stores | "
        f"{User.objects.count()} users | "
        f"{Product.objects.count()} products | "
        f"{Domain.objects.count()} domains"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
