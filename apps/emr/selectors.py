"""Read-only queries for the EMR & CPOE module.

Keeps view code thin (RULES §2.2): every non-trivial queryset lives here.
"""

from __future__ import annotations

from django.db.models import Count, Prefetch, Q
from django.utils import timezone

from .models import (Allergy, ClinicalAttachment, Encounter, EncounterStatus,
                     LabOrder, LabOrderItem, Prescription, PrescriptionItem,
                     ProblemListEntry, ProcedureOrder, RadiologyOrder,
                     RadiologyOrderItem, Vital)


def _as_datetime(date_value):
    """Return an aware datetime for a date, or ``None`` when unset."""
    if date_value is None:
        return None
    naive = timezone.datetime.combine(date_value, timezone.datetime.min.time())
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


def encounter_list(
    *,
    doctor=None,
    patient=None,
    status: str = "",
    search: str = "",
    enc_date=None,
    encounter_type: str = "",
):
    """Filtered encounter queryset for the encounter worklist."""
    qs = Encounter.objects.select_related("patient", "doctor", "appointment")
    if doctor is not None:
        qs = qs.filter(doctor=doctor)
    if patient is not None:
        qs = qs.filter(patient=patient)
    if status:
        qs = qs.filter(status=status)
    if encounter_type:
        qs = qs.filter(encounter_type=encounter_type)
    if enc_date:
        qs = qs.filter(encounter_date=enc_date)
    if search:
        qs = qs.filter(
            Q(patient__full_name_en__icontains=search)
            | Q(patient__uhid__icontains=search)
            | Q(patient__phone__icontains=search)
            | Q(chief_complaint__icontains=search)
        )
    return qs


def patient_encounters(patient):
    """All encounters for a patient, newest first."""
    return (
        Encounter.objects.filter(patient=patient)
        .select_related("doctor", "appointment")
        .order_by("-encounter_date", "-id")
    )


def active_problems(patient):
    """Active entries on a patient's problem list."""
    return ProblemListEntry.objects.filter(
        patient=patient, is_active=True
    ).select_related("diagnosis")


def patient_allergies(patient):
    """Active entries in a patient's allergy register."""
    return Allergy.objects.filter(patient=patient, is_active=True)


def latest_vitals(patient, *, limit: int = 6):
    """Most recent vitals rows for a patient."""
    return Vital.objects.filter(patient=patient).select_related("recorded_by")[:limit]


def encounter_orders(encounter):
    """Return all CPOE orders for an encounter, grouped by kind."""
    return {
        "prescriptions": encounter.prescriptions.prefetch_related(
            Prefetch("items", queryset=PrescriptionItem.objects.select_related("drug"))
        ),
        "lab_orders": encounter.lab_orders.prefetch_related(
            Prefetch("items", queryset=LabOrderItem.objects.select_related("test"))
        ),
        "radiology_orders": encounter.radiology_orders.prefetch_related(
            Prefetch(
                "items", queryset=RadiologyOrderItem.objects.select_related("test")
            )
        ),
        "procedure_orders": encounter.procedure_orders.select_related("procedure"),
    }


def prescription_list(*, patient=None, doctor=None, search: str = ""):
    """Filtered prescription queryset for the prescriptions worklist."""
    qs = Prescription.objects.select_related("patient", "doctor", "encounter")
    if patient is not None:
        qs = qs.filter(patient=patient)
    if doctor is not None:
        qs = qs.filter(doctor=doctor)
    if search:
        qs = qs.filter(
            Q(patient__full_name_en__icontains=search)
            | Q(patient__uhid__icontains=search)
        )
    return qs


def attachments_for(patient):
    """Clinical attachments for a patient, newest first."""
    return ClinicalAttachment.objects.filter(patient=patient).select_related(
        "uploaded_by", "encounter"
    )


