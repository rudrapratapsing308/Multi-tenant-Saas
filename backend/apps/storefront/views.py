"""
Storefront bootstrap endpoint.

    GET /api/v1/storefront/init/

Called exactly once by the React app on boot. The middleware has already
turned the incoming hostname into ``request.tenant`` (or answered 404), so a
view never has to re-implement host parsing - it just reads the tenant and
serialises its branding. This is the only view in this module; the rest of
the DRF surface lands in the next steps.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DEFAULT_THEME, Banner, BrandConfig


def _absolute(request, file_field) -> str | None:
    """Absolute URL for an uploaded file (logo/banner), or None if missing."""
    if not file_field:
        return None
    return request.build_absolute_uri(file_field.url)


class StorefrontInitView(APIView):
    """
    Return everything the frontend needs to render *this* store's shell:
    identity, brand assets, theme colours and the active banners.

    Payload shape (stable contract with the frontend)::

        {
          "store":  {id, slug, name, host, currency, timezone},
          "brand":  {brand_name, tagline, logo_url, favicon_url},
          "theme":  {primary_color, secondary_color, accent_color},
          "banners":[{id, title, subtitle, image_url, link_url}],
          "server_time": "..."
        }
    """

    authentication_classes = []          # public endpoint, no session/CSRF work
    permission_classes = [AllowAny]      # tenant scoping comes from the middleware

    def get(self, request):
        # The middleware guarantees a tenant on this path (JSON 404 otherwise);
        # getattr keeps the view safe if it is ever mounted on an exempt path.
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response(
                {
                    "error": "store_not_found",
                    "detail": "No storefront resolved for this request.",
                    "host": getattr(request, "tenant_host", None),
                },
                status=404,
            )

        now = timezone.now()

        # Missing BrandConfig is not an error: a brand-new store still boots
        # with its business name and the platform default palette.
        brand = BrandConfig.objects.for_tenant(tenant).filter(is_active=True).first()

        # A store has only a handful of banners, so the scheduling rules stay
        # in Banner.is_current() - one source of truth instead of a SQL clone.
        banners = [
            {
                "id": banner.pk,
                "title": banner.title,
                "subtitle": banner.subtitle,
                "image_url": _absolute(request, banner.image),
                "link_url": banner.link_url or None,
            }
            for banner in Banner.objects.for_tenant(tenant).filter(is_active=True)
            .order_by("position", "-created_at")
            if banner.is_current(now)
        ]

        payload = {
            "store": {
                "id": str(tenant.pk),
                "slug": tenant.slug,
                "name": tenant.name,
                "host": request.tenant_host,
                "currency": tenant.currency,
                "timezone": tenant.timezone,
            },
            "brand": {
                "brand_name": brand.display_name if brand else tenant.name,
                "tagline": brand.tagline if brand else "",
                "logo_url": _absolute(request, brand.logo) if brand else None,
                "favicon_url": _absolute(request, brand.favicon) if brand else None,
            },
            "theme": brand.theme if brand else dict(DEFAULT_THEME),
            "banners": banners,
            "server_time": now.isoformat(),
        }
        return Response(payload)
