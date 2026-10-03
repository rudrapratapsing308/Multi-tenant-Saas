"""
Shared abstract models used by every app (no business rules live here).
"""
from __future__ import annotations

from django.db import models


class TimeStampedModel(models.Model):
    """
    ``created_at`` / ``updated_at`` audit columns.

    Abstract -> adds no table of its own; inherit it in concrete models:

        class Product(TimeStampedModel):
            ...
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
