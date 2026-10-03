"""
Public catalog endpoints.

THE RULE (enforced in every get_queryset below): every queryset starts with
``Model.objects.for_tenant(request.tenant)``. An id from another store simply
does not exist for this request -> 404, never data.
"""
from __future__ import annotations

from django.db.models import Prefetch, Q
from rest_framework import mixins
from rest_framework.generics import CreateAPIView, ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from apps.accounts.permissions import IsCustomer

from .models import Category, Product, ProductVariant, Review
from .serializers import (
    CategorySerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    ReviewSerializer,
)


class CategoryListView(ListAPIView):
    """GET /api/v1/catalog/categories/ - active categories of this store."""

    serializer_class = CategorySerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return (
            Category.objects.for_tenant(self.request.tenant)
            .filter(is_active=True)
            .select_related("parent")
        )


class ProductViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, GenericViewSet):
    """
    GET /api/v1/catalog/products/          - active products of this store
    GET /api/v1/catalog/products/<id>/     - one product + variants + approved reviews

    Query params (list): ``category=<slug>``, ``featured=true``, ``search=<text>``.
    """

    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ProductDetailSerializer
        return ProductListSerializer

    def get_queryset(self):
        tenant = self.request.tenant
        queryset = (
            Product.objects.for_tenant(tenant)
            .filter(is_active=True)
            .select_related("category")
        )

        params = self.request.query_params
        category = params.get("category")
        if category:
            queryset = queryset.filter(category__slug=category)
        if str(params.get("featured", "")).lower() in ("1", "true", "yes"):
            queryset = queryset.filter(is_featured=True)
        search = params.get("search") or params.get("q")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(description__icontains=search)
            )

        if self.action == "retrieve":
            # Load exactly what the detail payload shows, still tenant-scoped.
            queryset = queryset.prefetch_related(
                Prefetch(
                    "variants",
                    queryset=ProductVariant.objects.for_tenant(tenant).filter(
                        is_active=True
                    ),
                    to_attr="active_variants",
                ),
                Prefetch(
                    "reviews",
                    queryset=Review.objects.for_tenant(tenant)
                    .filter(status=Review.Status.APPROVED)
                    .select_related("customer")
                    .order_by("-created_at"),
                    to_attr="approved_reviews",
                ),
            )
        return queryset


class ReviewCreateView(CreateAPIView):
    """
    POST /api/v1/catalog/reviews/ - authenticated customers only.

    Validation chain: product must exist in THIS store (scoped field queryset)
    -> the customer must have bought it (non-cancelled order) -> one review per
    customer per product. The row lands as PENDING until the vendor approves.
    """

    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticated, IsCustomer]
