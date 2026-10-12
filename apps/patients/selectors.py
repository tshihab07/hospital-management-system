"""Read-only query helpers for patients."""

from __future__ import annotations

from django.db.models import Q

from .models import Patient


def patient_list(
    *,
    search: str | None = None,
    gender: str | None = None,
    patient_type: str | None = None,
    is_active: bool | None = None,
    include_deleted: bool = False,
):
    """Return patients filtered by the given criteria."""
    qs = Patient.all_objects.all() if include_deleted else Patient.objects.all()

    if search:
        qs = qs.filter(
            Q(uhid__icontains=search)
            | Q(full_name_en__icontains=search)
            | Q(full_name_bn__icontains=search)
            | Q(phone__icontains=search)
            | Q(nid__icontains=search)
        )
    if gender:
        qs = qs.filter(gender=gender)
    if patient_type:
        qs = qs.filter(patient_type=patient_type)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)

    return qs.select_related("registered_by").order_by("-created_at")


def find_duplicates(*, phone=None, dob=None, full_name_en=None, exclude_pk=None):
    """Return existing patients that look like the one being registered.

    The exit criteria require a warning for the same phone + DOB combination;
    a strong name match is also surfaced.
    """
    condition = Q()
    if phone and dob:
        condition |= Q(phone=phone, date_of_birth=dob)
    elif phone:
        condition |= Q(phone=phone)
    elif dob:
        condition |= Q(date_of_birth=dob)
    if full_name_en:
        condition |= Q(full_name_en__iexact=full_name_en)

    if not condition:
        return Patient.objects.none()

    qs = Patient.objects.filter(condition)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.distinct()


def patient_documents(patient):
    """Documents attached to a patient, newest first."""
    return patient.documents.select_related("uploaded_by").order_by("-created_at")
