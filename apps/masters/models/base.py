"""Abstract bases shared by every master-data model."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel


class MasterModel(TimeStampedModel):
    """Common behaviour for reference/lookup records.

    Masters are configuration data (RULES Phase 2): they are never soft
    deleted, instead they carry an ``is_active`` flag so they can be retired
    without breaking historical references.
    """

    is_active = models.BooleanField(_("active"), default=True, db_index=True)

    class Meta:
        abstract = True
        ordering = ["name"]


class NamedMaster(MasterModel):
    """A master with a unique human-readable ``name``."""

    name = models.CharField(_("name"), max_length=150, unique=True)

    class Meta(MasterModel.Meta):
        abstract = True

    def __str__(self) -> str:
        return self.name


class CodedMaster(NamedMaster):
    """A named master that also carries an optional short code."""

    code = models.CharField(_("code"), max_length=30, unique=True)

    class Meta(NamedMaster.Meta):
        abstract = True

    def __str__(self) -> str:
        return f"{self.code} · {self.name}" if self.code else self.name
