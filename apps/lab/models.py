"""Domain models for the Laboratory & Radiology (LIS/RIS) module.

The module wraps the CPOE orders created in :mod:`apps.emr` (Phase 6) with the
diagnostic workflow: sample collection/tracking, result entry with reference
ranges and abnormal flagging, second-level verification that freezes a report
(addenda only afterwards), radiology reporting with an uploaded image/PDF, and
lab charge capture for billing.

Every concrete model inherits :class:`~core.models.TimeStampedModel`; money is
``DecimalField(12, 2)``; result/report rows are never hard-edited after
verification (addendum rows are appended instead).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.emr.models import LabOrder, LabOrderItem, RadiologyOrder
from apps.masters.models import LabTest
from apps.opd.models import Doctor
from core.models import TimeStampedModel


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class SequenceKind(models.TextChoices):
    SAMPLE = "sample", _("Sample barcode")
    REPORT = "report", _("Lab report")
    RADIOLOGY = "radiology", _("Radiology report")


class SampleStatus(models.TextChoices):
    PENDING = "pending", _("Pending collection")
    COLLECTED = "collected", _("Collected")
    IN_PROCESS = "in_process", _("In process")
    RESULTED = "resulted", _("Resulted")
    REJECTED = "rejected", _("Rejected")


class ResultFlag(models.TextChoices):
    NORMAL = "normal", _("Normal")
    LOW = "low", _("Low")
    HIGH = "high", _("High")
    CRITICAL_LOW = "critical_low", _("Critical low")
    CRITICAL_HIGH = "critical_high", _("Critical high")
    ABNORMAL = "abnormal", _("Abnormal")


class ReportStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    VERIFIED = "verified", _("Verified")
    AMENDED = "amended", _("Amended")
    RELEASED = "released", _("Released")


class RadiologyStatus(models.TextChoices):
    ORDERED = "ordered", _("Ordered")
    SCHEDULED = "scheduled", _("Scheduled")
    PERFORMED = "performed", _("Performed")
    REPORTED = "reported", _("Reported")
    CANCELLED = "cancelled", _("Cancelled")


#: Flags that should render red / prompt a call-back.
ABNORMAL_FLAGS = (
    ResultFlag.LOW,
    ResultFlag.HIGH,
    ResultFlag.CRITICAL_LOW,
    ResultFlag.CRITICAL_HIGH,
    ResultFlag.ABNORMAL,
)


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------
class LabSequence(TimeStampedModel):
    """Per-year counter per document kind (sample / report / radiology)."""

    year = models.PositiveSmallIntegerField(_("year"))
    kind = models.CharField(_("kind"), max_length=12, choices=SequenceKind.choices)
    last_number = models.PositiveIntegerField(_("last number"), default=0)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("lab sequence")
        verbose_name_plural = _("lab sequences")
        constraints = [
            models.UniqueConstraint(
                fields=["year", "kind"], name="uniq_lab_sequence_year_kind"
            )
        ]

    def __str__(self) -> str:
        return f"{self.year} {self.kind} → {self.last_number}"


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------
class LabSample(TimeStampedModel):
    """A physical specimen tied to a lab order, identified by a barcode."""

    order = models.OneToOneField(
        LabOrder,
        on_delete=models.CASCADE,
        related_name="sample",
        verbose_name=_("lab order"),
    )
    barcode = models.CharField(_("barcode"), max_length=40, unique=True)
    sample_type = models.CharField(_("sample type"), max_length=100, blank=True)
    status = models.CharField(
        _("status"),
        max_length=12,
        choices=SampleStatus.choices,
        default=SampleStatus.PENDING,
        db_index=True,
    )
    collected_at = models.DateTimeField(_("collected at"), null=True, blank=True)
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lab_samples_collected",
        verbose_name=_("collected by"),
    )
    received_at = models.DateTimeField(_("received at"), null=True, blank=True)
    rejected_reason = models.TextField(_("rejection reason"), blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("lab sample")
        verbose_name_plural = _("lab samples")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self) -> str:
        return self.barcode

    @property
    def is_collected(self) -> bool:
        return self.status in {
            SampleStatus.COLLECTED,
            SampleStatus.IN_PROCESS,
            SampleStatus.RESULTED,
        }


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
class LabResult(TimeStampedModel):
    """A single analyte result for one lab order item."""

    order = models.ForeignKey(
        LabOrder,
        on_delete=models.PROTECT,
        related_name="results",
        verbose_name=_("lab order"),
    )
    order_item = models.OneToOneField(
        LabOrderItem,
        on_delete=models.CASCADE,
        related_name="result",
        verbose_name=_("order item"),
    )
    test = models.ForeignKey(
        LabTest,
        on_delete=models.PROTECT,
        related_name="results",
        verbose_name=_("test"),
    )
    value = models.CharField(_("value"), max_length=120, blank=True)
    unit = models.CharField(_("unit"), max_length=50, blank=True)
    reference_range = models.CharField(_("reference range"), max_length=200, blank=True)
    flag = models.CharField(
        _("flag"),
        max_length=15,
        choices=ResultFlag.choices,
        default=ResultFlag.NORMAL,
        db_index=True,
    )
    remarks = models.CharField(_("remarks"), max_length=255, blank=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lab_results_entered",
        verbose_name=_("entered by"),
    )
    entered_at = models.DateTimeField(_("entered at"), null=True, blank=True)
    is_verified = models.BooleanField(_("verified"), default=False, db_index=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lab_results_verified",
        verbose_name=_("verified by"),
    )
    verified_at = models.DateTimeField(_("verified at"), null=True, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("lab result")
        verbose_name_plural = _("lab results")
        ordering = ["id"]
        permissions = [("verify_labresult", _("Can verify lab results"))]

    def __str__(self) -> str:
        return f"{self.test} = {self.value}"

    @property
    def is_abnormal(self) -> bool:
        return self.flag in ABNORMAL_FLAGS


class LabResultAddendum(TimeStampedModel):
    """A correction/comment appended to a result after verification."""

    result = models.ForeignKey(
        LabResult,
        on_delete=models.PROTECT,
        related_name="addenda",
        verbose_name=_("result"),
    )
    text = models.TextField(_("addendum"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lab_addenda",
        verbose_name=_("created by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("lab result addendum")
        verbose_name_plural = _("lab result addenda")
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Addendum · {self.result_id}"


class LabReport(TimeStampedModel):
    """Order-level report that aggregates verified results."""

    order = models.OneToOneField(
        LabOrder,
        on_delete=models.CASCADE,
        related_name="report",
        verbose_name=_("lab order"),
    )
    report_no = models.CharField(_("report number"), max_length=30, unique=True)
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=ReportStatus.choices,
        default=ReportStatus.DRAFT,
        db_index=True,
    )
    remarks = models.TextField(_("remarks"), blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lab_reports_verified",
        verbose_name=_("verified by"),
    )
    verified_at = models.DateTimeField(_("verified at"), null=True, blank=True)
    is_released = models.BooleanField(_("released"), default=False, db_index=True)
    released_at = models.DateTimeField(_("released at"), null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lab_reports_released",
        verbose_name=_("released by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("lab report")
        verbose_name_plural = _("lab reports")
        permissions = [
            ("verify_labreport", _("Can verify lab reports")),
            ("release_labreport", _("Can release lab reports")),
        ]

    def __str__(self) -> str:
        return self.report_no

    @property
    def is_verified(self) -> bool:
        return self.status in {
            ReportStatus.VERIFIED,
            ReportStatus.AMENDED,
            ReportStatus.RELEASED,
        }

    @property
    def has_abnormal(self) -> bool:
        return any(r.is_abnormal for r in self.order.results.all())


# ---------------------------------------------------------------------------
# Radiology
# ---------------------------------------------------------------------------
class RadiologyRecord(TimeStampedModel):
    """Workflow + report for a radiology order (upload-only, no PACS)."""

    order = models.OneToOneField(
        RadiologyOrder,
        on_delete=models.CASCADE,
        related_name="record",
        verbose_name=_("radiology order"),
    )
    report_no = models.CharField(_("report number"), max_length=30, unique=True)
    status = models.CharField(
        _("status"),
        max_length=12,
        choices=RadiologyStatus.choices,
        default=RadiologyStatus.ORDERED,
        db_index=True,
    )
    scheduled_at = models.DateTimeField(_("scheduled at"), null=True, blank=True)
    performed_at = models.DateTimeField(_("performed at"), null=True, blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="radiology_performed",
        verbose_name=_("performed by"),
    )
    radiologist = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="radiology_reports",
        verbose_name=_("radiologist"),
    )
    findings = models.TextField(_("findings"), blank=True)
    impression = models.TextField(_("impression"), blank=True)
    attachment = models.FileField(
        _("report file"), upload_to="radiology/", blank=True, null=True
    )
    is_released = models.BooleanField(_("released"), default=False, db_index=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="radiology_verified",
        verbose_name=_("verified by"),
    )
    verified_at = models.DateTimeField(_("verified at"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("radiology record")
        verbose_name_plural = _("radiology records")
        ordering = ["-created_at"]
        permissions = [("verify_radiologyrecord", _("Can verify radiology reports"))]

    def __str__(self) -> str:
        return self.report_no

    @property
    def is_reported(self) -> bool:
        return self.status == RadiologyStatus.REPORTED


# ---------------------------------------------------------------------------
# Charges (posted to billing in Phase 12)
# ---------------------------------------------------------------------------
class LabCharge(TimeStampedModel):
    """A lab charge line derived from an order item (billing in Phase 12)."""

    order = models.ForeignKey(
        LabOrder,
        on_delete=models.PROTECT,
        related_name="charges",
        verbose_name=_("lab order"),
    )
    test = models.ForeignKey(
        LabTest,
        on_delete=models.PROTECT,
        related_name="charges",
        verbose_name=_("test"),
    )
    amount = models.DecimalField(
        _("amount"), max_digits=12, decimal_places=2, default=0
    )
    is_billed = models.BooleanField(_("billed"), default=False, db_index=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("lab charge")
        verbose_name_plural = _("lab charges")
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "test"], name="uniq_lab_charge_order_test"
            )
        ]

    def __str__(self) -> str:
        return f"{self.test} · {self.amount}"

    @property
    def is_posted(self) -> bool:
        return self.is_billed
