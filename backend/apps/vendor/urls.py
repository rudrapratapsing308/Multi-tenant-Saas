"""Vendor URLs: mounted at /api/v1/vendor/ in config/urls.py."""
from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

app_name = "vendor"

# SimpleRouter (not DefaultRouter): no browsable API-root HTML page.
router = SimpleRouter()
router.register("orders", views.VendorOrderViewSet, basename="vendor-order")
router.register("products", views.VendorProductViewSet, basename="vendor-product")
router.register("categories", views.VendorCategoryViewSet, basename="vendor-category")
router.register("promotions", views.VendorDiscountCodeViewSet, basename="vendor-promotion")

urlpatterns = [
    path("analytics/", views.VendorAnalyticsView.as_view(), name="vendor-analytics"),
    path("settings/", views.BrandConfigView.as_view(), name="vendor-settings"),
    *router.urls,
]
