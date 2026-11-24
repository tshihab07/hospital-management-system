"""Model-level tests for the ICU / Emergency module."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.icu.models import EmergencyCase, TriageLevel

from .factories import make_admission, make_emergency_case, make_icu_record

pytestmark = pytest.mark.django_db


def test_icu_record_map_and_fluid_balance():
    record = make_icu_record(
        bp_systolic=120, bp_diastolic=80, intake_ml=500, output_ml=300
    )
    assert record.bp_display == "120/80"
    assert record.map_estimate == 93  # (120 + 160) / 3
    assert record.fluid_balance == 200
    assert record.is_ventilated is False


def test_critical_findings_detected():
    record = make_icu_record(
        spo2=85, pulse=150, bp_systolic=70, temperature=Decimal("34.0")
    )
    params = {f["parameter"] for f in record.critical_findings}
    assert {"spo2", "pulse", "bp_systolic", "temperature"} <= params


def test_normal_record_has_no_findings():
    record = make_icu_record()
    assert record.critical_findings == []


def test_emergency_case_triage_rank_and_wait():
    case = make_emergency_case(triage_level=TriageLevel.RED)
    assert case.triage_rank == 0
    assert case.is_open is True
    assert case.wait_minutes >= 0
    assert EmergencyCase.TRIAGE_RANK[TriageLevel.BLUE] == 4


def test_er_number_is_unique_and_formatted():
    first = make_emergency_case()
    second = make_emergency_case()
    assert first.case_no != second.case_no
    assert first.case_no.startswith("ER-")
    assert len(first.case_no.split("-")[-1]) == 5


def test_icu_record_links_to_admission():
    admission = make_admission()
    record = make_icu_record(admission=admission)
    assert record.admission_id == admission.pk
    assert admission.icu_records.count() == 1
