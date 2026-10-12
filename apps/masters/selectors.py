"""Read-only query helpers for master data."""

from __future__ import annotations

from django.db.models import Q

from .registry import MasterSpec


def master_queryset(
    spec: MasterSpec,
    *,
    search: str | None = None,
    is_active: bool | None = None,
):
    """Return the master records for ``spec`` with optional search/status filters."""
    qs = spec.model.objects.all()
    if search and spec.search_fields:
        condition = Q()
        for field in spec.search_fields:
            condition |= Q(**{f"{field}__icontains": search})
        qs = qs.filter(condition)

    if is_active is not None and any(
        f.name == "is_active" for f in spec.model._meta.fields
    ):
        qs = qs.filter(is_active=is_active)

    select_related = []
    for f in spec.model._meta.fields:
        if f.is_relation and f.many_to_one:
            select_related.append(f.name)
    if select_related:
        qs = qs.select_related(*select_related)
    return qs
