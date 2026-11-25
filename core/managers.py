"""Reusable model managers and querysets for IHMS."""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    """Queryset exposing soft-delete/restore helpers."""

    def alive(self) -> "SoftDeleteQuerySet":
        """Return only non-deleted rows."""
        return self.filter(is_deleted=False)

    def dead(self) -> "SoftDeleteQuerySet":
        """Return only soft-deleted rows."""
        return self.filter(is_deleted=True)

    def soft_delete(self) -> int:
        """Soft-delete every row in the queryset."""
        return self.update(is_deleted=True, deleted_at=timezone.now())

    def restore(self) -> int:
        """Restore every soft-deleted row in the queryset."""
        return self.update(is_deleted=False, deleted_at=None)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Default manager that hides soft-deleted rows."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        """Return only rows that have not been soft-deleted."""
        return super().get_queryset().filter(is_deleted=False)


class AllObjectsManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Manager that includes soft-deleted rows (for admin/audit use)."""
