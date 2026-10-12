"""Model-level tests for the IPD module."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.ipd.models import (AdmissionStatus, BedStatus, ClearanceDepartment,
                             DailyCharge, DischargeClearance)

from .factories import (allocate, make_admission, make_bed, make_patient,
                        make_ward)

pytestmark = pytest.mark.django_db


def test_ward_bed_number_unique():
    ward = make_ward()
    make_bed(ward, bed_no="01")
    with pytest.raises(IntegrityError):
        make_bed(ward, bed_no="01")


def test_is_active_admission():
    admit = allocate(make_admission(), make_bed())
    assert admit.is_active_admission is True
    assert admit.status == AdmissionStatus.ADMITTED
    assert admit.bed.is_occupied is True
    assert BedStatus.OCCUPIED == admit.bed.status


def test_length_of_stay_days_counts_admission_day():
    admit = allocate(make_admission(), make_bed())
    assert admit.length_of_stay_days >= 1


def test_pending_clearance_departments_by_default():
    admit = allocate(make_admission(), make_bed())
    pending = admit.pending_clearance_departments
    assert ClearanceDepartment.LAB in pending
    assert ClearanceDepartment.PHARMACY in pending
    assert ClearanceDepartment.BILLING in pending
    assert admit.has_pending_clearances is True


def test_required_clearances_clear():
    admit = allocate(make_admission(), make_bed())
    for dep in (
        ClearanceDepartment.LAB,
        ClearanceDepartment.PHARMACY,
        ClearanceDepartment.BILLING,
    ):
        DischargeClearance.objects.create(
            admission=admit, department=dep, is_cleared=True
        )
    assert admit.has_pending_clearances is False
    assert admit.pending_clearance_departments == set()


def test_daily_charge_total_property():
    admit = allocate(make_admission(), make_bed(daily_rate="1000"))
    charge = DailyCharge.objects.create(
        admission=admit,
        charge_date="2026-01-01",
        bed_charge="1000",
        nursing_charge="300",
        doctor_visit_charge="500",
    )
    assert charge.total == 1800


def test_uniq_bed_active_admission_blocks_release():
    bed = make_bed()
    allocate(make_admission(), bed)
    other = make_admission()
    other.ip_number = "IP-2026-99999"
    with pytest.raises(IntegrityError):
        other.__class__.objects.create(
            patient=make_patient(),
            doctor=other.doctor,
            bed=bed,
            status=AdmissionStatus.ADMITTED,
        )
