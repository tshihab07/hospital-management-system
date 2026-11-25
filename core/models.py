"""Base abstract models shared across every IHMS app.

Every concrete model in the project MUST inherit from :class:`TimeStampedModel`
(or a subclass such as :class:`SoftDeleteModel`) per RULES §2.3.
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.utils import timezone

from .managers import AllObjectsManager, SoftDeleteManager


class TimeStampedModel(models.Model):
    """Abstract base adding ``created_at`` / ``updated_at`` timestamps."""

    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True, help_text="Row creation timestamp (BST)."
    )
    updated_at = models.DateTimeField(
        auto_now=True, help_text="Last modification timestamp (BST)."
    )

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class SoftDeleteModel(TimeStampedModel):
    """Abstract base adding safe, reversible soft deletion.

    Hard deletes are discouraged for clinical and financial records
    (RULES §2.3.3). Use :meth:`soft_delete` instead of :meth:`delete`.
    """

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta(TimeStampedModel.Meta):
        abstract = True

    def soft_delete(self) -> None:
        """Mark the row as deleted without removing it from the database."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def restore(self) -> None:
        """Undo a previous soft delete."""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def delete(
        self, using: str | None = None, keep_parents: bool = False, hard: bool = False
    ) -> Any:
        """Soft-delete by default; pass ``hard=True`` for a real delete."""
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        self.soft_delete()
        return (0, {})


class ActiveManager(models.Manager):
    """Manager returning only rows where ``is_active`` is true."""

    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(is_active=True)
