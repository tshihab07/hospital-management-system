"""Service-level tests for the ICU / Emergency module."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.icu import services
from apps.icu.models import (AlertStatus, CodeBlueStatus, CriticalAlert,
                             CriticalScore, EmergencyStatus, ScoreType)

from .factories import make_admission, make_doctor, make_emergency_case

pytestmark = pytest.mark.django_db

_LOCMEM = override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
)


@_LOCMEM
def test_create_icu_record_raises_critical_alert_and_notifies():
    admission = make_admission()
    services.create_icu_record(admission=admission, data={"spo2": 80, "pulse": 80})
    alert = CriticalAlert.objects.get(admission=admission)
    assert alert.parameter == "spo2"
    assert alert.status == AlertStatus.ACTIVE
    assert alert.severity == "high"
    assert alert.notified_to  # doctor/duty recipients recorded


@_LOCMEM
def test_normal_chart_creates_no_alert():
    admission = make_admission()
    services.create_icu_record(
        admission=admission, data={"spo2": 98, "pulse": 80, "bp_systolic": 120}
    )
    assert CriticalAlert.objects.filter(admission=admission).count() == 0


def test_acknowledge_and_resolve_alert():
    admission = make_admission()
    services.create_icu_record(admission=admission, data={"spo2": 80})
    alert = CriticalAlert.objects.get(admission=admission)
    services.acknowledge_alert(alert=alert)
    alert.refresh_from_db()
    assert alert.status == AlertStatus.ACKNOWLEDGED
    assert alert.acknowledged_at is not None
    services.resolve_alert(alert=alert)
    alert.refresh_from_db()
    assert alert.status == AlertStatus.RESOLVED


def test_apache_ii_calculation():
    score, breakdown = services.calculate_apache_ii(
        {
            "temperature": 36.5,
            "map": 90,
            "heart_rate": 80,
            "respiratory_rate": 16,
            "pao2": 90,
            "ph": 7.4,
            "sodium": 140,
            "potassium": 4.0,
            "creatinine": 1.0,
            "hematocrit": 40,
            "wbc": 8.0,
            "gcs": 15,
            "age": 40,
        }
    )
    assert score == 0
    assert breakdown["gcs"] == 0


def test_apache_ii_scores_abnormal_values():
    score, _ = services.calculate_apache_ii(
        {"gcs": 5, "age": 80, "creatinine": 4.0, "chronic_points": 5}
    )
    # gcs 10 + age 6 + creatinine 4 + chronic 5
    assert score == 25


def test_sofa_calculation():
    score, breakdown = services.calculate_sofa(
        {
            "pao2_fio2": 250,
            "platelets": 90,
            "bilirubin": 3.0,
            "map": 60,
            "gcs": 11,
            "creatinine": 3.6,
        }
    )
    assert breakdown["respiration"] == 2
    assert breakdown["coagulation"] == 2
    assert breakdown["liver"] == 2
    assert breakdown["cardiovascular"] == 1
    assert breakdown["cns"] == 2
    assert breakdown["renal"] == 3
    assert score == 12


def test_record_score_persists():
    admission = make_admission()
    score = services.record_score(
        admission=admission, score_type=ScoreType.SOFA, data={"gcs": 15}
    )
    assert isinstance(score, CriticalScore)
    assert score.score_value == 0
    assert score.breakdown == {"cns": 0}


def test_open_emergency_case_defaults():
    case = make_emergency_case()
    assert case.status == EmergencyStatus.WAITING
    assert case.case_no
    assert case.triage_level == "yellow"


def test_quick_register_creates_patient_and_case():
    case = services.quick_register_and_open_case(
        patient_data={
            "full_name_en": "Unknown Male 1",
            "phone": "01700000000",
            "gender": "male",
            "age_years": 30,
        },
        complaint="Road traffic accident",
        triage_level="red",
    )
    assert case.patient.uhid
    assert case.triage_level == "red"
    assert case.patient.full_name_en == "Unknown Male 1"


def test_triage_and_status_transitions():
    case = make_emergency_case()
    services.set_triage(case=case, triage_level="red")
    case.refresh_from_db()
    assert case.triage_level == "red"
    services.set_emergency_status(case=case, status=EmergencyStatus.IN_TREATMENT)
    case.refresh_from_db()
    assert case.status == EmergencyStatus.IN_TREATMENT
    assert case.is_open


def test_convert_to_admission_links_admission():
    case = make_emergency_case()
    doctor = make_doctor()
    services.convert_to_admission(case=case, doctor=doctor, reason="Needs surgery")
    case.refresh_from_db()
    assert case.status == EmergencyStatus.ADMITTED
    assert case.converted_admission is not None
    assert case.converted_admission.patient_id == case.patient_id


def test_quick_discharge_sets_discharged():
    case = make_emergency_case()
    services.quick_discharge(case=case)
    case.refresh_from_db()
    assert case.status == EmergencyStatus.DISCHARGED
    assert case.discharged_at is not None
    assert case.is_open is False


@_LOCMEM
def test_code_blue_raise_and_resolve():
    alert = services.raise_code_blue(location="ICU Bed 01")
    assert alert.status == CodeBlueStatus.ACTIVE
    assert alert.notified_count >= 0
    services.resolve_code_blue(alert=alert, notes="ROSC achieved")
    alert.refresh_from_db()
    assert alert.status == CodeBlueStatus.RESOLVED
    assert alert.resolved_at is not None


def test_handover_note_lifecycle():
    note = services.record_handover(
        unit="icu", shift="day", summary="Stable overnight", pending_tasks="Repeat ABG"
    )
    assert note.acknowledged is False
    services.acknowledge_handover(note=note)
    note.refresh_from_db()
    assert note.acknowledged is True
