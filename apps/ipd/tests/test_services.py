"""Service-layer tests for the IPD module (admission, bed, discharge)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.ipd import services
from apps.ipd.models import (AdmissionStatus, BedStatus, ClearanceDepartment,
                             DischargeSummary, DischargeType, MarAction,
                             NursingShift, Route)

from .factories import (allocate, make_admission, make_bed, make_drug,
                        make_patient, make_ward)

pytestmark = pytest.mark.django_db


def _admitted():
    return allocate(make_admission(), make_bed())


def test_generate_ip_number_is_sequential_and_prefixed():
    first = services.generate_ip_number()
    second = services.generate_ip_number()
    year = timezone.localdate().year
    assert first == f"IP-{year}-00001"
    assert second == f"IP-{year}-00002"


def test_request_admission_mints_no_bed():
    admission = make_admission()
    assert admission.status == AdmissionStatus.REQUESTED
    assert admission.ip_number is None
    assert admission.bed_id is None


def test_duplicate_active_admission_raises():
    admission = make_admission(patient=make_patient())
    with pytest.raises(ValueError):
        services.request_admission(
            patient=admission.patient, doctor=admission.doctor, reason="Again"
        )


def test_allocate_bed_transition_and_occupancy():
    admission = _admitted()
    assert admission.ip_number.startswith("IP-")
    assert admission.admitted_at is not None
    assert admission.bed.status == BedStatus.OCCUPIED
    assert admission.bed not in [
        bed
        for bed in admission.bed.ward.beds.all()
        if bed.status == BedStatus.AVAILABLE
    ]


def test_allocate_rejects_occupied_bed():
    made = allocate(make_admission(), make_bed())
    second = make_admission(patient=make_patient())
    with pytest.raises(ValueError):
        allocate(second, made.bed)


def test_allocate_rejects_unknown_status():
    admission = make_admission(patient=make_patient())
    allocate(admission, make_bed())
    with pytest.raises(ValueError):
        allocate(admission, make_bed())


def test_transfer_bed_updates_ward_and_logs():
    ward_a = make_ward(name="Alpha")
    ward_b = make_ward(name="Beta")
    bed_a = make_bed(ward_a, bed_no="01")
    bed_b = make_bed(ward_b, bed_no="02")
    admission = allocate(make_admission(), bed_a)
    transfer = services.transfer_bed(
        admission=admission, to_bed=bed_b, reason="ICU escalation"
    )
    bed_a.refresh_from_db()
    bed_b.refresh_from_db()
    assert bed_a.status == BedStatus.AVAILABLE
    assert bed_b.status == BedStatus.OCCUPIED
    assert admission.bed_id == bed_b.pk
    assert transfer.from_ward == "Alpha"
    assert transfer.to_ward == "Beta"
    assert admission.current_ward == ward_b


def test_transfer_rejects_same_bed_and_inactive():
    bed = make_bed()
    admission = allocate(make_admission(), bed)
    with pytest.raises(ValueError):
        services.transfer_bed(admission=admission, to_bed=bed)
    fresh = make_admission(patient=make_patient())
    with pytest.raises(ValueError):
        services.transfer_bed(admission=fresh, to_bed=make_bed())


def test_mark_discharge_request():
    admission = _admitted()
    services.mark_discharge_request(admission=admission, reason="Improved")
    assert admission.status == AdmissionStatus.DISCHARGE_REQUESTED
    assert admission.discharge_reason == "Improved"


def test_set_clearance_creates_then_updates():
    admission = _admitted()
    first = services.set_clearance(
        admission=admission, department=ClearanceDepartment.LAB, cleared=True
    )
    second = services.set_clearance(
        admission=admission, department=ClearanceDepartment.LAB, cleared=False
    )
    assert second.pk == first.pk
    assert second.is_cleared is False


def test_discharge_blocked_by_pending_clearances():
    admission = _admitted()
    with pytest.raises(ValueError):
        services.discharge(
            admission=admission,
            summary_data={"diagnosis_summary": "Fever", "treatment_given": "Rx"},
        )
    assert admission.status == AdmissionStatus.ADMITTED


def test_discharge_succeeds_after_all_clearances():
    admission = _admitted()
    for dep in (
        ClearanceDepartment.LAB,
        ClearanceDepartment.PHARMACY,
        ClearanceDepartment.BILLING,
    ):
        services.set_clearance(admission=admission, department=dep, cleared=True)
    bed = admission.bed
    summary = services.discharge(
        admission=admission,
        summary_data={
            "discharge_type": DischargeType.ROUTINE,
            "diagnosis_summary": "Viral fever",
            "treatment_given": "Paracetamol",
            "follow_up": "Review in 3 days",
            "discharge_advice": "Fluids",
        },
    )
    assert summary is not None
    assert isinstance(summary, DischargeSummary)
    assert admission.status == AdmissionStatus.DISCHARGED
    assert admission.discharged_at is not None
    assert admission.is_active_admission is False
    bed.refresh_from_db()
    assert bed.status == BedStatus.AVAILABLE


def test_accrue_daily_charges_is_idempotent():
    admission = _admitted()
    count = services.accrue_daily_charges()
    assert count == 1
    again = services.accrue_daily_charges()
    assert again == 0
    row = admission.daily_charges.get()
    assert row.bed_charge == admission.bed.daily_rate
    assert row.nursing_charge == Decimal("300")
    assert row.doctor_visit_charge == Decimal("500")


@override_settings(
    IHMS={
        "IP_DAILY_NURSING_RATE": "450",
        "IP_DAILY_DOCTOR_VISIT_RATE": "700",
        "IP_NUMBER_WIDTH": 4,
    }
)
def test_configured_rates_and_ip_width_are_used():
    admission = _admitted()
    assert admission.ip_number.endswith("-0001")
    charge_date = timezone.localdate()
    services.accrue_daily_charges(charge_date=charge_date)
    row = admission.daily_charges.get()
    assert row.nursing_charge == Decimal("450")
    assert row.doctor_visit_charge == Decimal("700")


def test_record_nursing_note_stores_shift():
    entry = services.record_nursing_note(
        admission=_admitted(), note="Stable overnight", shift=NursingShift.NIGHT
    )
    assert entry.note == "Stable overnight"
    assert entry.shift == NursingShift.NIGHT


def test_record_mar_defaults_to_oral_given():
    drug = make_drug()
    entry = services.record_mar(
        admission=_admitted(),
        drug=drug,
        dose="500mg",
        route=Route.ORAL,
        scheduled_for=timezone.now(),
    )
    assert entry.action == MarAction.GIVEN
    assert entry.route == Route.ORAL


def test_record_intake_output():
    entry = services.record_intake_output(
        admission=_admitted(),
        fluid_type="intake",
        category="oral",
        volume_ml=250,
        shift=NursingShift.DAY,
    )
    assert entry.volume_ml == 250
    assert entry.shift == NursingShift.DAY
