"""
Host -> tenant resolution.

Kept out of the middleware so tests, seed scripts and management commands can
resolve a storefront without faking an HTTP request::

    from apps.tenants.resolvers import resolve_domain, resolve_business

    domain  = resolve_domain("acme.local-saas.com:8000")   # port tolerant
    business = resolve_business("acme.local-saas.com")

No cache layer yet on purpose: this is a single indexed SELECT on a UNIQUE
column per request, and a stale mapping would mean serving the wrong tenant's
data. Add cache + explicit invalidation on Domain.save() only if profiling
shows it is needed.
"""
from __future__ import annotations

from typing import Optional

from .models import Business, Domain, normalize_host


def resolve_domain(host: Optional[str]) -> Optional[Domain]:
    """Return the active Domain for a hostname (or None if it is unknown)."""
    normalized = normalize_host(host)
    if not normalized:
        return None
    return (
        Domain.objects.select_related("business")
        .filter(host=normalized, is_active=True)
        .first()
    )


def resolve_business(host: Optional[str]) -> Optional[Business]:
    """Return the Business behind a hostname (or None)."""
    domain = resolve_domain(host)
    return domain.business if domain is not None else None
