"""Read-only queries for the IPD module (RULES §2.2 — keep views thin)."""

from __future__ import annotations

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (Admission, AdmissionStatus, Bed, BedStatus, DailyCharge,
                     Ward)


def admission_list(*, status: str = "", search: str = "", ward=None, patient=None):
    """Filtered admission queryset for the IPD worklist."""
    qs = Admission.objects.select_related("patient", "doctor", "bed__ward")
    if status:
        qs = qs.filter(status=status)
    if ward is not None:
        qs = qs.filter(bed__ward=ward)
    if patient is not None:
        qs = qs.filter(patient=patient)
    if search:
        qs = qs.filter(
            Q(patient__full_name_en__icontains=search)
            | Q(patient__uhid__icontains=search)
            | Q(ip_number__icontains=search)
        )
    return qs


def patient_admissions(patient):
    """All admissions for a patient, newest first."""
    return Admission.objects.filter(patient=patient).select_related(
        "doctor", "bed__ward"
    )


def ward_bed_map(*, ward_type: str = ""):
    """Active wards with their beds (and occupants) for the bed map.

    Returns a list of ward dicts; each ``beds`` entry carries the display
    attributes the template needs (CSS class, status dot, occupant name).
    """
    wards = Ward.objects.filter(is_active=True)
    if ward_type:
        wards = wards.filter(ward_type=ward_type)
    wards = wards.prefetch_related("beds").order_by("name")

    occupied_beds = {
        a.bed_id: a.patient.display_name
        for a in Admission.objects.filter(
            status__in=[
                AdmissionStatus.ADMITTED,
                AdmissionStatus.DISCHARGE_REQUESTED,
            ],
            bed__isnull=False,
        ).select_related("patient")
    }

    result = []
    for ward in wards:
        beds = []
        for bed in ward.beds.all():
            occupied = bed.status == BedStatus.OCCUPIED and bed.id in occupied_beds
            beds.append(
                {
                    "id": bed.pk,
                    "bed_no": bed.bed_no,
                    "status": bed.status,
                    "status_display": bed.get_status_display(),
                    "daily_rate": bed.daily_rate,
                    "occupied": occupied,
                    "current_patient": occupied_beds.get(bed.id, ""),
                    "css": (
                        "border-red-200 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10"
                        if occupied
                        else "border-slate-100 dark:border-slate-800"
                    ),
                    "dot": (
                        "bg-red-500"
                        if occupied
                        else (
                            "bg-emerald-500"
                            if bed.status == BedStatus.AVAILABLE
                            else "bg-amber-400"
                        )
                    ),
                }
            )
        result.append(
            {
                "id": ward.pk,
                "name": ward.name,
                "ward_type": ward.ward_type,
                "ward_type_display": ward.get_ward_type_display(),
                "floor": ward.floor,
                "free_beds": sum(
                    not b["occupied"] and b["status"] == BedStatus.AVAILABLE
                    for b in beds
                ),
                "beds": beds,
            }
        )
    return result


def bed_kpis():
    """Bed capacity KPIs derived from physical bed status."""
    return {
        "occupied": Bed.objects.filter(status=BedStatus.OCCUPIED).count(),
        "available": Bed.objects.filter(status=BedStatus.AVAILABLE).count(),
        "maintenance": Bed.objects.filter(status=BedStatus.MAINTENANCE).count(),
        "beds_total": Bed.objects.count(),
    }


def bed_status_counts():
    """Bed capacity KPIs grouped by physical status."""
    return {
        row["status"]: row["count"]
        for row in Bed.objects.values("status").annotate(count=Count("id"))
    }


def occupancy_kpis():
    """Today's IPD occupancy figures for the dashboard header."""
    today = timezone.localdate()
    qs = Admission.objects.filter(
        status__in=[
            AdmissionStatus.ADMITTED,
            AdmissionStatus.DISCHARGE_REQUESTED,
        ]
    )
    return {
        "inpatients": qs.count(),
        "admitted_today": qs.filter(admitted_at__date=today).count(),
        "beds_total": Bed.objects.count(),
        "beds_available": Bed.objects.filter(status=BedStatus.AVAILABLE).count(),
    }


def charge_summary(admission):
    """Aggregated accrued charges for an admission."""
    return DailyCharge.objects.filter(admission=admission).aggregate(
        bed=Sum("bed_charge"),
        nursing=Sum("nursing_charge"),
        doctor_visit=Sum("doctor_visit_charge"),
        nights=Count("id"),
    )


def recent_transfers(admission, *, limit: int = 8):
    """Most recent bed/ward transfers for an admission."""
    return admission.bed_transfers.select_related("from_bed", "to_bed")[:limit]
