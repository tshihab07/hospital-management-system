"""Read-side queries for ICU / Emergency (no writes, no audit)."""

from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone

from .models import (AlertStatus, CodeBlueAlert, CodeBlueStatus, CriticalAlert,
                     CriticalScore, EmergencyCase, EmergencyStatus,
                     HandoverNote, IcuRecord)


# ---------------------------------------------------------------------------
# ICU charting
# ---------------------------------------------------------------------------
def icu_admissions(*, search: str = ""):
    """Admissions that currently have ICU charting or an ICU/CCU bed."""
    from apps.ipd.models import Admission, AdmissionStatus

    qs = (
        Admission.objects.filter(status=AdmissionStatus.ADMITTED)
        .select_related("patient", "doctor", "bed__ward")
        .annotate(chart_count=Count("icu_records"))
    )
    if search:
        qs = qs.filter(
            Q(patient__full_name_en__icontains=search)
            | Q(patient__uhid__icontains=search)
            | Q(ip_number__icontains=search)
        )
    return qs.order_by("-admitted_at")


def charts_for(admission, *, limit: int | None = None):
    qs = IcuRecord.objects.filter(admission=admission).select_related("charted_by")
    return qs[:limit] if limit else qs


def latest_record(admission):
    return charts_for(admission).first()


def icu_kpis() -> dict:
    today = timezone.localdate()
    active_alerts = CriticalAlert.objects.filter(status=AlertStatus.ACTIVE)
    return {
        "charts_today": IcuRecord.objects.filter(recorded_at__date=today).count(),
        "active_alerts": active_alerts.count(),
        "high_alerts": active_alerts.filter(severity="high").count(),
        "ventilated": IcuRecord.objects.exclude(ventilator_mode="")
        .filter(recorded_at__date=today)
        .values("admission")
        .distinct()
        .count(),
    }


def alerts(*, status: str = "", admission=None):
    qs = CriticalAlert.objects.select_related(
        "admission__patient", "admission__doctor", "icu_record"
    )
    if status:
        qs = qs.filter(status=status)
    if admission is not None:
        qs = qs.filter(admission=admission)
    return qs.order_by("-created_at")


def score_history(admission):
    return CriticalScore.objects.filter(admission=admission).order_by("-calculated_at")


# ---------------------------------------------------------------------------
# Emergency queue
# ---------------------------------------------------------------------------
def emergency_queue(*, status: str = "", triage: str = "", search: str = ""):
    """Open ER cases ordered by triage priority, then arrival (FIFO)."""
    from django.db.models import Case, IntegerField, Value, When

    qs = EmergencyCase.objects.select_related(
        "patient", "attending_doctor", "converted_admission"
    )
    if status:
        qs = qs.filter(status=status)
    else:
        qs = qs.exclude(
            status__in=[
                EmergencyStatus.DISCHARGED,
                EmergencyStatus.LEFT,
                EmergencyStatus.DECEASED,
            ]
        )
    if triage:
        qs = qs.filter(triage_level=triage)
    if search:
        qs = qs.filter(
            Q(patient__full_name_en__icontains=search)
            | Q(patient__uhid__icontains=search)
            | Q(case_no__icontains=search)
        )
    rank = Case(
        *(
            When(triage_level=level, then=Value(rank))
            for level, rank in EmergencyCase.TRIAGE_RANK.items()
        ),
        default=Value(9),
        output_field=IntegerField(),
    )
    return qs.annotate(triage_rank_order=rank).order_by(
        "triage_rank_order", "arrival_time"
    )


def emergency_kpis() -> dict:
    open_cases = EmergencyCase.objects.exclude(
        status__in=[
            EmergencyStatus.DISCHARGED,
            EmergencyStatus.LEFT,
            EmergencyStatus.DECEASED,
        ]
    )
    today = timezone.localdate()
    waiting = open_cases.filter(status=EmergencyStatus.WAITING)
    oldest = waiting.order_by("arrival_time").first()
    return {
        "open_cases": open_cases.count(),
        "waiting": waiting.count(),
        "red": open_cases.filter(triage_level="red").count(),
        "arrivals_today": EmergencyCase.objects.filter(
            arrival_time__date=today
        ).count(),
        "longest_wait": oldest.wait_minutes if oldest else 0,
    }


# ---------------------------------------------------------------------------
# Code Blue / handover
# ---------------------------------------------------------------------------
def code_blues(*, status: str = ""):
    qs = CodeBlueAlert.objects.select_related(
        "admission__patient", "emergency_case__patient", "called_by"
    )
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-called_at")


def active_code_blue_count() -> int:
    return CodeBlueAlert.objects.filter(status=CodeBlueStatus.ACTIVE).count()


def handover_notes(*, unit: str = "", shift: str = ""):
    qs = HandoverNote.objects.select_related(
        "handed_over_by", "handover_to", "admission__patient", "emergency_case__patient"
    )
    if unit:
        qs = qs.filter(unit=unit)
    if shift:
        qs = qs.filter(shift=shift)
    return qs.order_by("-handover_date", "-created_at")
