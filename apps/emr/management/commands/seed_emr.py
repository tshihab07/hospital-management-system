"""Seed EMR reference data: SOAP templates and basic drug-interaction rules.

Usage::

    python manage.py seed_emr

Idempotent: safe to re-run. Drug-interaction rules are only created when both
referenced drugs already exist in the master data (run ``seed_masters`` first).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.emr.models import (DrugInteractionRule, InteractionSeverity,
                             SoapTemplate)
from apps.masters.models import Drug

SOAP_TEMPLATES = [
    {
        "name": "Fever — adult",
        "chief_complaint": "Fever for ___ days, associated with ___.",
        "subjective": "Fever since ___, highest recorded ___, associated with "
        "chills / headache / body ache. No cough, no burning micturition.",
        "objective": "Temp ___°C, pulse ___, BP ___. Conscious, oriented. "
        "Throat congested; chest clear.",
        "assessment": "Acute febrile illness, likely viral / to rule out URTI.",
        "plan": "Antipyretic, hydration, CBC + dengue NS1 if persistent, review in 2 days.",
    },
    {
        "name": "Hypertension follow-up",
        "chief_complaint": "Follow-up for hypertension.",
        "subjective": "Compliant with medication / occasional missed doses. "
        "No chest pain, no shortness of breath, no headache.",
        "objective": "BP ___, pulse ___. S1 S2 normal, no murmur. No pedal edema.",
        "assessment": "Essential hypertension — controlled / uncontrolled.",
        "plan": "Continue antihypertensive, salt restriction, lipid profile + ECG, review 1 month.",
    },
    {
        "name": "Type 2 Diabetes follow-up",
        "chief_complaint": "Follow-up for diabetes mellitus.",
        "subjective": "No polyuria / polydipsia. No hypoglycaemic episodes.",
        "objective": "BP ___, weight ___. Feet: normal sensation, no ulcer.",
        "assessment": "Type 2 diabetes mellitus — controlled / uncontrolled.",
        "plan": "Continue antidiabetic, diet counselling, HbA1c + creatinine, review 3 months.",
    },
    {
        "name": "Acute URTI",
        "chief_complaint": "Cough, runny nose, sore throat for ___ days.",
        "subjective": "Cough, nasal congestion, sore throat. No breathlessness. "
        "No high-grade fever.",
        "objective": "Temp ___. Throat congested. Chest clear on auscultation.",
        "assessment": "Acute upper respiratory tract infection (viral).",
        "plan": "Antihistamine, warm saline gargle, antipyretic PRN, review if not improving in 5 days.",
    },
]

# (generic_a, generic_b, severity, description)
INTERACTION_RULES = [
    (
        "Azithromycin",
        "Amlodipine",
        InteractionSeverity.MODERATE,
        "Possible additive QT-interval prolongation; monitor ECG in at-risk patients.",
    ),
    (
        "Omeprazole",
        "Metformin",
        InteractionSeverity.MINOR,
        "Long-term proton-pump use may reduce vitamin B12 absorption; periodic monitoring advised.",
    ),
]


class Command(BaseCommand):
    help = "Seed SOAP templates and basic drug-interaction rules for the EMR module."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        tmpl_created = 0
        for row in SOAP_TEMPLATES:
            _, created = SoapTemplate.objects.get_or_create(
                name=row["name"], defaults=row
            )
            tmpl_created += int(created)

        rule_created = 0
        for generic_a, generic_b, severity, description in INTERACTION_RULES:
            drug_a = Drug.objects.filter(generic_name=generic_a, is_active=True).first()
            drug_b = Drug.objects.filter(generic_name=generic_b, is_active=True).first()
            if not drug_a or not drug_b or drug_a.pk == drug_b.pk:
                continue
            _, created = DrugInteractionRule.objects.get_or_create(
                drug_a=drug_a,
                drug_b=drug_b,
                defaults={"severity": severity, "description": description},
            )
            rule_created += int(created)

        self.stdout.write(
            self.style.SUCCESS(
                f"EMR seed complete: {tmpl_created} SOAP template(s), "
                f"{rule_created} interaction rule(s) created."
            )
        )
