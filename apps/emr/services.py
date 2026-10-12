"""Write operations for the EMR & CPOE module (atomic + audit).

Covers encounter lifecycle, SOAP documentation, vitals, visit diagnoses, the
longitudinal problem list & allergy register, clinical attachments and the CPOE
order set (prescriptions, lab/radiology/procedure) — including the basic
drug-interaction rules engine (RULES Phase 6).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.audit import AuditAction, log_action, model_to_dict_safe

from .models import (Allergy, ClinicalAttachment, DrugInteractionRule,
                     Encounter, EncounterStatus, EncounterType, LabOrder,
                     LabOrderItem, OrderStatus, Prescription, PrescriptionItem,
                     PrescriptionStatus, ProblemListEntry, ProcedureOrder,
                     RadiologyOrder, RadiologyOrderItem, SoapNote,
                     VisitDiagnosis, Vital)


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------
@transaction.atomic
def open_encounter(
    *,
    patient,
    doctor,
    appointment=None,
    encounter_type=None,
    chief_complaint: str = "",
    encounter_date=None,
    actor=None,
    request=None,
) -> tuple[Encounter, bool]:
    """Open (or reuse) the clinical encounter for a visit.

    When an ``appointment`` is supplied the encounter is idempotent: the same
    appointment never yields two encounters. Returns ``(encounter, created)``.
    """
    if appointment is not None:
        existing = Encounter.objects.filter(appointment=appointment).first()
        if existing is not None:
            return existing, False

    if encounter_type is None:
        encounter_type = EncounterType.OUTPATIENT
    if encounter_date is None:
        encounter_date = (
            appointment.appt_date if appointment is not None else timezone.localdate()
        )

    encounter = Encounter.objects.create(
        patient=patient,
        doctor=doctor,
        appointment=appointment,
        encounter_date=encounter_date,
        encounter_type=encounter_type,
        chief_complaint=chief_complaint,
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    log_action(
        AuditAction.CREATE,
        instance=encounter,
        changes=model_to_dict_safe(encounter),
        user=actor,
        request=request,
    )
    return encounter, True


@transaction.atomic
def close_encounter(*, instance: Encounter, actor=None, request=None) -> Encounter:
    """Close an open encounter (idempotent)."""
    if instance.status == EncounterStatus.CLOSED:
        return instance
    before = model_to_dict_safe(instance)
    instance.status = EncounterStatus.CLOSED
    instance.closed_at = timezone.now()
    instance.save(update_fields=["status", "closed_at", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=instance,
        changes={"before": before, "after": model_to_dict_safe(instance)},
        user=actor,
        request=request,
    )
    return instance


# ---------------------------------------------------------------------------
# SOAP documentation
# ---------------------------------------------------------------------------
@transaction.atomic
def save_soap_note(
    *,
    encounter: Encounter,
    subjective: str = "",
    objective: str = "",
    assessment: str = "",
    plan: str = "",
    template=None,
    actor=None,
    request=None,
) -> SoapNote:
    """Create or update the SOAP note for an encounter."""
    note, created = SoapNote.objects.update_or_create(
        encounter=encounter,
        defaults={
            "subjective": subjective,
            "objective": objective,
            "assessment": assessment,
            "plan": plan,
            "template": template,
            "authored_by": actor if getattr(actor, "pk", None) else None,
        },
    )
    log_action(
        AuditAction.CREATE if created else AuditAction.UPDATE,
        instance=note,
        changes=model_to_dict_safe(note),
        user=actor,
        request=request,
    )
    return note


# ---------------------------------------------------------------------------
# Vitals
# ---------------------------------------------------------------------------
@transaction.atomic
def record_vitals(
    *, encounter: Encounter, data: dict, actor=None, request=None
) -> Vital:
    """Record a vitals measurement against an encounter."""
    vital = Vital.objects.create(
        encounter=encounter,
        patient=encounter.patient,
        recorded_by=actor if getattr(actor, "pk", None) else None,
        **data,
    )
    log_action(
        AuditAction.CREATE,
        instance=vital,
        changes=model_to_dict_safe(vital),
        user=actor,
        request=request,
    )
    return vital


# ---------------------------------------------------------------------------
# Visit diagnoses
# ---------------------------------------------------------------------------
@transaction.atomic
def add_visit_diagnosis(
    *,
    encounter: Encounter,
    diagnosis=None,
    description: str = "",
    is_primary: bool = False,
    actor=None,
    request=None,
) -> VisitDiagnosis:
    """Record a diagnosis against an encounter (exclusive primary enforced)."""
    if is_primary:
        VisitDiagnosis.objects.filter(encounter=encounter, is_primary=True).update(
            is_primary=False
        )
    entry = VisitDiagnosis.objects.create(
        encounter=encounter,
        diagnosis=diagnosis,
        description=description,
        is_primary=is_primary,
    )
    log_action(
        AuditAction.CREATE,
        instance=entry,
        changes=model_to_dict_safe(entry),
        user=actor,
        request=request,
    )
    return entry


@transaction.atomic
def remove_visit_diagnosis(
    *, instance: VisitDiagnosis, actor=None, request=None
) -> None:
    """Remove a visit diagnosis from an encounter."""
    log_action(
        AuditAction.DELETE,
        instance=instance,
        changes=model_to_dict_safe(instance),
        user=actor,
        request=request,
    )
    instance.delete()


# ---------------------------------------------------------------------------
# Problem list & allergy register
# ---------------------------------------------------------------------------
@transaction.atomic
def add_problem(
    *,
    patient,
    description: str,
    diagnosis=None,
    onset_date=None,
    actor=None,
    request=None,
) -> ProblemListEntry:
    entry = ProblemListEntry.objects.create(
        patient=patient,
        diagnosis=diagnosis,
        description=description,
        onset_date=onset_date,
    )
    log_action(
        AuditAction.CREATE,
        instance=entry,
        changes=model_to_dict_safe(entry),
        user=actor,
        request=request,
    )
    return entry


@transaction.atomic
def resolve_problem(
    *, instance: ProblemListEntry, actor=None, request=None
) -> ProblemListEntry:
    """Mark a problem as resolved (idempotent)."""
    if not instance.is_active:
        return instance
    before = model_to_dict_safe(instance)
    instance.is_active = False
    instance.resolved_date = timezone.localdate()
    instance.save(update_fields=["is_active", "resolved_date", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=instance,
        changes={"before": before, "after": model_to_dict_safe(instance)},
        user=actor,
        request=request,
    )
    return instance


@transaction.atomic
def add_allergy(
    *,
    patient,
    allergen: str,
    allergy_type=None,
    reaction: str = "",
    severity=None,
    noted_on=None,
    actor=None,
    request=None,
) -> Allergy:
    """Add an entry to the patient's allergy register."""
    kwargs = {"patient": patient, "allergen": allergen, "reaction": reaction}
    if allergy_type is not None:
        kwargs["allergy_type"] = allergy_type
    if severity is not None:
        kwargs["severity"] = severity
    if noted_on is not None:
        kwargs["noted_on"] = noted_on
    allergy = Allergy.objects.create(**kwargs)
    log_action(
        AuditAction.CREATE,
        instance=allergy,
        changes=model_to_dict_safe(allergy),
        user=actor,
        request=request,
    )
    return allergy


