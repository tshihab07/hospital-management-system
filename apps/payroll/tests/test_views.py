"""View / access-control tests for the Payroll module (RULES Phase 14)."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounting import services as accounting

from .. import services
from ..models import AdjustmentKind, PayrollRun, PayrollRunStatus, Payslip
from . import factories

pytestmark = pytest.mark.django_db

PERMS = [
    "payroll.view_payrollrun",
    "payroll.add_payrollrun",
    "payroll.run_payroll",
    "payroll.approve_payrollrun",
    "payroll.pay_payrollrun",
    "payroll.export_beftn",
    "payroll.view_payslip",
    "payroll.view_salaryadjustment",
    "payroll.add_salaryadjustment",
    "payroll.change_salaryadjustment",
    "payroll.view_taxslab",
    "payroll.manage_taxslab",
    "payroll.view_payrollsetting",
    "payroll.manage_payrollsettings",
    "hr.view_staff",
]


@pytest.fixture
def seeded():
    accounting.seed_chart_of_accounts()
    return factories.seed_payroll()


@pytest.fixture
def client_logged(client):
    client.force_login(factories.make_user(*PERMS))
    return client


def test_run_list_requires_login(client):
    response = client.get(reverse("payroll:run_list"))
    assert response.status_code in (301, 302)


def test_run_list_ok(client_logged, seeded):
    response = client_logged.get(reverse("payroll:run_list"))
    assert response.status_code == 200


def test_create_run_via_view(client_logged, seeded):
    factories.make_staff("EMP-V01")
    response = client_logged.post(
        reverse("payroll:run_create"),
        {"year": 2026, "month": 1, "payment_method": "bank"},
    )
    assert response.status_code == 302
    run = PayrollRun.objects.get()
    assert run.status == PayrollRunStatus.DRAFT
    assert run.employee_count == 1


def test_run_detail_ok(client_logged, seeded):
    factories.make_staff("EMP-V02")
    run = services.generate_run(year=2026, month=2)
    response = client_logged.get(reverse("payroll:run_detail", args=[run.pk]))
    assert response.status_code == 200
    assert b"RUN-2026-02" in response.content


def test_approve_action(client_logged, seeded):
    factories.make_staff("EMP-V03")
    run = services.generate_run(year=2026, month=3)
    response = client_logged.post(
        reverse("payroll:run_action", args=[run.pk, "approve"])
    )
    assert response.status_code == 302
    run.refresh_from_db()
    assert run.status == PayrollRunStatus.APPROVED


def test_pay_action(client_logged, seeded):
    factories.make_staff("EMP-V04")
    run = services.generate_run(year=2026, month=4)
    services.approve_run(run)
    response = client_logged.post(reverse("payroll:run_action", args=[run.pk, "pay"]))
    assert response.status_code == 302
    run.refresh_from_db()
    assert run.status == PayrollRunStatus.PAID


def test_payslip_detail_ok(client_logged, seeded):
    factories.make_staff("EMP-V05")
    run = services.generate_run(year=2026, month=5)
    slip = Payslip.objects.get(run=run)
    response = client_logged.get(reverse("payroll:payslip_detail", args=[slip.pk]))
    assert response.status_code == 200


def test_register_page(client_logged, seeded):
    factories.make_staff("EMP-V06")
    run = services.generate_run(year=2026, month=6)
    response = client_logged.get(reverse("payroll:register", args=[run.pk]))
    assert response.status_code == 200


def test_register_csv_export(client_logged, seeded):
    factories.make_staff("EMP-V07")
    run = services.generate_run(year=2026, month=7)
    response = client_logged.get(
        reverse("payroll:register", args=[run.pk]) + "?export=csv"
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")


def test_beftn_bank_file(client_logged, seeded):
    factories.make_staff(
        "EMP-V08",
        salary_payment_mode="bank",
        bank_name="DBBL",
        bank_account_no="1234567890",
        bank_routing_no="090261234",
    )
    run = services.generate_run(year=2026, month=8, payment_method="bank")
    services.approve_run(run)
    response = client_logged.get(reverse("payroll:run_bank_file", args=[run.pk]))
    assert response.status_code == 200
    assert b"BEFTN SALARY FILE" in response.content


def test_beftn_bank_file_draft_blocked(client_logged, seeded):
    run = services.generate_run(year=2026, month=9, payment_method="bank")
    response = client_logged.get(reverse("payroll:run_bank_file", args=[run.pk]))
    assert response.status_code == 302


def test_adjustment_list_ok(client_logged, seeded):
    response = client_logged.get(reverse("payroll:adjustment_list"))
    assert response.status_code == 200


def test_adjustment_create_via_view(client_logged, seeded):
    staff = factories.make_staff("EMP-V09")
    response = client_logged.post(
        reverse("payroll:adjustment_create"),
        {
            "staff": staff.pk,
            "year": 2026,
            "month": 1,
            "kind": AdjustmentKind.EARNING,
            "amount": "2500.00",
            "reason": "Bonus",
        },
    )
    assert response.status_code == 302
    assert staff.salary_adjustments.count() == 1


def test_salary_structure_ok(client_logged, seeded):
    factories.make_staff("EMP-V10")
    response = client_logged.get(reverse("payroll:salary_structure"))
    assert response.status_code == 200


def test_tax_slab_list_ok(client_logged, seeded):
    response = client_logged.get(reverse("payroll:tax_slab_list"))
    assert response.status_code == 200


def test_settings_ok(client_logged, seeded):
    response = client_logged.get(reverse("payroll:settings"))
    assert response.status_code == 200


def test_permitted_user_without_perm_is_denied(client, seeded):
    client.force_login(factories.make_user("hr.view_staff"))
    response = client.get(reverse("payroll:run_list"))
    assert response.status_code == 403
