"""Central registry describing every master for the generic CRUD screens.

One :class:`MasterSpec` per master keeps the list/form/import views, URLs and
navigation DRY while still exposing each model's specifics (columns, search
fields, importable columns).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from . import forms
from .models import (Bed, BedType, Department, Designation, Diagnosis, Drug,
                     LabTest, NotificationTemplate, PaymentMethod, Procedure,
                     RadiologyTest, TaxConfig, Ward)

Column = tuple[str, str | Callable[[Any], Any]]


def _active(obj) -> str:
    return "Active" if obj.is_active else "Inactive"


@dataclass(frozen=True)
class MasterSpec:
    """Describes a master for the generic CRUD layer."""

    slug: str
    model: type
    form: type
    label: str
    label_plural: str
    icon: str
    group: str
    columns: list[Column]
    search_fields: list[str] = field(default_factory=list)
    import_fields: list[str] = field(default_factory=list)
    import_required: list[str] = field(default_factory=list)

    @property
    def view_perm(self) -> str:
        return f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"

    @property
    def add_perm(self) -> str:
        return f"{self.model._meta.app_label}.add_{self.model._meta.model_name}"


MASTERS: list[MasterSpec] = [
    # ---- Organisation ----------------------------------------------------
    MasterSpec(
        slug="departments",
        model=Department,
        form=forms.DepartmentForm,
        label="Department",
        label_plural="Departments",
        icon="building-2",
        group="Organisation",
        columns=[
            ("Name", "name"),
            ("Code", "code"),
            ("Type", lambda o: o.get_type_display()),
            ("Head", lambda o: str(o.head) if o.head else "—"),
            ("Status", _active),
        ],
        search_fields=["name", "code"],
        import_fields=["name", "code", "type", "description"],
        import_required=["name", "code"],
    ),
    MasterSpec(
        slug="designations",
        model=Designation,
        form=forms.DesignationForm,
        label="Designation",
        label_plural="Designations",
        icon="id-badge",
        group="Organisation",
        columns=[
            ("Name", "name"),
            ("Code", "code"),
            ("Category", lambda o: o.get_category_display()),
            ("Status", _active),
        ],
        search_fields=["name", "code"],
        import_fields=["name", "code", "category", "description"],
        import_required=["name", "code"],
    ),
    MasterSpec(
        slug="wards",
        model=Ward,
        form=forms.WardForm,
        label="Ward",
        label_plural="Wards",
        icon="layout-grid",
        group="Organisation",
        columns=[
            ("Name", "name"),
            ("Type", lambda o: o.get_type_display()),
            ("Floor", "floor"),
            ("Department", lambda o: str(o.department) if o.department else "—"),
            ("Status", _active),
        ],
        search_fields=["name", "code"],
        import_fields=["name", "code", "type", "floor", "description"],
        import_required=["name", "code"],
    ),
    MasterSpec(
        slug="bed-types",
        model=BedType,
        form=forms.BedTypeForm,
        label="Bed Type",
        label_plural="Bed Types",
        icon="bed-single",
        group="Organisation",
        columns=[
            ("Name", "name"),
            ("Daily Rate", "daily_rate"),
            ("Status", _active),
        ],
        search_fields=["name"],
        import_fields=["name", "daily_rate", "description"],
        import_required=["name"],
    ),
    MasterSpec(
        slug="beds",
        model=Bed,
        form=forms.BedForm,
        label="Bed",
        label_plural="Beds",
        icon="bed-double",
        group="Organisation",
        columns=[
            ("Ward", lambda o: o.ward.name),
            ("Bed No", "bed_no"),
            ("Type", lambda o: o.bed_type.name),
            ("Status", lambda o: o.get_status_display()),
        ],
        search_fields=["bed_no", "ward__name"],
        import_fields=["ward", "bed_no", "bed_type", "daily_rate", "status"],
        import_required=["ward", "bed_no", "bed_type"],
    ),
    # ---- Clinical --------------------------------------------------------
    MasterSpec(
        slug="drugs",
        model=Drug,
        form=forms.DrugForm,
        label="Drug",
        label_plural="Drugs",
        icon="pill",
        group="Clinical",
        columns=[
            ("Generic", "generic_name"),
            ("Brand", lambda o: o.brand_name or "—"),
            ("Form", lambda o: o.get_form_display()),
            ("Strength", lambda o: o.strength or "—"),
            ("Unit Price", "unit_price"),
            ("Status", _active),
        ],
        search_fields=["generic_name", "brand_name", "strength"],
        import_fields=[
            "generic_name",
            "brand_name",
            "form",
            "strength",
            "unit",
            "unit_price",
            "reorder_level",
            "description",
            "is_active",
        ],
        import_required=["generic_name"],
    ),
    MasterSpec(
        slug="lab-tests",
        model=LabTest,
        form=forms.LabTestForm,
        label="Lab Test",
        label_plural="Lab Tests",
        icon="flask-conical",
        group="Clinical",
        columns=[
            ("Code", "code"),
            ("Name", "name"),
            ("Category", lambda o: o.category or "—"),
            ("Price", "price"),
            ("Status", _active),
        ],
        search_fields=["code", "name", "category"],
        import_fields=[
            "code",
            "name",
            "category",
            "price",
            "reference_range",
            "unit",
            "sample_type",
            "is_active",
        ],
        import_required=["code", "name"],
    ),
    MasterSpec(
        slug="radiology-tests",
        model=RadiologyTest,
        form=forms.RadiologyTestForm,
        label="Radiology Test",
        label_plural="Radiology Tests",
        icon="scan",
        group="Clinical",
        columns=[
            ("Code", "code"),
            ("Name", "name"),
            ("Modality", lambda o: o.get_modality_display()),
            ("Price", "price"),
            ("Status", _active),
        ],
        search_fields=["code", "name", "modality"],
        import_fields=["code", "name", "modality", "price", "preparation", "is_active"],
        import_required=["code", "name"],
    ),
    MasterSpec(
        slug="procedures",
        model=Procedure,
        form=forms.ProcedureForm,
        label="Procedure",
        label_plural="Procedures",
        icon="scissors",
        group="Clinical",
        columns=[
            ("Code", "code"),
            ("Name", "name"),
            ("Category", lambda o: o.category or "—"),
            ("Price", "price"),
            ("Status", _active),
        ],
        search_fields=["code", "name", "category"],
        import_fields=["code", "name", "category", "price", "description", "is_active"],
        import_required=["code", "name"],
    ),
    MasterSpec(
        slug="diagnoses",
        model=Diagnosis,
        form=forms.DiagnosisForm,
        label="Diagnosis",
        label_plural="Diagnoses (ICD-10)",
        icon="stethoscope",
        group="Clinical",
        columns=[
            ("Code", "code"),
            ("Name", "name"),
            ("Category", lambda o: o.category or "—"),
            ("Status", _active),
        ],
        search_fields=["code", "name", "category"],
        import_fields=["code", "name", "category", "is_active"],
        import_required=["code", "name"],
    ),
    # ---- Configuration ---------------------------------------------------
    MasterSpec(
        slug="taxes",
        model=TaxConfig,
        form=forms.TaxConfigForm,
        label="Tax / VAT",
        label_plural="Tax & VAT",
        icon="percent",
        group="Configuration",
        columns=[
            ("Name", "name"),
            ("Category", lambda o: o.get_category_display()),
            ("Rate %", "rate"),
            ("Status", _active),
        ],
        search_fields=["name", "category"],
    ),
    MasterSpec(
        slug="payment-methods",
        model=PaymentMethod,
        form=forms.PaymentMethodForm,
        label="Payment Method",
        label_plural="Payment Methods",
        icon="credit-card",
        group="Configuration",
        columns=[
            ("Name", "name"),
            ("Code", "code"),
            ("Kind", lambda o: o.get_kind_display()),
            ("Charge %", "charge_pct"),
            ("Status", _active),
        ],
        search_fields=["name", "code"],
    ),
    MasterSpec(
        slug="notifications",
        model=NotificationTemplate,
        form=forms.NotificationTemplateForm,
        label="Notification Template",
        label_plural="Notification Templates",
        icon="bell-ring",
        group="Configuration",
        columns=[
            ("Name", "name"),
            ("Channel", lambda o: o.get_channel_display()),
            ("Code", "code"),
            ("Status", _active),
        ],
        search_fields=["name", "code"],
    ),
]

MASTER_BY_SLUG: dict[str, MasterSpec] = {spec.slug: spec for spec in MASTERS}
MASTER_GROUPS: dict[str, list[MasterSpec]] = {}
for _spec in MASTERS:
    MASTER_GROUPS.setdefault(_spec.group, []).append(_spec)
