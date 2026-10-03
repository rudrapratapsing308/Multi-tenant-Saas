"""
Django BASE settings - shared by every environment.

Environment-specific values (DEBUG, database, CORS origins, proxy trust) live
in development.py / production.py, which do ``from .base import *``.

This project is an **API-only** backend: it serves JSON + uploaded media and
never renders storefront HTML. The only templates Django knows about are the
ones bundled with ``django.contrib.admin`` (platform tooling), and the React
frontend consumes this service over REST from a separate origin.
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from corsheaders.defaults import default_headers  # CORS default request headers

# backend/ (this file is backend/config/settings/base.py -> up 3 levels)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --- Core security ---------------------------------------------------------
# Generate a real one: python -c "from django.core.management.utils import \
#     get_random_secret_key; print(get_random_secret_key())"
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "insecure-dev-only-key-please-override-in-production"
)

# base = hardened defaults; development.py flips this on for local work.
DEBUG = False

# Populated by the environment files; development.py also adds dev hosts.
ALLOWED_HOSTS: list[str] = [
    host for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if host
]

# --- Applications ----------------------------------------------------------
INSTALLED_APPS = [
    # Django contrib (admin is platform tooling only - no storefront templates)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 3rd party
    "corsheaders",   # registers a system check that validates our CORS config
    "rest_framework",
    # Project apps. ``core`` first (abstract bases), then the tenancy kernel -
    # every other app points a ForeignKey at tenants.Business by string name.
    "apps.core",
    "apps.tenants",
    "apps.accounts",
    "apps.storefront",
    "apps.catalog",
    "apps.cart",        # session/server-side cart
    "apps.orders",      # checkout + order history
    "apps.promotions",
    "apps.analytics",   # populated in the analytics module
    "apps.vendor",      # vendor dashboard API (views only, no models)
    "apps.superadmin",  # platform owner API (views only, no models)
]

# --- Middleware ------------------------------------------------------------
# Order matters:
#  * CorsMiddleware must run before CommonMiddleware so preflights are answered
#    even for requests the tenant layer would reject.
#  * RequestTenantMiddleware runs early so *every* later component can rely on
#    request.tenant, and so unknown hosts fail fast with a JSON 404.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "apps.tenants.middleware.RequestTenantMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Django still needs templates for admin pages and error pages - there are no
# storefront templates in this project by design.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Filled in by the environment settings module.
DATABASES: dict = {}

# --- Auth ------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalisation ---------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static files & media ---------------------------------------------------
# /static/ -> aggregated CSS/JS (collectstatic target = STATIC_ROOT)
# /media/  -> tenant uploads: logos, banners, product images
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django REST Framework ---------------------------------------------------
REST_FRAMEWORK = {
    # Strictly JSON: no Browsable API HTML shell.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        # Needed for logo/banner uploads from the vendor dashboard.
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Primary: Bearer tokens issued by /api/v1/auth/login/ (the SPA never
        # relies on cookies -> no CSRF surface for the React app).
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        # Kept for Django admin, DRF dev tooling and browser sessions.
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    # The storefront is public. Write endpoints opt into stricter permissions
    # (and, above all, tenant query scoping) explicitly in their own views.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

# --- JWT (djangorestframework-simplejwt) ------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    # A refresh response carries a fresh refresh token, so the SPA can keep
    # sliding the session. Blacklisting old ones would require the optional
    # token_blacklist app; the lifetimes bound reuse instead.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# --- CORS (React dev server runs on a different origin) ----------------------
# NOTE: every custom header below must be listed here, otherwise the browser
# preflight rejects it and the frontend can never send it.
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    *default_headers,          # accept, authorization, content-type, ...
    "x-forwarded-host",        # frontend tells us which storefront it browsed
    "x-tenant-host",           # explicit escape hatch for local tooling
]
# Origins are environment specific -> see development.py / production.py.

# --- Multi-tenancy -----------------------------------------------------------
# Hosts are resolved to a Business by the middleware. Paths in this list are
# reachable without a resolvable tenant (platform endpoints, auth, admin,
# static/media). request.tenant is still attached whenever it CAN be resolved,
# so a vendor logging in from their own subdomain still gets request.tenant.
TENANT_EXEMPT_PATH_PREFIXES = (
    "/admin/",
    "/static/",
    "/media/",
    "/api/v1/auth/",
    "/api/v1/platform/",
    # The platform owner oversees ALL tenants, so their API must work from
    # any host (IsSuperAdmin ignores request.tenant by design).
    "/api/v1/superadmin/",
    "/healthz/",
)

# Trust the X-Forwarded-Host request header?
#   * development: the React app at localhost:5173 calls the API at
#     localhost:8000 and sends X-Forwarded-Host: <window.location.host> so the
#     API can tell which storefront the browser is looking at.
#   * production: ONLY enable this behind a proxy that OVERWRITES/validates the
#     header - otherwise a client could pick another tenant's host. Keep False
#     when the API is reached directly, because then Host is authoritative.
TENANT_TRUST_X_FORWARDED_HOST = False
# Only meaningful together with the flag above (see development.py).
USE_X_FORWARDED_HOST = False

# Zone used when a vendor registers a store: 'acme' -> 'acme.<zone>'.
# development: the dns_simulator.py sandbox zone; production: your real domain.
TENANT_DOMAIN_ZONE = "local-saas.com"

# --- Security headers --------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
