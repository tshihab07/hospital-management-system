"""Service-layer tests: UHID generation, mutations and merge."""

from __future__ import annotations

import datetime as dt
import re

import pytest

from apps.patients import services
from apps.patients.models import Patient, PatientDocument
from core.audit import AuditAction, AuditLog

pytestmark = pytest.mark.django_db

UHID_RE = re.compile(r"^DHK-\d{4}-\d{6}$")


def _data(**overrides):
    data = {
        "full_name_en": "Test Patient",
        "date_of_birth": dt.date(1990, 1, 1),
        "gender": "male",
        "phone": "01700000000",
    }
    data.update(overrides)
    return data


def test_generate_uhid_forms_and_increments():
    first = services.generate_uhid(year=2026)
    second = services.generate_uhid(year=2026)
    assert UHID_RE.match(first)
    assert first.endswith("000001")
    assert second.endswith("000002")
    assert first != second


def test_register_assigns_uhid_and_audits():
    patient = services.register_patient(data=_data())
    assert UHID_RE.match(patient.uhid)
    assert patient.registered_by is None
    assert AuditLog.objects.filter(
        action=AuditAction.CREATE, object_id=str(patient.pk)
    ).exists()


def test_update_patient_records_diff():
    patient = services.register_patient(data=_data())
    services.update_patient(
        instance=patient, data=_data(phone="01800000000"), actor=None
    )
    entry = AuditLog.objects.filter(action=AuditAction.UPDATE).latest("id")
    assert "phone" in entry.changes
    assert entry.changes["phone"]["to"] == "01800000000"


def test_soft_delete_and_restore():
    patient = services.register_patient(data=_data())
    services.soft_delete_patient(instance=patient)
    assert Patient.objects.filter(pk=patient.pk).exists() is False
    services.restore_patient(instance=patient)
    assert Patient.objects.filter(pk=patient.pk).exists()


def test_merge_moves_documents_and_archives_duplicate():
    primary = services.register_patient(data=_data(full_name_en="Primary"))
    duplicate = services.register_patient(
        data=_data(full_name_en="Dup", phone="0180001")
    )
    doc = PatientDocument.objects.create(patient=duplicate, title="Scan", file="x.pdf")

    services.merge_patients(primary=primary, duplicate=duplicate)

    doc.refresh_from_db()
    assert doc.patient_id == primary.pk
    duplicate.refresh_from_db()
    assert duplicate.is_deleted is True
    assert AuditLog.objects.filter(
        action=AuditAction.UPDATE, object_id=str(primary.pk)
    ).exists()


def test_merge_into_self_raises():
    patient = services.register_patient(data=_data())
    with pytest.raises(ValueError):
        services.merge_patients(primary=patient, duplicate=patient)
