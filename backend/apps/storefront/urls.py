"""URLs of the storefront app: /api/v1/storefront/ -> views."""
from django.urls import path

from . import views

app_name = "storefront"

urlpatterns = [
    # /api/v1/storefront/init/
    path("init/", views.StorefrontInitView.as_view(), name="init"),
]
