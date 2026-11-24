"""Thin views for the Laboratory & Radiology module (RULES Phase 10).

Views validate input, delegate writes to :mod:`apps.lab.services`, reads to
:mod:`apps.lab.selectors`, then render a template or redirect.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.base import TemplateResponseMixin

from apps.emr.models import LabOrder, LabOrderItem
from apps.masters.models import HospitalProfile
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from . import selectors, services
from .forms import (AddendumForm, CollectSampleForm, LabOrderFilterForm,
                    RadiologyFilterForm, RadiologyReportForm,
                    RadiologyScheduleForm, RejectSampleForm, ReportRemarksForm,
                    ResultEntryForm, ResultFilterForm, SampleFilterForm)
from .models import LabResult, LabSample


def _order(pk) -> LabOrder:
    return get_object_or_404(
        LabOrder.objects.select_related("patient", "doctor"), pk=pk
    )


# ---------------------------------------------------------------------------
# Lab orders worklist
# ---------------------------------------------------------------------------
class LabOrderListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "lab/order_list.html"
    permission_required = "emr.view_laborder"

    def get(self, request, *args, **kwargs):
        data = request.GET
        orders = selectors.lab_order_list(
            q=data.get("q", ""),
            status=data.get("status", ""),
            priority=data.get("priority", ""),
        )
        return self.render_to_response(
            {
                "page_title": _("Laboratory · Orders"),
                "orders": orders,
                "dashboard": selectors.lab_dashboard(),
                "filters": LabOrderFilterForm(initial=data),
            }
        )


class LabOrderDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "lab/order_detail.html"
    permission_required = "emr.view_laborder"

    def get(self, request, *args, **kwargs):
        order = _order(kwargs["pk"])
        return self.render_to_response(
            {
                "page_title": _("Lab order #%(pk)s") % {"pk": order.pk},
                "order": order,
                "sample": getattr(order, "sample", None),
                "results": selectors.results_for_order(order=order),
                "report": getattr(order, "report", None),
                "charges": selectors.charges_for_order(order=order),
                "collect_form": CollectSampleForm(),
                "reject_form": RejectSampleForm(),
            }
        )


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------
class SampleListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "lab/sample_list.html"
    permission_required = "lab.view_labsample"

    def get(self, request, *args, **kwargs):
        data = request.GET
        return self.render_to_response(
            {
                "page_title": _("Laboratory · Samples"),
                "samples": selectors.sample_list(
                    q=data.get("q", ""), status=data.get("status", "")
                ),
                "filters": SampleFilterForm(initial=data),
            }
        )


class SampleCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "lab.add_labsample"

    def post(self, request, *args, **kwargs):
        order = _order(kwargs["pk"])
        sample = services.ensure_sample(
            order=order, actor=request.user, request=request
        )
        messages.success(
            request, _("Sample barcode %(code)s created.") % {"code": sample.barcode}
        )
        return redirect("lab:order_detail", pk=order.pk)


class SampleActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Collect / receive / reject a sample."""

    permission_required = "lab.change_labsample"

    def post(self, request, *args, **kwargs):
        sample = get_object_or_404(
            LabSample.objects.select_related("order"), pk=kwargs["pk"]
        )
        action = kwargs["action"]
        try:
            if action == "collect":
                form = CollectSampleForm(request.POST)
                if form.is_valid() and form.cleaned_data.get("sample_type"):
                    sample.sample_type = form.cleaned_data["sample_type"]
                services.collect_sample(
                    sample=sample, actor=request.user, request=request
                )
                messages.success(request, _("Sample collected."))
            elif action == "receive":
                services.receive_sample(
                    sample=sample, actor=request.user, request=request
                )
                messages.success(request, _("Sample received for processing."))
            elif action == "reject":
                form = RejectSampleForm(request.POST)
                reason = form.cleaned_data["reason"] if form.is_valid() else ""
                services.reject_sample(
                    sample=sample, reason=reason, actor=request.user, request=request
                )
                messages.warning(request, _("Sample rejected."))
            else:
                messages.error(request, _("Unknown action."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("lab:order_detail", pk=sample.order_id)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
class ResultListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "lab/result_list.html"
    permission_required = "lab.view_labresult"

    def get(self, request, *args, **kwargs):
        data = request.GET
        return self.render_to_response(
            {
                "page_title": _("Laboratory · Results"),
                "results": selectors.result_list(
                    q=data.get("q", ""),
                    status=data.get("status", ""),
                    flagged=bool(data.get("flagged")),
                ),
                "filters": ResultFilterForm(initial=data),
            }
        )


class ResultEntryView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "lab.add_labresult"

    def get(self, request, *args, **kwargs):
        order = _order(kwargs["pk"])
        existing = {
            r.order_item_id: r for r in selectors.results_for_order(order=order)
        }
        rows = [
            {"item": item, "result": existing.get(item.id), "form": ResultEntryForm()}
            for item in order.items.select_related("test")
        ]
        return render(
            request,
            "lab/result_entry.html",
            {
                "page_title": _("Enter results · order #%(pk)s") % {"pk": order.pk},
                "order": order,
                "rows": rows,
            },
        )

    def post(self, request, *args, **kwargs):
        order = _order(kwargs["pk"])
        item = get_object_or_404(
            LabOrderItem.objects.select_related("test"),
            pk=request.POST.get("item_id"),
            order=order,
        )
        form = ResultEntryForm(request.POST)
        if form.is_valid():
            try:
                services.enter_result(
                    order_item=item,
                    value=form.cleaned_data["value"],
                    flag=form.cleaned_data.get("flag") or None,
                    remarks=form.cleaned_data.get("remarks", ""),
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Result saved."))
            except ValueError as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, _("Enter a result value."))
        return redirect("lab:result_entry", pk=order.pk)


class ResultVerifyView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "lab.verify_labresult"

    def post(self, request, *args, **kwargs):
        result = get_object_or_404(
            LabResult.objects.select_related("order"), pk=kwargs["pk"]
        )
        try:
            services.verify_result(result=result, actor=request.user, request=request)
            messages.success(request, _("Result verified."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("lab:order_detail", pk=result.order_id)


class ResultAddendumView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "lab.add_labresultaddendum"

    def post(self, request, *args, **kwargs):
        result = get_object_or_404(
            LabResult.objects.select_related("order"), pk=kwargs["pk"]
        )
        form = AddendumForm(request.POST)
        if form.is_valid():
            services.add_result_addendum(
                result=result,
                text=form.cleaned_data["text"],
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Addendum appended."))
        else:
            messages.error(request, _("Addendum text is required."))
        return redirect("lab:order_detail", pk=result.order_id)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class ReportDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "lab/report_detail.html"
    permission_required = "lab.view_labreport"

    def get(self, request, *args, **kwargs):
        order = _order(kwargs["pk"])
        report = getattr(order, "report", None)
        if report is None:
            messages.info(request, _("No report generated yet."))
            return redirect("lab:order_detail", pk=order.pk)
        return self.render_to_response(
            {
                "page_title": _("Lab report · %(no)s") % {"no": report.report_no},
                "order": order,
                "report": report,
                "results": selectors.results_for_order(order=order),
                "remarks_form": ReportRemarksForm(initial={"remarks": report.remarks}),
            }
        )


class ReportActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Verify / release a report and save remarks."""

    def get_permission_required(self):
        if self.kwargs["action"] == "release":
            return ("lab.release_labreport",)
        return ("lab.verify_labreport",)

    def post(self, request, *args, **kwargs):
        order = _order(kwargs["pk"])
        report = getattr(order, "report", None)
        if report is None:
            messages.error(request, _("Generate results and verify them first."))
            return redirect("lab:order_detail", pk=order.pk)
        action = kwargs["action"]
        form = ReportRemarksForm(request.POST)
        if form.is_valid():
            report.remarks = form.cleaned_data.get("remarks", "")
            report.save(update_fields=["remarks", "updated_at"])
        try:
            if action == "verify":
                services.verify_report(
                    report=report, actor=request.user, request=request
                )
                messages.success(request, _("Report verified."))
            elif action == "release":
                services.release_report(
                    report=report, actor=request.user, request=request
                )
                messages.success(request, _("Report released."))
            else:
                messages.error(request, _("Unknown action."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("lab:report_detail", pk=order.pk)


class ReportPdfView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "lab.view_labreport"

    def get(self, request, *args, **kwargs):
        order = _order(kwargs["pk"])
        report = getattr(order, "report", None)
        if report is None:
            messages.info(request, _("No report generated yet."))
            return redirect("lab:order_detail", pk=order.pk)
        try:
            from weasyprint import HTML
        except ImportError:  # pragma: no cover - defensive
            return redirect("lab:report_detail", pk=order.pk)
        context = {
            "order": order,
            "report": report,
            "results": selectors.results_for_order(order=order),
            "hospital": HospitalProfile.load(),
            "pdf_mode": True,
        }
        html = render_to_string("lab/report_pdf.html", context, request=request)
        pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        filename = f"report-{report.report_no}.pdf"
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response


# ---------------------------------------------------------------------------
# Radiology
# ---------------------------------------------------------------------------
class RadiologyListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "lab/radiology_list.html"
    permission_required = "lab.view_radiologyrecord"

    def get(self, request, *args, **kwargs):
        data = request.GET
        return self.render_to_response(
            {
                "page_title": _("Radiology · Orders"),
                "orders": selectors.radiology_order_list(
                    q=data.get("q", ""), status=data.get("status", "")
                ),
                "filters": RadiologyFilterForm(initial=data),
            }
        )


class RadiologyDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "lab/radiology_detail.html"
    permission_required = "lab.view_radiologyrecord"

    def get(self, request, *args, **kwargs):
        from apps.emr.models import RadiologyOrder

        order = get_object_or_404(
            RadiologyOrder.objects.select_related("patient", "doctor"), pk=kwargs["pk"]
        )
        record = getattr(order, "record", None)
        return self.render_to_response(
            {
                "page_title": _("Radiology order #%(pk)s") % {"pk": order.pk},
                "order": order,
                "record": record,
                "schedule_form": RadiologyScheduleForm(),
                "report_form": RadiologyReportForm(),
            }
        )


class RadiologyActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Ensure record / schedule / report / verify / release."""

    def get_permission_required(self):
        action = self.kwargs["action"]
        if action == "verify":
            return ("lab.verify_radiologyrecord",)
        return ("lab.change_radiologyrecord",)

    def post(self, request, *args, **kwargs):
        from apps.emr.models import RadiologyOrder

        order = get_object_or_404(RadiologyOrder, pk=kwargs["pk"])
        record = services.ensure_radiology_record(
            order=order, actor=request.user, request=request
        )
        action = kwargs["action"]
        try:
            if action == "schedule":
                form = RadiologyScheduleForm(request.POST)
                if not form.is_valid():
                    raise ValueError(_("Provide a valid date/time."))
                services.schedule_radiology(
                    record=record,
                    scheduled_at=form.cleaned_data["scheduled_at"],
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Radiology scheduled."))
            elif action == "report":
                form = RadiologyReportForm(request.POST, request.FILES)
                if not form.is_valid():
                    raise ValueError(_("Please review the report fields."))
                data = form.cleaned_data
                services.record_radiology_report(
                    record=record,
                    findings=data.get("findings", ""),
                    impression=data.get("impression", ""),
                    radiologist=data.get("radiologist"),
                    attachment=data.get("attachment"),
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Radiology report saved."))
            elif action == "verify":
                services.verify_radiology(
                    record=record, actor=request.user, request=request
                )
                messages.success(request, _("Radiology report verified."))
            elif action == "release":
                services.release_radiology(
                    record=record, actor=request.user, request=request
                )
                messages.success(request, _("Radiology report released."))
            else:
                messages.error(request, _("Unknown action."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("lab:radiology_detail", pk=order.pk)
