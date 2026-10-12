"""Write operations for patients (atomic + audit).

Every mutation runs inside a transaction and writes an :class:`AuditLog`
entry. UHID allocation uses a row-locked per-year sequence so concurrent
registrations can never collide (RULES Phase 3).
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.audit import AuditAction, log_action, model_to_dict_safe

from .models import Patient, PatientDocument, PatientSequence

UHID_PREFIX = settings.IHMS.get("UHID_PREFIX", "DHK")
UHID_WIDTH = 6


def _diff(before: dict, after: dict) -> dict:
    changed = {}
    for key, value in after.items():
        if key in {"updated_at", "created_at"}:
            continue
        if before.get(key) != value:
            changed[key] = {"from": before.get(key), "to": value}
    return changed


def format_uhid(prefix: str, year: int, number: int) -> str:
    """Compose a UHID such as ``DHK-2026-000123``."""
    return f"{prefix}-{year}-{number:0{UHID_WIDTH}d}"


def _normalise(payload: dict) -> dict:
    """Fold empty values back to their model defaults.

    Optional form fields submit ``""`` for fields the operator left untouched;
    sending that would override the model default (e.g. blood group). Fields
    with no default keep a real empty value (used to clear a field on edit).
    """
    import django.db.models as m

    fields = {f.name: f for f in Patient._meta.fields}
    normalised = {}
    for key, value in payload.items():
        if value is None:
            continue
        field = fields.get(key)
        if value == "" and field is not None and field.default is not m.NOT_PROVIDED:
            normalised[key] = field.get_default()
        else:
            normalised[key] = value
    return normalised


@transaction.atomic
def generate_uhid(year: int | None = None) -> str:
    """Allocate the next UHID for ``year`` using a locked sequence row."""
    year = year or timezone.localdate().year
    sequence, _ = PatientSequence.objects.get_or_create(year=year)
    sequence = PatientSequence.objects.select_for_update().get(pk=sequence.pk)
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])
    return format_uhid(UHID_PREFIX, year, sequence.last_number)


@transaction.atomic
def register_patient(*, data: dict, actor=None, request=None) -> Patient:
    """Create a patient, assigning a fresh UHID."""
    payload = _normalise(dict(data))
    payload.pop("uhid", None)
    patient = Patient(**payload)
    patient.uhid = generate_uhid()
    patient.registered_by = actor
    patient.full_clean(exclude=None)
    patient.save()
    log_action(
        AuditAction.CREATE,
        instance=patient,
        changes=model_to_dict_safe(patient),
        user=actor,
        request=request,
    )
    return patient


@transaction.atomic
def update_patient(
    *, instance: Patient, data: dict, actor=None, request=None
) -> Patient:
    """Update a patient and audit the field-level diff."""
    before = model_to_dict_safe(instance)
    payload = _normalise(dict(data))
    payload.pop("uhid", None)
    for field, value in payload.items():
        setattr(instance, field, value)
    instance.full_clean(exclude=None)
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
def soft_delete_patient(*, instance: Patient, actor=None, request=None) -> Patient:
    """Soft-delete a patient (RULES §2.3.3)."""
    instance.soft_delete()
    log_action(
        AuditAction.DELETE,
        instance=instance,
        changes={"is_deleted": {"to": True}},
        user=actor,
        request=request,
    )
    return instance


@transaction.atomic
def restore_patient(*, instance: Patient, actor=None, request=None) -> Patient:
    """Reinstate a soft-deleted patient."""
    instance.restore()
    log_action(
        AuditAction.UPDATE,
        instance=instance,
        changes={"is_deleted": {"to": False}},
        user=actor,
        request=request,
    )
    return instance


@transaction.atomic
def add_document(
    *, patient: Patient, data: dict, actor=None, request=None
) -> PatientDocument:
    """Attach a scanned document to a patient."""
    document = PatientDocument.objects.create(
        patient=patient,
        uploaded_by=actor,
        **data,
    )
    log_action(
        AuditAction.CREATE,
        instance=document,
        changes=model_to_dict_safe(document),
        user=actor,
        request=request,
    )
    return document


@transaction.atomic
def merge_patients(
    *, primary: Patient, duplicate: Patient, actor=None, request=None
) -> Patient:
    """Merge ``duplicate`` into ``primary`` and soft-delete the duplicate.

    Currently only documents exist as dependents; future phases extend this
    to move encounters, bills and orders. The action is fully audited.
    """
    if primary.pk == duplicate.pk:
        raise ValueError("Cannot merge a patient into itself.")

    moved = 0
    for document in duplicate.documents.all():
        document.patient = primary
        document.save(update_fields=["patient", "updated_at"])
        moved += 1

    duplicate.soft_delete()
    log_action(
        AuditAction.UPDATE,
        instance=primary,
        changes={
            "merged_from": {
                "to": duplicate.uhid,
                "documents_moved": moved,
            }
        },
        user=actor,
        request=request,
    )
    return primary
