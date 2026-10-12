"""Write operations for the IPD — Admission & Bed Management module (atomic + audit).

Covers the admission advice → bed allocation → care workflow (nursing notes,
MAR, intake/output, transfers) → discharge (order → clearance → summary).
The bed-allocation engine is guarded by row locks and database-level partial
unique constraints so a bed can never be double-booked. IP numbers are minted
via the per-year row-locked :class:`AdmissionSequence` counter (RULES Phase 7).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.audit import AuditAction, log_action, model_to_dict_safe

from .models import (Admission, AdmissionSequence, AdmissionStatus, Bed,
                     BedStatus, BedTransfer, DailyCharge, DischargeClearance,
                     DischargeSummary, IntakeOutput, MarAction,
                     MedicationAdministration, NursingNote)


def _prefix() -> str:
    return settings.IHMS.get("IP_PREFIX", "IP")


def _width() -> int:
    return int(settings.IHMS.get("IP_NUMBER_WIDTH", 5))


@transaction.atomic
def generate_ip_number(now=None) -> str:
    """Mint a ``IP-YYYY-NNNNN`` number using a row-locked per-year counter."""
    now = now or timezone.now()
    seq, _ = AdmissionSequence.objects.get_or_create(year=now.year)
    seq = AdmissionSequence.objects.select_for_update().get(pk=seq.pk)
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    return f"{_prefix()}-{now.year}-{seq.last_number:0{_width()}d}"


def _active_admission(patient) -> Admission | None:
    return Admission.objects.filter(
        patient=patient,
        status__in=[
            AdmissionStatus.REQUESTED,
            AdmissionStatus.ADMITTED,
            AdmissionStatus.DISCHARGE_REQUESTED,
        ],
    ).first()


@transaction.atomic
def request_admission(
    *,
    patient,
    doctor,
    admission_type=None,
    reason: str,
    admission_note: str = "",
    encounter=None,
    actor=None,
    request=None,
) -> Admission:
    """Create an admission advice (no bed allocated yet)."""
    from .models import AdmissionType

    existing = _active_admission(patient)
    if existing is not None:
        raise ValueError(_("The patient already has an active admission."))
    admission = Admission.objects.create(
        patient=patient,
        doctor=doctor,
        encounter=encounter,
        admission_type=admission_type or AdmissionType.ROUTINE,
        reason=reason,
        admission_note=admission_note,
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    log_action(
        AuditAction.CREATE,
        instance=admission,
        changes=model_to_dict_safe(admission),
        user=actor,
        request=request,
    )
    return admission


@transaction.atomic
def allocate_bed(
    *, admission: Admission, bed: Bed, actor=None, request=None
) -> Admission:
    """Allocate a bed, mint the IP number and admit the patient.

    Raises ``ValueError`` when the bed is unavailable; a row lock plus the
    ``uniq_bed_active_admission`` constraint guarantee no double-booking.
    """
    if admission.status != AdmissionStatus.REQUESTED:
        raise ValueError(_("Only requested admissions can be allocated a bed."))
    if admission.ip_number:
        raise ValueError(_("The admission already has a bed."))

    locked = Bed.objects.select_for_update().get(pk=bed.pk)
    if locked.status != BedStatus.AVAILABLE:
        raise ValueError(
            _("Bed %(bed)s is not available (status: %(status)s).")
            % {"bed": locked, "status": locked.get_status_display()}
        )
    locked.status = BedStatus.OCCUPIED
    locked.save(update_fields=["status", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=locked,
        changes={
            "before": {"status": BedStatus.AVAILABLE},
            "after": {"status": BedStatus.OCCUPIED},
        },
        user=actor,
        request=request,
    )

    admission.ip_number = generate_ip_number()
    admission.bed = locked
    admission.status = AdmissionStatus.ADMITTED
    admission.admitted_at = timezone.now()
    admission.save()
    log_action(
        AuditAction.UPDATE,
        instance=admission,
        changes=model_to_dict_safe(admission),
        user=actor,
        request=request,
    )
    return admission


@transaction.atomic
def transfer_bed(
    *,
    admission: Admission,
    to_bed: Bed,
    reason: str = "",
    actor=None,
    request=None,
) -> BedTransfer:
    """Move an admitted patient to another bed (within or across wards)."""
    from .models import BedStatus

    if not admission.is_active_admission or admission.bed_id is None:
        raise ValueError(_("Only admitted patients can be transferred."))
    if admission.bed_id == to_bed.pk:
        raise ValueError(_("The patient is already in that bed."))

    locked = Bed.objects.select_for_update().get(pk=to_bed.pk)
    if locked.status != BedStatus.AVAILABLE:
        raise ValueError(
            _("Bed %(bed)s is not available (status: %(status)s).")
            % {"bed": locked, "status": locked.get_status_display()}
        )

    from_bed = admission.bed
    old_ward = from_bed.ward.name if from_bed else ""
    new_ward = locked.ward.name

    locked.status = BedStatus.OCCUPIED
    locked.save(update_fields=["status", "updated_at"])
    if from_bed is not None:
        Bed.objects.filter(pk=from_bed.pk).update(
            status=BedStatus.AVAILABLE, updated_at=timezone.now()
        )

    transfer = BedTransfer.objects.create(
        admission=admission,
        from_bed=from_bed,
        to_bed=locked,
        from_ward=old_ward,
        to_ward=new_ward,
        reason=reason,
        transferred_by=actor if getattr(actor, "pk", None) else None,
    )
    admission.bed = locked
    admission.save(update_fields=["bed", "updated_at"])
    log_action(
        AuditAction.CREATE,
        instance=transfer,
        changes=model_to_dict_safe(transfer),
        user=actor,
        request=request,
    )
    return transfer


@transaction.atomic
def mark_discharge_request(
    *, admission: Admission, reason: str, actor=None, request=None
) -> Admission:
    """A doctor issues the discharge order for an admitted patient."""
    if (
        not admission.is_active_admission
        or admission.status != AdmissionStatus.ADMITTED
    ):
        raise ValueError(_("Only admitted patients can be ordered for discharge."))
    before = model_to_dict_safe(admission)
    admission.status = AdmissionStatus.DISCHARGE_REQUESTED
    admission.discharge_reason = reason
    admission.save(update_fields=["status", "discharge_reason", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=admission,
        changes={"before": before, "after": model_to_dict_safe(admission)},
        user=actor,
        request=request,
    )
    return admission


@transaction.atomic
def set_clearance(
    *,
    admission: Admission,
    department: str,
    cleared: bool,
    notes: str = "",
    actor=None,
    request=None,
) -> DischargeClearance:
    """Record a departmental no-dues clearance for a discharge."""
    clearance, created = DischargeClearance.objects.update_or_create(
        admission=admission,
        department=department,
        defaults={
            "is_cleared": cleared,
            "cleared_by": actor if cleared and getattr(actor, "pk", None) else None,
            "cleared_at": timezone.now() if cleared else None,
            "notes": notes,
        },
    )
    log_action(
        AuditAction.CREATE if created else AuditAction.UPDATE,
        instance=clearance,
        changes=model_to_dict_safe(clearance),
        user=actor,
        request=request,
    )
    return clearance


@transaction.atomic
def discharge(
    *,
    admission: Admission,
    summary_data: dict,
    actor=None,
    request=None,
) -> DischargeSummary:
    """Discharge a patient after all required clearances are obtained.

    Blocks (raises) whenever Lab, Pharmacy or Billing clearances are pending
    (RULES Phase 7 exit criterion).
    """
    from .models import BedStatus, DischargeType

    pending = admission.pending_clearance_departments
    if pending:
        raise ValueError(
            _("Discharge blocked — pending clearances: %(deps)s.")
            % {"deps": ", ".join(sorted(pending))}
        )
    if admission.status not in {
        AdmissionStatus.ADMITTED,
        AdmissionStatus.DISCHARGE_REQUESTED,
    }:
        raise ValueError(_("The admission is not in a dischargeable state."))

    now = timezone.now()
    summary = DischargeSummary.objects.create(
        admission=admission,
        discharged_at=now,
        discharge_type=summary_data.get("discharge_type", DischargeType.ROUTINE),
        diagnosis_summary=summary_data.get("diagnosis_summary", ""),
        treatment_given=summary_data.get("treatment_given", ""),
        follow_up=summary_data.get("follow_up", ""),
        discharge_advice=summary_data.get("discharge_advice", ""),
        generated_by=actor if getattr(actor, "pk", None) else None,
    )

    bed_id = admission.bed_id
    admission.status = AdmissionStatus.DISCHARGED
    admission.discharged_at = now
    admission.save()
    if bed_id:
        Bed.objects.filter(pk=bed_id).update(status=BedStatus.AVAILABLE, updated_at=now)

    log_action(
        AuditAction.CREATE,
        instance=summary,
        changes=model_to_dict_safe(summary),
        user=actor,
        request=request,
    )
    return summary


@transaction.atomic
def accrue_daily_charges(*, charge_date: date | None = None, admission=None):
    """Accrue one day of bed + nursing + doctor-visit charges (idempotent).

    ``charge_date`` defaults to today; every *admitted* admission without a
    charge row for that date gets one. Rates come from ``settings.IHMS``.
    """
    charge_date = charge_date or timezone.localdate()
    qs = Admission.objects.filter(
        status__in=[AdmissionStatus.ADMITTED, AdmissionStatus.DISCHARGE_REQUESTED],
        admitted_at__date__lte=charge_date,
    )
    if admission is not None:
        qs = qs.filter(pk=admission.pk)
    if not qs.exists():
        return 0

    existing = set(
        DailyCharge.objects.filter(charge_date=charge_date).values_list(
            "admission_id", flat=True
        )
    )
    nursing_rate = Decimal(settings.IHMS.get("IP_DAILY_NURSING_RATE", 300))
    doctor_rate = Decimal(settings.IHMS.get("IP_DAILY_DOCTOR_VISIT_RATE", 500))

    count = 0
    for adm in qs:
        if adm.bed_id is None or adm.pk in existing:
            continue
        DailyCharge.objects.create(
            admission=adm,
            charge_date=charge_date,
            bed_charge=adm.bed.daily_rate,
            nursing_charge=nursing_rate,
            doctor_visit_charge=doctor_rate,
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Nursing documentation
# ---------------------------------------------------------------------------
@transaction.atomic
def record_nursing_note(
    *, admission: Admission, note: str, shift: str, actor=None, request=None
) -> NursingNote:
    from .models import NursingShift

    entry = NursingNote.objects.create(
        admission=admission,
        note=note,
        shift=shift or NursingShift.DAY,
        nurse=actor if getattr(actor, "pk", None) else None,
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
def record_mar(
    *,
    admission: Admission,
    drug,
    dose: str,
    route: str,
    scheduled_for,
    action: str = MarAction.GIVEN,
    prescription_item=None,
    notes: str = "",
    actor=None,
    request=None,
) -> MedicationAdministration:
    entry = MedicationAdministration.objects.create(
        admission=admission,
        prescription_item=prescription_item,
        drug=drug,
        dose=dose,
        route=route,
        scheduled_for=scheduled_for,
        action=action,
        notes=notes,
        given_by=actor if getattr(actor, "pk", None) else None,
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
def record_intake_output(
    *,
    admission: Admission,
    fluid_type: str,
    category: str,
    volume_ml: int,
    shift: str,
    actor=None,
    request=None,
) -> IntakeOutput:
    from .models import NursingShift

    entry = IntakeOutput.objects.create(
        admission=admission,
        fluid_type=fluid_type,
        category=category,
        volume_ml=volume_ml,
        shift=shift or NursingShift.DAY,
        recorded_by=actor if getattr(actor, "pk", None) else None,
    )
    log_action(
        AuditAction.CREATE,
        instance=entry,
        changes=model_to_dict_safe(entry),
        user=actor,
        request=request,
    )
    return entry
