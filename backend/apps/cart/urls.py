"""Cart URLs: mounted at /api/v1/cart/ in config/urls.py."""
from django.urls import path

from . import views

app_name = "cart"

urlpatterns = [
    path("", views.CartView.as_view(), name="cart"),
]