def patient_timeline(patient, *, limit: int = 200):
    """Build a unified, reverse-chronological EMR timeline for a patient.

    Merges encounters, diagnoses, vitals, prescriptions, lab/radiology/
    procedure orders and attachments into a single list of event dicts.
    """
    events: list[dict] = []

    def add(
        at, kind, icon, title, detail="", url_name="", url_pk=None, variant="neutral"
    ):
        events.append(
            {
                "at": at,
                "kind": kind,
                "icon": icon,
                "title": title,
                "detail": detail,
                "url_name": url_name,
                "url_pk": url_pk,
                "variant": variant,
            }
        )

    for enc in patient_encounters(patient):
        add(
            _as_datetime(enc.encounter_date),
            "encounter",
            "stethoscope",
            f"{enc.get_encounter_type_display()} — {enc.doctor.name_en}",
            enc.chief_complaint or "",
            "emr:encounter_detail",
            enc.pk,
            "info",
        )

    for rx in Prescription.objects.filter(patient=patient).select_related("doctor"):
        add(
            rx.issued_at,
            "prescription",
            "pill",
            f"Prescription · {rx.items.count()} drug(s) — {rx.doctor.name_en}",
            rx.notes or "",
            "emr:prescription_detail",
            rx.pk,
            "success",
        )

    for order in LabOrder.objects.filter(patient=patient):
        add(
            order.ordered_at,
            "lab_order",
            "flask-conical",
            f"Lab order · {order.get_status_display()}",
            ", ".join(str(i.test) for i in order.items.all()),
            "emr:encounter_detail",
            order.encounter_id,
            "warning",
        )

    for order in RadiologyOrder.objects.filter(patient=patient):
        add(
            order.ordered_at,
            "radiology_order",
            "scan",
            f"Radiology order · {order.get_status_display()}",
            ", ".join(str(i.test) for i in order.items.all()),
            "emr:encounter_detail",
            order.encounter_id,
            "warning",
        )

    for order in ProcedureOrder.objects.filter(patient=patient).select_related(
        "procedure"
    ):
        add(
            order.ordered_at,
            "procedure_order",
            "scissors",
            f"Procedure order · {order.procedure.name}",
            order.get_status_display(),
            "emr:encounter_detail",
            order.encounter_id,
            "warning",
        )

    for vit in Vital.objects.filter(patient=patient).select_related("recorded_by"):
        add(
            vit.recorded_at,
            "vitals",
            "activity",
            f"Vitals · BP {vit.bp_display}",
            (
                f"T {vit.temperature_c or '—'}°C · P {vit.pulse or '—'} · "
                f"SpO₂ {vit.spo2 or '—'}%"
            ),
        )

    for att in ClinicalAttachment.objects.filter(patient=patient):
        add(
            att.created_at,
            "attachment",
            "paperclip",
            f"Attachment · {att.title}",
            att.get_category_display(),
            "emr:attachment_list",
            att.patient_id,
        )

    for allergy in Allergy.objects.filter(patient=patient):
        add(
            _as_datetime(allergy.noted_on) or allergy.created_at,
            "allergy",
            "alert-triangle",
            f"Allergy noted · {allergy.allergen}",
            f"{allergy.get_allergy_type_display()} · {allergy.get_severity_display()}",
            "emr:allergy_list",
            allergy.patient_id,
            "danger",
        )

    events.sort(key=lambda e: e["at"] or timezone.now(), reverse=True)
    return events[:limit]


def encounter_summary(doctor=None, *, enc_date=None):
    """Small KPI summary for the encounter worklist header."""
    if enc_date is None:
        enc_date = timezone.localdate()
    qs = Encounter.objects.filter(encounter_date=enc_date)
    if doctor is not None:
        qs = qs.filter(doctor=doctor)
    return qs.aggregate(
        total=Count("id"),
        open=Count("id", filter=Q(status=EncounterStatus.OPEN)),
        closed=Count("id", filter=Q(status=EncounterStatus.CLOSED)),
    )
