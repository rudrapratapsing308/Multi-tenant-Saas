"""Auth URLs: mounted at /api/v1/auth/ in config/urls.py."""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    # The SPA trades its (7-day) refresh token for a fresh access token.
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", views.CurrentUserView.as_view(), name="me"),
]
