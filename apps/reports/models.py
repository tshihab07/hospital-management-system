"""Domain models for the Reports & Analytics module (RULES Phase 16).

Two models give the control tower its scheduling spine:

* :class:`ReportSchedule` — a recurring definition (which report, how often,
  in which format, to whom) with a computed ``next_run``.
* :class:`ReportRun` — the immutable record of one generated report, holding
  the rendered file (CSV/XLSX/PDF), row count and delivery metadata.

The report *content* itself is never stored in the database — it is derived on
demand from the operational modules (billing, accounting, lab, pharmacy, HR,
OT, IPD, ICU) via :mod:`apps.reports.selectors`.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import SoftDeleteModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class ReportType(models.TextChoices):
    """Every report offered by the control tower (RULES Phase 16)."""

    KPI_SUMMARY = "kpi_summary", _("KPI summary")
    DAILY_CENSUS = "daily_census", _("Daily census")
    MONTHLY_REVENUE = "monthly_revenue", _("Monthly revenue")
    DOCTOR_PERFORMANCE = "doctor_performance", _("Doctor performance")
    DEPARTMENT_PROFITABILITY = "department_profitability", _(
        "Department profitability"
    )
    INVENTORY_CONSUMPTION = "inventory_consumption", _("Inventory consumption")
    BED_OCCUPANCY = "bed_occupancy", _("Bed occupancy")
    ER_WAIT_TIMES = "er_wait_times", _("ER wait times")
    VAT = "vat", _("VAT return")
    COLLECTION = "collection", _("Collection")
    PAYROLL = "payroll", _("Payroll register")
    PNL = "pnl", _("Profit & loss")


class ReportFrequency(models.TextChoices):
    DAILY = "daily", _("Daily")
    WEEKLY = "weekly", _("Weekly")
    MONTHLY = "monthly", _("Monthly")


class ReportFormat(models.TextChoices):
    PDF = "pdf", _("PDF")
    CSV = "csv", _("CSV")
    XLSX = "xlsx", _("Excel (XLSX)")


class ReportRunStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")


FREQUENCY_DELTAS = {
    ReportFrequency.DAILY: timedelta(days=1),
    ReportFrequency.WEEKLY: timedelta(days=7),
    ReportFrequency.MONTHLY: timedelta(days=30),
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ReportSchedule(SoftDeleteModel):
    """A recurring report definition.

    ``next_run`` is advanced by :func:`apps.reports.services.advance_next_run`
    after each successful (or failed) delivery so the management command is
    idempotent and safe to run as often as desired.
    """

    name = models.CharField(_("name"), max_length=150, unique=True)
    report_type = models.CharField(
        _("report"),
        max_length=32,
        choices=ReportType.choices,
        db_index=True,
    )
    frequency = models.CharField(
        _("frequency"),
        max_length=10,
        choices=ReportFrequency.choices,
        default=ReportFrequency.DAILY,
        db_index=True,
    )
    report_format = models.CharField(
        _("format"),
        max_length=8,
        choices=ReportFormat.choices,
        default=ReportFormat.PDF,
    )
    recipients = models.TextField(
        _("recipients"),
        blank=True,
        help_text=_("Comma or newline separated email addresses."),
    )
    parameters = models.JSONField(
        _("parameters"),
        default=dict,
        blank=True,
        help_text=_("Report filters, e.g. {\"range_days\": 30, \"year\": 2026}."),
    )
    is_active = models.BooleanField(_("active"), default=True, db_index=True)
    next_run = models.DateTimeField(_("next run"), null=True, blank=True, db_index=True)
    last_run = models.DateTimeField(_("last run"), null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="report_schedules_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("report schedule")
        verbose_name_plural = _("report schedules")
        ordering = ["name"]
        permissions = [
            ("run_reportschedule", _("Can run report schedules")),
        ]

    def __str__(self) -> str:
        return f"{self.name} · {self.get_report_type_display()}"

    @property
    def recipient_list(self) -> list[str]:
        """Normalise ``recipients`` into a clean list of addresses."""
        raw = (self.recipients or "").replace(",", "\n")
        return [addr.strip() for addr in raw.splitlines() if addr.strip()]

    @property
    def is_due(self) -> bool:
        if not self.is_active:
            return False
        if self.next_run is None:
            return True
        return self.next_run <= timezone.now()

    def compute_next_run(self, *, reference=None):
        """Return the next scheduled timestamp after ``reference`` (or now)."""
        base = reference or timezone.now()
        delta = FREQUENCY_DELTAS.get(self.frequency, timedelta(days=1))
        nxt = base + delta
        if self.frequency == ReportFrequency.MONTHLY:
            # Keep the same wall-clock time a month ahead where possible.
            try:
                nxt = base.replace(month=base.month + 1)
            except ValueError:  # pragma: no cover - month rollover
                nxt = base + delta
        return nxt


class ReportRun(TimeStampedModel):
    """A single generated report (ad-hoc or from a schedule)."""

    schedule = models.ForeignKey(
        ReportSchedule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="runs",
        verbose_name=_("schedule"),
    )
    report_type = models.CharField(
        _("report"),
        max_length=32,
        choices=ReportType.choices,
        db_index=True,
    )
    report_format = models.CharField(
        _("format"),
        max_length=8,
        choices=ReportFormat.choices,
        default=ReportFormat.CSV,
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=ReportRunStatus.choices,
        default=ReportRunStatus.PENDING,
        db_index=True,
    )
    period_start = models.DateField(_("period start"), null=True, blank=True)
    period_end = models.DateField(_("period end"), null=True, blank=True)
    row_count = models.PositiveIntegerField(_("rows"), default=0)
    file = models.FileField(
        _("file"), upload_to="reports/runs/%Y/%m/", null=True, blank=True
    )
    emailed_to = models.CharField(_("emailed to"), max_length=500, blank=True)
    error = models.TextField(_("error"), blank=True)
    started_at = models.DateTimeField(_("started at"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="report_runs_created",
        verbose_name=_("created by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("report run")
        verbose_name_plural = _("report runs")
        ordering = ["-created_at"]
        permissions = [
            ("view_hospitalreports", _("Can view hospital reports")),
            ("export_hospitalreports", _("Can export hospital reports")),
        ]

    def __str__(self) -> str:
        when = self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "—"
        return f"{self.get_report_type_display()} · {when}"

    @property
    def filename(self) -> str:
        try:
            return self.file.name.rsplit("/", 1)[-1]
        except (AttributeError, IndexError):  # pragma: no cover - defensive
            return ""

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return round((self.finished_at - self.started_at).total_seconds(), 2)
        return None
