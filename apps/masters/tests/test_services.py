"""Service-layer tests: atomic writes + audit trail."""

from __future__ import annotations

import pytest

from apps.masters import services
from apps.masters.models import Drug
from core.audit import AuditAction, AuditLog

pytestmark = pytest.mark.django_db


def test_create_master_writes_audit():
    drug = services.create_master(
        model=Drug,
        data={"generic_name": "Napa", "form": "tablet"},
    )
    assert drug.pk is not None
    assert AuditLog.objects.filter(
        action=AuditAction.CREATE, object_id=str(drug.pk)
    ).exists()


def test_update_master_records_diff():
    drug = services.create_master(model=Drug, data={"generic_name": "Napa"})
    services.update_master(instance=drug, data={"brand_name": "Napa Extra"})
    entry = AuditLog.objects.filter(action=AuditAction.UPDATE).latest("id")
    assert "brand_name" in entry.changes
    assert entry.changes["brand_name"]["to"] == "Napa Extra"


def test_toggle_master_active():
    drug = services.create_master(model=Drug, data={"generic_name": "Napa"})
    services.toggle_master_active(instance=drug)
    drug.refresh_from_db()
    assert drug.is_active is False


def test_delete_master_writes_audit_and_removes():
    drug = services.create_master(model=Drug, data={"generic_name": "Napa"})
    pk = drug.pk
    services.delete_master(instance=drug)
    assert not Drug.objects.filter(pk=pk).exists()
    assert AuditLog.objects.filter(action=AuditAction.DELETE).exists()
