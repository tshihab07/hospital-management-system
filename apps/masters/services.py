"""Write operations for master data (atomic + audit).

RULES §2.2: models -> services -> views. Every mutation runs in a transaction
and writes an :class:`AuditLog` entry with a before/after diff.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Model

from core.audit import AuditAction, log_action, model_to_dict_safe


def _diff(before: dict, after: dict) -> dict:
    changed = {}
    for key, value in after.items():
        if key in {"updated_at", "created_at"}:
            continue
        if before.get(key) != value:
            changed[key] = {"from": before.get(key), "to": value}
    return changed


@transaction.atomic
def create_master(*, model: type[Model], data: dict, actor=None, request=None) -> Model:
    """Create a master record and audit it."""
    data = dict(data)
    instance = model.objects.create(**data)
    log_action(
        AuditAction.CREATE,
        instance=instance,
        changes=model_to_dict_safe(instance),
        user=actor,
        request=request,
    )
    return instance


@transaction.atomic
def update_master(*, instance: Model, data: dict, actor=None, request=None) -> Model:
    """Update a master record and audit the diff."""
    before = model_to_dict_safe(instance)
    for field, value in dict(data).items():
        setattr(instance, field, value)
    instance.save()
    log_action(
        AuditAction.UPDATE,
        instance=instance,
        changes=_diff(before, model_to_dict_safe(instance)),
        user=actor,
        request=request,
    )
    return instance


@transaction.atomic
def toggle_master_active(*, instance: Model, actor=None, request=None) -> Model:
    """Flip the ``is_active`` flag on a master record."""
    instance.is_active = not instance.is_active
    instance.save(update_fields=["is_active", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=instance,
        changes={"is_active": {"to": instance.is_active}},
        user=actor,
        request=request,
    )
    return instance


@transaction.atomic
def delete_master(*, instance: Model, actor=None, request=None) -> None:
    """Hard-delete a master record (protected FKs raise ``ProtectedError``)."""
    label = str(instance)
    log_action(
        AuditAction.DELETE,
        instance=instance,
        changes={"repr": label},
        user=actor,
        request=request,
    )
    instance.delete()
