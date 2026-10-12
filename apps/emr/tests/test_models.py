"""Model tests for the EMR module."""

from __future__ import annotations

import pytest

from apps.emr.models import (DrugInteractionRule, EncounterStatus,
                             InteractionSeverity, Vital)

from .factories import make_doctor, make_encounter, make_patient

pytestmark = pytest.mark.django_db


def test_encounter_str_and_is_open():
    patient = make_patient()
    encounter = make_encounter(patient=patient)
    assert encounter.is_open is True
    assert str(encounter) == f"{patient.pk}@{encounter.encounter_date}"


def test_close_sets_status_and_timestamp():
    encounter = make_encounter()
    encounter.status = EncounterStatus.CLOSED
    assert encounter.is_open is False


def test_vital_bmi_and_bp_display():
    vital = Vital(patient=make_patient(), height_cm="175.00", weight_kg="70.00")
    assert vital.bmi == 22.9
    vital.bp_systolic = 120
    vital.bp_diastolic = 80
    assert vital.bp_display == "120/80"


def test_vital_bmi_none_without_measurements():
    vital = Vital(patient=make_patient())
    assert vital.bmi is None
    assert vital.bp_display == "—"


def test_drug_interaction_rule_matches_and_clean():
    from apps.masters.models import Drug

    a = Drug.objects.create(generic_name="Warfarin")
    b = Drug.objects.create(generic_name="Aspirin")
    rule = DrugInteractionRule.objects.create(
        drug_a=a, drug_b=b, severity=InteractionSeverity.MAJOR
    )
    assert rule.matches({a.pk, b.pk}) is True
    assert rule.matches({a.pk}) is False
    assert "⨯" in str(rule)

    bad = DrugInteractionRule(drug_a=a, drug_b=a)
    with pytest.raises(Exception):
        bad.full_clean()


def test_doctor_display_name():
    doctor = make_doctor(name_en="Dr. Test", specialization="Cardiology")
    assert doctor.display_name == "Dr. Test, Cardiology"
