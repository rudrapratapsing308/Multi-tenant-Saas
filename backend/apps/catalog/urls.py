"""Catalog URLs: mounted at /api/v1/catalog/ in config/urls.py."""
from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

app_name = "catalog"

# SimpleRouter (not DefaultRouter): no browsable API-root HTML page.
router = SimpleRouter()
router.register("products", views.ProductViewSet, basename="product")

urlpatterns = [
    path("categories/", views.CategoryListView.as_view(), name="category-list"),
    path("reviews/", views.ReviewCreateView.as_view(), name="review-create"),
    *router.urls,  # products/ and products/<pk>/
]
