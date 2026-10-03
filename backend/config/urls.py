"""
Root URL configuration - pure JSON API surface.

    /admin/                        -> Django admin (platform tooling only)
    /api/v1/storefront/init/       -> branding for the current host
    /api/v1/auth/                  -> register / login / token refresh / me
    /api/v1/catalog/               -> categories, products, reviews
    /api/v1/cart/                  -> the customer's cart (per store)
    /api/v1/orders/                -> checkout + order history
    /api/v1/vendor/                -> dashboard endpoints (orders)

Namespace map (modules still to come):
    /api/v1/promotions/ promotions - public vouchers API
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/storefront/", include("apps.storefront.urls")),
    path("api/v1/catalog/", include("apps.catalog.urls")),
    path("api/v1/cart/", include("apps.cart.urls")),
    path("api/v1/orders/", include("apps.orders.urls")),
    path("api/v1/vendor/", include("apps.vendor.urls")),
    path("api/v1/superadmin/", include("apps.superadmin.urls")),
    # path("api/v1/promotions/", include("apps.promotions.urls")),  # public vouchers API
]

# Serve uploaded tenant media (logos, banners) straight from Django in dev.
# ``static()`` returns an empty list when DEBUG is off.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
