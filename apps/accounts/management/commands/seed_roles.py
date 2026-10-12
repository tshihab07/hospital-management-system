"""Seed default IHMS roles and their permission grants.

Usage::

    python manage.py seed_roles          # create missing roles only
    python manage.py seed_roles --sync   # also refresh permissions on existing roles

The command is idempotent: re-running never duplicates roles and only touches
permission grants when ``--sync`` is passed (or the role is newly created).
Granular, per-module grants are declared as ``<app_label>.<codename>`` strings
or whole ``apps`` (e.g. every ``accounts.*`` permission).
"""

from __future__ import annotations

import logging

from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role

logger = logging.getLogger(__name__)

ROLE_SPECS: dict[str, dict] = {
    "Super Admin": {
        "description": "Full, unrestricted access to every module.",
        "is_system": True,
        "all": True,
    },
    "Hospital Admin": {
        "description": "Administrative access to users, roles and configuration.",
        "is_system": True,
        "apps": ["accounts", "core", "masters", "patients", "opd", "hr", "emr", "ipd"],
    },
    "Auditor": {
        "description": "Read-only access to the audit trail and account directory.",
        "is_system": True,
        "perms": [
            "accounts.view_user",
            "accounts.view_role",
            "core.view_auditlog",
        ],
    },
    "Doctor": {
        "description": "Clinical access for physicians (expanded in later phases).",
        "perms": [
            "accounts.view_user",
            "patients.view_patient",
            "masters.view_diagnosis",
            "masters.view_drug",
            "masters.view_labtest",
            "masters.view_radiologytest",
            "masters.view_procedure",
            "masters.view_department",
            "masters.view_ward",
            "masters.view_bed",
            "masters.view_bedtype",
            "opd.view_doctor",
            "opd.view_appointment",
            "opd.change_appointment",
            "hr.view_staff",
            "hr.view_dutyroster",
            "emr.view_encounter",
            "emr.add_encounter",
            "emr.change_encounter",
            "emr.view_soapnote",
            "emr.add_soapnote",
            "emr.change_soapnote",
            "emr.view_vital",
            "emr.add_vital",
            "emr.view_visitdiagnosis",
            "emr.add_visitdiagnosis",
            "emr.delete_visitdiagnosis",
            "emr.view_problemlistentry",
            "emr.add_problemlistentry",
            "emr.change_problemlistentry",
            "emr.view_allergy",
            "emr.add_allergy",
            "emr.view_prescription",
            "emr.add_prescription",
            "emr.change_prescription",
            "emr.view_laborder",
            "emr.add_laborder",
            "emr.change_laborder",
            "emr.view_radiologyorder",
            "emr.add_radiologyorder",
            "emr.change_radiologyorder",
            "emr.view_procedureorder",
            "emr.add_procedureorder",
            "emr.change_procedureorder",
            "emr.view_clinicalattachment",
            "emr.add_clinicalattachment",
            "emr.delete_clinicalattachment",
            "emr.view_soaptemplate",
            "emr.add_soaptemplate",
            "ipd.view_admission",
            "ipd.add_admission",
            "ipd.change_admission",
            "ipd.add_bedtransfer",
            "ipd.view_ward",
            "ipd.view_bed",
            "ipd.view_dailycharge",
            "ipd.view_dischargesummary",
            "ipd.add_dischargesummary",
        ],
    },
    "Nurse": {
        "description": "Ward and clinical support access (expanded in later phases).",
        "perms": [
            "patients.view_patient",
            "patients.change_patient",
            "opd.view_doctor",
            "opd.view_appointment",
            "opd.change_appointment",
            "hr.view_staff",
            "hr.view_dutyroster",
            "emr.view_encounter",
            "emr.view_soapnote",
            "emr.view_vital",
            "emr.add_vital",
            "emr.view_visitdiagnosis",
            "emr.view_problemlistentry",
            "emr.view_allergy",
            "emr.add_allergy",
            "emr.view_prescription",
            "emr.view_laborder",
            "emr.view_radiologyorder",
            "emr.view_procedureorder",
            "emr.view_clinicalattachment",
            "emr.add_clinicalattachment",
            "ipd.view_admission",
            "ipd.add_admission",
            "ipd.change_admission",
            "ipd.add_bedtransfer",
            "ipd.view_ward",
            "ipd.view_bed",
            "ipd.view_dailycharge",
            "ipd.view_dischargesummary",
            "ipd.change_dischargeclearance",
            "ipd.add_nursingnote",
            "ipd.add_medicationadministration",
            "ipd.add_intakeoutput",
        ],
    },
    "Receptionist": {
        "description": "Front-desk registration and appointment access.",
        "perms": [
            "patients.view_patient",
            "patients.add_patient",
            "patients.change_patient",
            "opd.view_doctor",
            "opd.view_appointment",
            "opd.add_appointment",
            "opd.change_appointment",
            "hr.view_staff",
            "emr.view_encounter",
            "emr.add_encounter",
            "ipd.view_admission",
        ],
    },
    "Accountant": {
        "description": "Billing and finance access (expanded in later phases).",
        "perms": [
            "patients.view_patient",
            "opd.view_doctor",
            "opd.view_appointment",
            "hr.view_staff",
            "ipd.view_admission",
            "ipd.view_dailycharge",
            "ipd.view_dischargesummary",
        ],
    },
    "HR Manager": {
        "description": "Staff records, roster, attendance and leave administration.",
        "perms": [
            "patients.view_patient",
            "opd.view_doctor",
            "hr.view_staff",
            "hr.add_staff",
            "hr.change_staff",
            "hr.view_shift",
            "hr.add_shift",
            "hr.change_shift",
            "hr.view_dutyroster",
            "hr.add_dutyroster",
            "hr.change_dutyroster",
            "hr.view_attendance",
            "hr.add_attendance",
            "hr.change_attendance",
            "hr.view_leavebalance",
            "hr.change_leavebalance",
            "hr.view_leavetype",
            "hr.add_leavetype",
            "hr.change_leavetype",
            "hr.view_leaverequest",
            "hr.add_leaverequest",
            "hr.change_leaverequest",
        ],
    },
    "Lab Technician": {
        "description": "Laboratory order and result access.",
        "perms": [
            "patients.view_patient",
            "emr.view_laborder",
            "emr.change_laborder",
            "emr.view_radiologyorder",
            "emr.change_radiologyorder",
        ],
    },
    "Pharmacist": {
        "description": "Pharmacy dispensing and stock access.",
        "perms": [
            "patients.view_patient",
            "emr.view_prescription",
        ],
    },
}


def _permissions_for(spec: dict):
    """Resolve the queryset of permissions described by a role spec."""
    if spec.get("all"):
        return Permission.objects.all()

    qs = Permission.objects.none()
    for candidate in spec.get("perms", []):
        app_label, _, codename = candidate.partition(".")
        qs = qs | Permission.objects.filter(
            content_type__app_label=app_label, codename=codename
        )
    for app_label in spec.get("apps", []):
        qs = qs | Permission.objects.filter(content_type__app_label=app_label)
    return qs.distinct()


class Command(BaseCommand):
    help = "Seed default IHMS roles and permissions."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Refresh permission grants on existing roles.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        sync = options["sync"]
        created_count = 0
        updated_count = 0

        for name, spec in ROLE_SPECS.items():
            role, created = Role.objects.get_or_create(
                name=name,
                defaults={
                    "description": spec.get("description", ""),
                    "is_system": spec.get("is_system", False),
                },
            )
            if created:
                created_count += 1

            if created or sync:
                role.permissions.set(_permissions_for(spec))
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Roles seeded: {created_count} created, "
                f"{updated_count} permission set(s) refreshed."
            )
        )
        logger.info(
            "seed_roles: %s created, %s refreshed.", created_count, updated_count
        )