# ---------------------------------------------------------------------------
# Drug-interaction rules engine
# ---------------------------------------------------------------------------
def check_drug_interactions(drug_ids) -> list[DrugInteractionRule]:
    """Return active interaction rules whose two drugs are both in ``drug_ids``.

    This is the basic Phase 6 rules engine: a pairwise lookup that fires an
    alert when a prescription contains two interacting drugs.
    """
    ids = {int(i) for i in drug_ids if i}
    if len(ids) < 2:
        return []
    rules = DrugInteractionRule.objects.filter(
        is_active=True, drug_a_id__in=ids, drug_b_id__in=ids
    ).select_related("drug_a", "drug_b")
    return [rule for rule in rules if rule.matches(ids)]


# ---------------------------------------------------------------------------
# CPOE: prescriptions
# ---------------------------------------------------------------------------
@transaction.atomic
def issue_prescription(
    *,
    encounter: Encounter,
    items: list[dict],
    notes: str = "",
    actor=None,
    request=None,
) -> tuple[Prescription, list[DrugInteractionRule]]:
    """Issue a prescription with item lines; returns ``(rx, interactions)``.

    Interaction alerts are advisory: the prescription is still issued but the
    caller is expected to surface the warnings to the prescriber.
    """
    if not items:
        raise ValueError(_("A prescription needs at least one drug."))

    prescription = Prescription.objects.create(
        encounter=encounter,
        patient=encounter.patient,
        doctor=encounter.doctor,
        status=PrescriptionStatus.ISSUED,
        notes=notes,
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    for row in items:
        PrescriptionItem.objects.create(prescription=prescription, **row)

    drug_ids = [row["drug"].pk for row in items]
    interactions = check_drug_interactions(drug_ids)

    log_action(
        AuditAction.CREATE,
        instance=prescription,
        changes=model_to_dict_safe(prescription),
        user=actor,
        request=request,
    )
    if interactions:
        log_action(
            AuditAction.UPDATE,
            instance=prescription,
            model_name="Prescription",
            object_id=prescription.pk,
            changes={
                "interaction_alerts": [rule.pk for rule in interactions],
                "severity": [rule.severity for rule in interactions],
            },
            user=actor,
            request=request,
        )
    return prescription, interactions


@transaction.atomic
def cancel_prescription(
    *, instance: Prescription, actor=None, request=None
) -> Prescription:
    """Cancel an issued prescription (idempotent)."""
    if instance.status == PrescriptionStatus.CANCELLED:
        return instance
    before = model_to_dict_safe(instance)
    instance.status = PrescriptionStatus.CANCELLED
    instance.save(update_fields=["status", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=instance,
        changes={"before": before, "after": model_to_dict_safe(instance)},
        user=actor,
        request=request,
    )
    return instance


# ---------------------------------------------------------------------------
# CPOE: lab / radiology / procedure orders
# ---------------------------------------------------------------------------
@transaction.atomic
def create_lab_order(
    *,
    encounter: Encounter,
    tests: list,
    priority=None,
    notes: str = "",
    actor=None,
    request=None,
) -> LabOrder:
    """Create a lab order for one or more tests."""
    if not tests:
        raise ValueError(_("Select at least one test."))
    kwargs = {"notes": notes}
    if priority is not None:
        kwargs["priority"] = priority
    order = LabOrder.objects.create(
        encounter=encounter,
        patient=encounter.patient,
        doctor=encounter.doctor,
        created_by=actor if getattr(actor, "pk", None) else None,
        **kwargs,
    )
    for test in tests:
        LabOrderItem.objects.create(order=order, test=test)
    log_action(
        AuditAction.CREATE,
        instance=order,
        changes=model_to_dict_safe(order),
        user=actor,
        request=request,
    )
    return order


@transaction.atomic
def create_radiology_order(
    *,
    encounter: Encounter,
    tests: list,
    priority=None,
    clinical_indication: str = "",
    notes: str = "",
    actor=None,
    request=None,
) -> RadiologyOrder:
    """Create a radiology order for one or more tests."""
    if not tests:
        raise ValueError(_("Select at least one test."))
    kwargs = {"clinical_indication": clinical_indication, "notes": notes}
    if priority is not None:
        kwargs["priority"] = priority
    order = RadiologyOrder.objects.create(
        encounter=encounter,
        patient=encounter.patient,
        doctor=encounter.doctor,
        created_by=actor if getattr(actor, "pk", None) else None,
        **kwargs,
    )
    for test in tests:
        RadiologyOrderItem.objects.create(order=order, test=test)
    log_action(
        AuditAction.CREATE,
        instance=order,
        changes=model_to_dict_safe(order),
        user=actor,
        request=request,
    )
    return order


@transaction.atomic
def create_procedure_order(
    *,
    encounter: Encounter,
    procedure,
    priority=None,
    scheduled_for=None,
    notes: str = "",
    actor=None,
    request=None,
) -> ProcedureOrder:
    """Create a procedure order."""
    kwargs = {"scheduled_for": scheduled_for, "notes": notes}
    if priority is not None:
        kwargs["priority"] = priority
    order = ProcedureOrder.objects.create(
        encounter=encounter,
        patient=encounter.patient,
        doctor=encounter.doctor,
        procedure=procedure,
        created_by=actor if getattr(actor, "pk", None) else None,
        **kwargs,
    )
    log_action(
        AuditAction.CREATE,
        instance=order,
        changes=model_to_dict_safe(order),
        user=actor,
        request=request,
    )
    return order


@transaction.atomic
def set_order_status(*, instance, status: str, actor=None, request=None):
    """Change the status of any CPOE order (idempotent)."""
    if status not in OrderStatus.values:
        raise ValueError(_("Unknown order status."))
    if instance.status == status:
        return instance
    before = model_to_dict_safe(instance)
    instance.status = status
    instance.save(update_fields=["status", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=instance,
        changes={"before": before, "after": model_to_dict_safe(instance)},
        user=actor,
        request=request,
    )
    return instance


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
@transaction.atomic
def add_attachment(
    *,
    patient,
    file,
    title: str,
    category=None,
    encounter=None,
    description: str = "",
    actor=None,
    request=None,
) -> ClinicalAttachment:
    """Attach a clinical file to a patient (optionally tied to an encounter)."""
    kwargs = {
        "patient": patient,
        "title": title,
        "file": file,
        "encounter": encounter,
        "description": description,
    }
    if category is not None:
        kwargs["category"] = category
    attachment = ClinicalAttachment.objects.create(
        uploaded_by=actor if getattr(actor, "pk", None) else None, **kwargs
    )
    log_action(
        AuditAction.CREATE,
        instance=attachment,
        changes=model_to_dict_safe(attachment),
        user=actor,
        request=request,
    )
    return attachment


@transaction.atomic
def remove_attachment(
    *, instance: ClinicalAttachment, actor=None, request=None
) -> None:
    """Soft-delete a clinical attachment."""
    log_action(
        AuditAction.DELETE,
        instance=instance,
        changes=model_to_dict_safe(instance),
        user=actor,
        request=request,
    )
    instance.soft_delete()
