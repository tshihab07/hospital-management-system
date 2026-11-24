"""Views for the Reports & Analytics module (RULES Phase 16).

Views validate input, read through :mod:`apps.reports.selectors`, render via
``templates/reports/`` and delegate any export/scheduling write to
:mod:`apps.reports.services`. Reports support ``?export=csv|xlsx|pdf``.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, View
from django.views.generic.base import TemplateResponseMixin

from core.audit import AuditAction, log_action
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from . import exports, selectors, services
from .forms import ReportFilterForm, ReportScheduleForm
from .models import ReportRun, ReportRunStatus, ReportSchedule, ReportType

# ---------------------------------------------------------------------------
# Permission codenames
# ---------------------------------------------------------------------------
VIEW_REPORT = "reports.view_hospitalreports"
EXPORT_REPORT = "reports.export_hospitalreports"
VIEW_SCHEDULE = "reports.view_reportschedule"
ADD_SCHEDULE = "reports.add_reportschedule"
CHANGE_SCHEDULE = "reports.change_reportschedule"
DELETE_SCHEDULE = "reports.delete_reportschedule"
RUN_SCHEDULE = "reports.run_reportschedule"
VIEW_RUN = "reports.view_reportrun"


def _date_param(request, key):
    raw = request.GET.get(key)
    return parse_date(raw) if raw else None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "reports/dashboard.html"
    permission_required = VIEW_REPORT

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("Analytics"),
                "kpis": selectors.dashboard_kpis(),
                "alerts": selectors.dashboard_alerts(),
                "recent_runs": ReportRun.objects.select_related("schedule")[:8],
                "schedules": ReportSchedule.objects.filter(is_active=True)[:6],
                "report_catalog": self._catalog(),
            }
        )

    @staticmethod
    def _catalog():
        """Group the report types into a simple catalogue for the dashboard."""
        return [
            {"label": _("Clinical"), "reports": [
                {"label": ReportType.DAILY_CENSUS.label, "url": "reports:daily_census"},
                {"label": ReportType.BED_OCCUPANCY.label, "url": "reports:bed_occupancy"},
                {"label": ReportType.ER_WAIT_TIMES.label, "url": "reports:er_wait_times"},
            ]},
            {"label": _("Financial"), "reports": [
                {"label": ReportType.MONTHLY_REVENUE.label, "url": "reports:monthly_revenue"},
                {"label": ReportType.COLLECTION.label, "url": "reports:collection"},
                {"label": ReportType.VAT.label, "url": "reports:vat"},
                {"label": ReportType.PNL.label, "url": "reports:pnl"},
                {"label": ReportType.DEPARTMENT_PROFITABILITY.label, "url": "reports:department_profitability"},
            ]},
            {"label": _("Operations"), "reports": [
                {"label": ReportType.DOCTOR_PERFORMANCE.label, "url": "reports:doctor_performance"},
                {"label": ReportType.INVENTORY_CONSUMPTION.label, "url": "reports:inventory_consumption"},
                {"label": ReportType.PAYROLL.label, "url": "reports:payroll"},
            ]},
        ]


# ---------------------------------------------------------------------------
# Generic report view
# ---------------------------------------------------------------------------
class BaseReportView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "reports/report.html"
    report_type: str = ReportType.DAILY_CENSUS
    permission_required = VIEW_REPORT
    url_name = "reports:dashboard"

    def get(self, request, *args, **kwargs):
        start = _date_param(request, "start")
        end = _date_param(request, "end")
        report = selectors.build_report(self.report_type, start=start, end=end)

        if request.GET.get("export"):
            if not request.user.has_perm(EXPORT_REPORT):
                log_action(
                    AuditAction.DENIED,
                    model_name="ReportExport",
                    object_repr=request.path,
                )
                from django.core.exceptions import PermissionDenied

                raise PermissionDenied(_("You cannot export reports."))
            response = exports.export_response(request, report)
            if response is not None:
                log_action(
                    AuditAction.EXPORT,
                    instance=None,
                    model_name="Report",
                    object_repr=f"{report['title']} ({request.GET.get('export')})",
                    changes={"rows": len(report["rows"])},
                )
                return response

        return self.render_to_response(
            {
                "page_title": report["title"],
                "report": report,
                "report_type": self.report_type,
                "url_name": self.url_name,
                "form": ReportFilterForm(
                    initial={
                        "start": report.get("start"),
                        "end": report.get("end"),
                    }
                ),
            }
        )


class DailyCensusView(BaseReportView):
    report_type = ReportType.DAILY_CENSUS
    url_name = "reports:daily_census"


class MonthlyRevenueView(BaseReportView):
    report_type = ReportType.MONTHLY_REVENUE
    url_name = "reports:monthly_revenue"


class DoctorPerformanceView(BaseReportView):
    report_type = ReportType.DOCTOR_PERFORMANCE
    url_name = "reports:doctor_performance"


class DepartmentProfitabilityView(BaseReportView):
    report_type = ReportType.DEPARTMENT_PROFITABILITY
    url_name = "reports:department_profitability"


class InventoryConsumptionView(BaseReportView):
    report_type = ReportType.INVENTORY_CONSUMPTION
    url_name = "reports:inventory_consumption"


class BedOccupancyView(BaseReportView):
    report_type = ReportType.BED_OCCUPANCY
    url_name = "reports:bed_occupancy"


class ErWaitTimesView(BaseReportView):
    report_type = ReportType.ER_WAIT_TIMES
    url_name = "reports:er_wait_times"


class VatReportView(BaseReportView):
    report_type = ReportType.VAT
    url_name = "reports:vat"


class CollectionReportView(BaseReportView):
    report_type = ReportType.COLLECTION
    url_name = "reports:collection"


class PayrollReportView(BaseReportView):
    report_type = ReportType.PAYROLL
    url_name = "reports:payroll"


class ProfitAndLossView(BaseReportView):
    report_type = ReportType.PNL
    url_name = "reports:pnl"


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
class ScheduleListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView
):
    template_name = "reports/schedule_list.html"
    context_object_name = "schedules"
    permission_required = VIEW_SCHEDULE
    paginate_by = 25

    def get_queryset(self):
        qs = ReportSchedule.objects.select_related("created_by")
        return qs.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Report schedules")
        return context


class ScheduleCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ADD_SCHEDULE

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "reports/schedule_form.html",
            {"form": ReportScheduleForm(), "page_title": _("New report schedule")},
        )

    def post(self, request, *args, **kwargs):
        form = ReportScheduleForm(request.POST)
        if form.is_valid():
            schedule = form.save(commit=False)
            schedule.created_by = request.user
            schedule.save()
            messages.success(request, _("Report schedule created."))
            return redirect("reports:schedule_list")
        return render(
            request,
            "reports/schedule_form.html",
            {"form": form, "page_title": _("New report schedule")},
        )


class ScheduleUpdateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = CHANGE_SCHEDULE

    def get(self, request, pk, *args, **kwargs):
        schedule = get_object_or_404(ReportSchedule, pk=pk)
        return render(
            request,
            "reports/schedule_form.html",
            {
                "form": ReportScheduleForm(instance=schedule),
                "schedule": schedule,
                "page_title": _("Edit report schedule"),
            },
        )

    def post(self, request, pk, *args, **kwargs):
        schedule = get_object_or_404(ReportSchedule, pk=pk)
        form = ReportScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            form.save()
            messages.success(request, _("Report schedule updated."))
            return redirect("reports:schedule_list")
        return render(
            request,
            "reports/schedule_form.html",
            {
                "form": form,
                "schedule": schedule,
                "page_title": _("Edit report schedule"),
            },
        )


class ScheduleDeleteView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = DELETE_SCHEDULE

    def post(self, request, pk, *args, **kwargs):
        schedule = get_object_or_404(ReportSchedule, pk=pk)
        schedule.soft_delete()
        messages.success(request, _("Report schedule removed."))
        return redirect("reports:schedule_list")


class ScheduleRunNowView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = RUN_SCHEDULE

    def post(self, request, pk, *args, **kwargs):
        schedule = get_object_or_404(ReportSchedule, pk=pk)
        run = services.run_schedule(
            schedule, actor=request.user, request=request, send_email=False
        )
        if run.status == ReportRunStatus.SUCCESS:
            messages.success(request, _("Report generated (%(n)s rows).") % {"n": run.row_count})
        else:
            messages.error(request, _("Report failed: %(e)s") % {"e": run.error})
        return redirect("reports:run_detail", pk=run.pk)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
class RunListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "reports/run_list.html"
    context_object_name = "runs"
    permission_required = VIEW_RUN
    paginate_by = 25

    def get_queryset(self):
        self.report_type = self.request.GET.get("report_type", "").strip()
        self.status = self.request.GET.get("status", "").strip()
        qs = ReportRun.objects.select_related("schedule", "created_by")
        if self.report_type:
            qs = qs.filter(report_type=self.report_type)
        if self.status:
            qs = qs.filter(status=self.status)
        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": _("Report runs"),
                "report_type": self.report_type,
                "status": self.status,
                "report_types": ReportType.choices,
                "statuses": ReportRunStatus.choices,
            }
        )
        return context


class RunDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "reports/run_detail.html"
    permission_required = VIEW_RUN

    def get(self, request, pk, *args, **kwargs):
        run = get_object_or_404(ReportRun.objects.select_related("schedule"), pk=pk)
        return self.render_to_response(
            {"page_title": _("Report run"), "run": run}
        )


class RunDownloadView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = EXPORT_REPORT

    def get(self, request, pk, *args, **kwargs):
        run = get_object_or_404(ReportRun, pk=pk)
        if not run.file:
            raise Http404(_("This run has no generated file."))
        log_action(
            AuditAction.EXPORT,
            instance=run,
            changes={"download": run.filename},
        )
        response = FileResponse(
            run.file.open("rb"),
            content_type=exports.CONTENT_TYPES.get(
                run.report_format, "application/octet-stream"
            ),
        )
        response["Content-Disposition"] = f'attachment; filename="{run.filename}"'
        return response
