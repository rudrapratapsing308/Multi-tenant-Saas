"""
RequestTenantMiddleware - the HTTP entry point of the tenancy engine.

Runs for *every* request (it sits high in MIDDLEWARE, right after CORS) and
answers three questions before any view executes:

    1. Which hostname did the client ask for?
       X-Tenant-Host (explicit, dev tooling)
       -> X-Forwarded-Host (only if TENANT_TRUST_X_FORWARDED_HOST)
       -> Host
    2. Which Business owns it?   Domain lookup (port stripped, lower-cased)
    3. May this request proceed?

and attaches the answers to the request object:

    request.tenant         -> Business | None     (what every view scopes by)
    request.tenant_domain  -> Domain   | None
    request.tenant_host    -> str      | None     (normalised hostname)

Failure modes (JSON, never an HTML error page):

    unknown host  -> 404 {"error": "store_not_found", ...}
    suspended or
    blocked store -> 403 {"error": "store_unavailable", ...}

Requests whose path starts with TENANT_EXEMPT_PATH_PREFIXES (platform API,
auth, admin, static/media) may proceed without a tenant - they serve the whole
platform - but they still get request.tenant when the host happens to resolve,
so a vendor logging in from their own subdomain keeps tenant context.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.cache import patch_vary_headers

from .models import normalize_host
from .resolvers import resolve_domain

logger = logging.getLogger(__name__)

# Headers are part of the cache key: two hosts must never share a cached body.
VARY_HEADERS = ("Host", "X-Tenant-Host", "X-Forwarded-Host")


class RequestTenantMiddleware:
    """Resolve ``Host`` -> Domain -> Business and enforce store availability."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.exempt_prefixes: tuple[str, ...] = tuple(
            getattr(settings, "TENANT_EXEMPT_PATH_PREFIXES", ())
        )
        self.trust_forwarded = bool(
            getattr(settings, "TENANT_TRUST_X_FORWARDED_HOST", False)
        )

    def __call__(self, request: HttpRequest) -> HttpResponse:
        host = self.extract_host(request)
        domain = resolve_domain(host)

        request.tenant_host = normalize_host(host) or None
        request.tenant_domain = domain
        request.tenant = domain.business if domain is not None else None

        error = self._reject(request)
        if error is not None:
            return error

        response = self.get_response(request)
        patch_vary_headers(response, VARY_HEADERS)
        return response

    # -- header handling ------------------------------------------------------
    def extract_host(self, request: HttpRequest) -> str:
        """
        Pick the authoritative hostname for this request.

        Precedence is deliberate: the explicit ``X-Tenant-Host`` wins (it is
        how local tooling says "I am browsing acme.local-saas.com"), then the
        proxy header, then the plain ``Host``. The first two are only trusted
        when TENANT_TRUST_X_FORWARDED_HOST is on, otherwise a remote client
        could hand-pick another tenant's host.
        """
        meta = request.META
        if self.trust_forwarded:
            explicit = meta.get("HTTP_X_TENANT_HOST", "").strip()
            if explicit:
                return explicit
            forwarded = meta.get("HTTP_X_FORWARDED_HOST", "").strip()
            if forwarded:
                return forwarded
        return meta.get("HTTP_HOST") or meta.get("SERVER_NAME") or ""

    # -- enforcement ----------------------------------------------------------
    def _reject(self, request: HttpRequest) -> Optional[JsonResponse]:
        """Return a JSON error response, or None when the request may proceed."""
        if self._is_exempt(request.path_info):
            return None

        if request.tenant is None:
            logger.info("tenant not found for host=%r path=%r",
                        request.tenant_host, request.path_info)
            return self._json_error(
                request,
                status=404,
                error="store_not_found",
                host=request.tenant_host,
                detail=f"No storefront is registered for host "
                       f"'{request.tenant_host or '<missing Host header>'}'.",
                hint="Register the hostname in the Domain table, or send "
                     "X-Tenant-Host: <store host> when calling the API "
                     "directly (curl/Postman/local frontend).",
            )

        if not request.tenant.is_active:
            logger.warning("host=%r path=%r rejected: business %s is %s",
                           request.tenant_host, request.path_info,
                           request.tenant.slug, request.tenant.status)
            return self._json_error(
                request,
                status=403,
                error="store_unavailable",
                detail="This store is currently unavailable.",
                store_status=request.tenant.status,
            )

        return None

    def _is_exempt(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self.exempt_prefixes)

    @staticmethod
    def _json_error(request: HttpRequest, *, status: int, **payload) -> JsonResponse:
        response = JsonResponse(payload, status=status)
        patch_vary_headers(response, VARY_HEADERS)
        return response
