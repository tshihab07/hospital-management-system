"""Service-layer tests for the EMR module (encounters, CPOE, interactions)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.emr import services
from apps.emr.models import (Allergy, ClinicalAttachment, DrugInteractionRule,
                             Encounter, EncounterType, InteractionSeverity,
                             LabOrder, OrderStatus, Prescription,
                             PrescriptionItem, ProcedureOrder, RadiologyOrder,
                             Route, SoapNote, VisitDiagnosis, Vital)
from apps.masters.models import (Diagnosis, Drug, LabTest, Procedure,
                                 RadiologyTest)
from apps.opd.models import Appointment, Doctor

from .factories import make_doctor, make_encounter, make_patient

pytestmark = pytest.mark.django_db


def _drug(name="Paracetamol") -> Drug:
    return Drug.objects.create(generic_name=name)


def _appointment() -> Appointment:
    return Appointment.objects.create(
        patient=make_patient(),
        doctor=make_doctor(),
        appt_date=dt.date(2026, 6, 1),
        token_no=1,
    )


def test_open_encounter_is_idempotent_per_appointment():
    appointment = _appointment()
    enc, created = services.open_encounter(
        patient=appointment.patient, doctor=appointment.doctor, appointment=appointment
    )
    assert created is True
    assert enc.encounter_type == EncounterType.OUTPATIENT
    again, created2 = services.open_encounter(
        patient=appointment.patient, doctor=appointment.doctor, appointment=appointment
    )
    assert created2 is False
    assert again.pk == enc.pk
    assert Encounter.objects.count() == 1


def test_close_encounter_is_idempotent():
    enc = make_encounter()
    closed = services.close_encounter(instance=enc)
    assert closed.status == "closed"
    assert closed.closed_at is not None
    again = services.close_encounter(instance=closed)
    assert again.closed_at == closed.closed_at


def test_save_soap_note_creates_then_updates():
    enc = make_encounter()
    note = services.save_soap_note(encounter=enc, subjective="S1", plan="P1")
    assert SoapNote.objects.count() == 1
    note2 = services.save_soap_note(encounter=enc, subjective="S2", plan="P2")
    assert note2.pk == note.pk
    assert SoapNote.objects.get(encounter=enc).subjective == "S2"


def test_record_vitals_sets_patient_from_encounter():
    enc = make_encounter()
    vital = services.record_vitals(
        encounter=enc, data={"pulse": 80, "bp_systolic": 120, "bp_diastolic": 80}
    )
    assert vital.patient_id == enc.patient_id
    assert Vital.objects.filter(patient=enc.patient).count() == 1


def test_add_visit_diagnosis_enforces_single_primary():
    enc = make_encounter()
    dx = Diagnosis.objects.create(code="I10", name="Hypertension")
    first = services.add_visit_diagnosis(encounter=enc, diagnosis=dx, is_primary=True)
    second = services.add_visit_diagnosis(
        encounter=enc, description="Headache", is_primary=True
    )
    first.refresh_from_db()
    assert first.is_primary is False
    assert second.is_primary is True
    assert VisitDiagnosis.objects.filter(encounter=enc).count() == 2


def test_problem_list_add_and_resolve():
    patient = make_patient()
    problem = services.add_problem(patient=patient, description="Asthma")
    assert problem.is_active is True
    resolved = services.resolve_problem(instance=problem)
    assert resolved.is_active is False
    assert resolved.resolved_date is not None


def test_add_allergy():
    patient = make_patient()
    allergy = services.add_allergy(
        patient=patient, allergen="Penicillin", reaction="Rash"
    )
    assert allergy.allergy_type == "drug"
    assert Allergy.objects.filter(patient=patient).count() == 1


def test_check_drug_interactions_needs_two_drugs():
    a, b = _drug("Warfarin"), _drug("Aspirin")
    DrugInteractionRule.objects.create(
        drug_a=a, drug_b=b, severity=InteractionSeverity.MAJOR
    )
    assert services.check_drug_interactions([a.pk]) == []
    found = services.check_drug_interactions([a.pk, b.pk])
    assert len(found) == 1
    assert found[0].severity == InteractionSeverity.MAJOR


def test_issue_prescription_creates_items_and_flags_interaction():
    enc = make_encounter()
    a, b, c = _drug("Warfarin"), _drug("Aspirin"), _drug("Paracetamol")
    DrugInteractionRule.objects.create(
        drug_a=a, drug_b=b, severity=InteractionSeverity.MAJOR
    )
    rx, interactions = services.issue_prescription(
        encounter=enc,
        items=[
            {"drug": a, "dose": "5 mg", "frequency": "1+0+0", "route": Route.ORAL},
            {"drug": b, "dose": "75 mg", "frequency": "0+1+0", "route": Route.ORAL},
            {"drug": c, "dose": "500 mg", "frequency": "1+1+1", "route": Route.ORAL},
        ],
    )
    assert rx.patient_id == enc.patient_id
    assert PrescriptionItem.objects.filter(prescription=rx).count() == 3
    assert len(interactions) == 1


def test_issue_prescription_requires_items():
    enc = make_encounter()
    with pytest.raises(ValueError):
        services.issue_prescription(encounter=enc, items=[])


def test_create_lab_and_radiology_and_procedure_orders():
    enc = make_encounter()
    lab = services.create_lab_order(
        encounter=enc, tests=[LabTest.objects.create(code="CBC", name="CBC")]
    )
    rad = services.create_radiology_order(
        encounter=enc, tests=[RadiologyTest.objects.create(code="XR", name="X-Ray")]
    )
    proc = services.create_procedure_order(
        encounter=enc, procedure=Procedure.objects.create(code="PR", name="Dressing")
    )
    assert LabOrder.objects.count() == 1
    assert RadiologyOrder.objects.count() == 1
    assert ProcedureOrder.objects.count() == 1
    assert lab.items.count() == 1 and rad.items.count() == 1
    assert proc.procedure_id == proc.procedure_id


def test_set_order_status():
    enc = make_encounter()
    order = services.create_lab_order(
        encounter=enc, tests=[LabTest.objects.create(code="CBC2", name="CBC")]
    )
    services.set_order_status(instance=order, status=OrderStatus.COMPLETED)
    order.refresh_from_db()
    assert order.status == OrderStatus.COMPLETED
    with pytest.raises(ValueError):
        services.set_order_status(instance=order, status="bogus")


def test_add_and_remove_attachment(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    patient = make_patient()
    upload = SimpleUploadedFile("report.txt", b"hello", content_type="text/plain")
    attachment = services.add_attachment(
        patient=patient, file=upload, title="External report"
    )
    assert ClinicalAttachment.objects.filter(patient=patient).count() == 1
    services.remove_attachment(instance=attachment)
    assert ClinicalAttachment.objects.filter(patient=patient).count() == 0
    assert ClinicalAttachment.all_objects.filter(patient=patient).count() == 1


def test_cancel_prescription():
    enc = make_encounter()
    drug = _drug("Omeprazole")
    rx, _ = services.issue_prescription(
        encounter=enc,
        items=[{"drug": drug, "dose": "20 mg", "frequency": "1+0+0"}],
    )
    assert rx.status == "issued"
    services.cancel_prescription(instance=rx)
    rx.refresh_from_db()
    assert rx.status == "cancelled"
    assert Prescription.objects.count() == 1


def test_doctor_signature_field_exists():
    doctor = Doctor.objects.get(pk=make_doctor().pk)
    assert doctor.signature.name in (None, "")
