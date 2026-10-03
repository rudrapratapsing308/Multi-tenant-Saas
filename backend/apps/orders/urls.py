"""Order URLs: mounted at /api/v1/orders/ in config/urls.py."""
from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("", views.OrderListView.as_view(), name="order-list"),
]
