"""
Development settings.

Run the API with:      python manage.py runserver 0.0.0.0:8000
Tenant subdomains:     acme.local-saas.com:8000  (see /dns_simulator.py)
"""
# Django's settings-inheritance idiom. Pyflakes reports F403/F405 for this
# file because it cannot follow star imports (the noqa is for flake8 users);
# every name used below is defined in .base.
from .base import *  # noqa: F403,F405

DEBUG = True

# ``*.local-saas.com`` is the sandbox zone served by dns_simulator.py; Django
# validates the Host BEFORE our middleware runs (CommonMiddleware calls
# get_host()), so tenant hosts must be listed here or Django answers with a
# 400 Bad Request instead of our JSON 404.
# NOTE: Django's wildcard syntax is a LEADING DOT, not "*". '.local-saas.com'
# matches the apex (local-saas.com) and every subdomain; '*.local-saas.com'
# would be matched literally and never match anything.
ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "[::1]",
    ".local-saas.com",
    "testserver",  # appended by Django's test setup anyway; explicit for clarity
]

# --- Database ---------------------------------------------------------------
# SQLite for local development. Path is inside backend/db/ so the data file
# never mixes with source code or uploaded media.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db" / "db.sqlite3",  # noqa: F405
    }
}

# --- E-mail ------------------------------------------------------------------
# Order confirmations, vouchers, ... printed to the console while developing.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# --- CORS / CSRF (React dev server) ------------------------------------------
_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Storefronts are browsed through their own hostname + the Vite port, e.g.
# http://acme.local-saas.com:5173 -> allow every tenant origin with a regex.
CORS_ALLOWED_ORIGINS = _DEV_ORIGINS
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://([a-z0-9-]+\.)*local-saas\.com(:[0-9]+)?$",
]

# Required for session-authenticated POSTs coming from another origin; Django
# rejects foreign origins without this. Wildcard entries are expanded to a
# leading-dot netloc by the CSRF middleware, and the PORT must be spelled out
# (an origin with :5173 never matches a portless pattern), hence one entry for
# storefronts served on port 80 and one for the Vite dev server.
CSRF_TRUSTED_ORIGINS = [
    *_DEV_ORIGINS,
    "http://*.local-saas.com",        # http://acme.local-saas.com
    "http://*.local-saas.com:5173",   # http://acme.local-saas.com:5173 (Vite)
]

# --- Proxy trust --------------------------------------------------------------
# In development the API is called directly (no reverse proxy), so trusting
# these headers is safe and lets the frontend announce which storefront it is
# rendering:  X-Forwarded-Host: acme.local-saas.com:5173
# Revisit BOTH flags in production (see base.py).
TENANT_TRUST_X_FORWARDED_HOST = True
USE_X_FORWARDED_HOST = True
