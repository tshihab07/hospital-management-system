"""Master-data models, grouped by concern."""

from .base import CodedMaster, MasterModel, NamedMaster
from .clinical import (Diagnosis, Drug, DrugForm, LabTest, Procedure,
                       RadiologyModality, RadiologyTest)
from .config import (HospitalProfile, NotificationChannel,
                     NotificationTemplate, PaymentKind, PaymentMethod,
                     TaxCategory, TaxConfig)
from .organization import (Bed, BedStatus, BedType, Department, DepartmentType,
                           Designation, DesignationCategory, Ward, WardType)

__all__ = [
    # base
    "MasterModel",
    "NamedMaster",
    "CodedMaster",
    # organization
    "Department",
    "DepartmentType",
    "Designation",
    "DesignationCategory",
    "Ward",
    "WardType",
    "BedType",
    "Bed",
    "BedStatus",
    # clinical
    "Drug",
    "DrugForm",
    "LabTest",
    "RadiologyTest",
    "RadiologyModality",
    "Procedure",
    "Diagnosis",
    # config
    "TaxConfig",
    "TaxCategory",
    "PaymentMethod",
    "PaymentKind",
    "NotificationTemplate",
    "NotificationChannel",
    "HospitalProfile",
]
