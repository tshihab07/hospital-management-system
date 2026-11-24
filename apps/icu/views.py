"""Views for the ICU / CCU & Emergency module (thin; logic in services)."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView, View
from django.views.generic.base import TemplateResponseMixin

from apps.ipd.models import Admission
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from . import selectors, services
from .forms import (CodeBlueForm, ConvertAdmissionForm, EmergencyFilterForm,
                    EmergencyStatusForm, HandoverForm, IcuRecordForm,
                    QuickRegistrationForm, ScoreForm, TriageForm)
from .models import CodeBlueAlert, CriticalAlert, EmergencyCase, HandoverNote


def _admission(pk):
    return get_object_or_404(
        Admission.objects.select_related("patient", "doctor", "bed__ward"), pk=pk
    )


# ---------------------------------------------------------------------------
# ICU charting
# ---------------------------------------------------------------------------
class IcuRecordListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "icu/record_list.html"
    context_object_name = "admissions"
    paginate_by = 25
    permission_required = "icu.view_icurecord"

    def get_queryset(self):
        self.search = self.request.GET.get("search", "")
        return selectors.icu_admissions(search=self.search)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("ICU / CCU")
        context["search"] = self.search
        context["kpis"] = selectors.icu_kpis()
        context["active_alerts"] = selectors.alerts(status="active")[:5]
        return context


class AdmissionChartsView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView
):
    template_name = "icu/admission_charts.html"
    context_object_name = "admission"
    permission_required = "icu.view_icurecord"

    def get_object(self, queryset=None):
        return _admission(self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        admission = self.object
        context["page_title"] = _("ICU chart — %(p)s") % {
            "p": admission.patient.display_name
        }
        context["records"] = selectors.charts_for(admission)
        context["alerts"] = selectors.alerts(admission=admission)
        context["scores"] = selectors.score_history(admission)
        return context


class IcuRecordCreateView(
    IHMSLoginRequiredMixin,
    IHMSPermissionRequiredMixin,
    TemplateResponseMixin,
    View,
):
    template_name = "icu/record_form.html"
    permission_required = "icu.add_icurecord"

    def get(self, request, *args, **kwargs):
        admission = _admission(self.kwargs["pk"])
        form = IcuRecordForm(initial={"recorded_at": None})
        return self.render_to_response(
            {"form": form, "admission": admission, "page_title": _("Chart ICU entry")}
        )

    def post(self, request, *args, **kwargs):
        admission = _admission(self.kwargs["pk"])
        form = IcuRecordForm(request.POST)
        if form.is_valid():
            record = services.create_icu_record(
                admission=admission,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
            if record.critical_findings:
                messages.warning(
                    request, _("Critical value(s) detected — alerts raised.")
                )
            messages.success(request, _("ICU entry charted."))
            return redirect("icu:admission_charts", pk=admission.pk)
        return self.render_to_response(
            {"form": form, "admission": admission, "page_title": _("Chart ICU entry")}
        )


class ScoreCreateView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "icu/score_form.html"
    permission_required = "icu.add_criticalscore"

    def get(self, request, *args, **kwargs):
        admission = _admission(self.kwargs["pk"])
        return self.render_to_response(
            {
                "form": ScoreForm(),
                "admission": admission,
                "page_title": _("Severity score"),
            }
        )

    def post(self, request, *args, **kwargs):
        admission = _admission(self.kwargs["pk"])
        form = ScoreForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            score_type = data.pop("score_type")
            services.record_score(
                admission=admission,
                score_type=score_type,
                data=data,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Score calculated."))
            return redirect("icu:admission_charts", pk=admission.pk)
        return self.render_to_response(
            {"form": form, "admission": admission, "page_title": _("Severity score")}
        )


class AlertListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "icu/alert_list.html"
    context_object_name = "alerts"
    paginate_by = 25
    permission_required = "icu.view_criticalalert"

    def get_queryset(self):
        self.status = self.request.GET.get("status", "")
        return selectors.alerts(status=self.status)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Critical alerts")
        context["status"] = self.status
        return context


class AlertActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "icu.change_criticalalert"
    action = "acknowledge"

    def post(self, request, *args, **kwargs):
        alert = get_object_or_404(CriticalAlert, pk=self.kwargs["pk"])
        if self.action == "resolve":
            services.resolve_alert(alert=alert, actor=request.user, request=request)
            messages.success(request, _("Alert resolved."))
        else:
            services.acknowledge_alert(alert=alert, actor=request.user, request=request)
            messages.success(request, _("Alert acknowledged."))
        return redirect(request.META.get("HTTP_REFERER", "icu:alert_list"))


# ---------------------------------------------------------------------------
# Emergency
# ---------------------------------------------------------------------------
class EmergencyListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "icu/emergency_list.html"
    context_object_name = "cases"
    paginate_by = 30
    permission_required = "icu.view_emergencycase"

    def get_queryset(self):
        self.filter_form = EmergencyFilterForm(self.request.GET or None)
        data = self.filter_form.cleaned_data if self.filter_form.is_valid() else {}
        return selectors.emergency_queue(
            status=data.get("status") or "",
            triage=data.get("triage") or "",
            search=data.get("search") or "",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["page_title"] = _("Emergency")
        context["kpis"] = selectors.emergency_kpis()
        context["active_code_blues"] = selectors.active_code_blue_count()
        return context


class EmergencyRegisterView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "icu/emergency_register.html"
    permission_required = "icu.add_emergencycase"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {"form": QuickRegistrationForm(), "page_title": _("Register ER case")}
        )

    def post(self, request, *args, **kwargs):
        form = QuickRegistrationForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                case = services.quick_register_and_open_case(
                    patient_data={
                        "full_name_en": data["full_name_en"],
                        "phone": data["phone"],
                        "gender": data["gender"],
                        "age_years": data.get("age_years"),
                        "date_of_birth": data.get("date_of_birth"),
                    },
                    complaint=data["complaint"],
                    triage_level=data["triage_level"],
                    attending_doctor=data.get("attending_doctor"),
                    actor=request.user,
                    request=request,
                )
            except Exception as exc:  # surface validation errors to the user
                form.add_error(None, str(exc))
            else:
                messages.success(
                    request, _("ER case %(no)s registered.") % {"no": case.case_no}
                )
                return redirect("icu:emergency_detail", pk=case.pk)
        return self.render_to_response(
            {"form": form, "page_title": _("Register ER case")}
        )


class EmergencyDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView
):
    template_name = "icu/emergency_detail.html"
    context_object_name = "case"
    permission_required = "icu.view_emergencycase"

    def get_object(self, queryset=None):
        return get_object_or_404(
            EmergencyCase.objects.select_related(
                "patient", "attending_doctor", "converted_admission"
            ),
            pk=self.kwargs["pk"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("ER case %(p)s") % {
            "p": self.object.case_no or self.object.pk
        }
        context["triage_form"] = TriageForm(
            initial={"triage_level": self.object.triage_level}
        )
        context["status_form"] = EmergencyStatusForm(
            initial={"status": self.object.status}
        )
        context["code_blues"] = selectors.code_blues()
        context["handovers"] = selectors.handover_notes(unit="er")
        return context


class EmergencyTriageView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "icu.change_emergencycase"

    def post(self, request, *args, **kwargs):
        case = get_object_or_404(EmergencyCase, pk=self.kwargs["pk"])
        form = TriageForm(request.POST)
        if form.is_valid():
            services.set_triage(
                case=case,
                triage_level=form.cleaned_data["triage_level"],
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Triage updated."))
        return redirect("icu:emergency_detail", pk=case.pk)


class EmergencyStatusView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "icu.change_emergencycase"

    def post(self, request, *args, **kwargs):
        case = get_object_or_404(EmergencyCase, pk=self.kwargs["pk"])
        form = EmergencyStatusForm(request.POST)
        if form.is_valid():
            services.set_emergency_status(
                case=case,
                status=form.cleaned_data["status"],
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Status updated."))
        return redirect("icu:emergency_detail", pk=case.pk)


class EmergencyConvertView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "icu/emergency_convert.html"
    permission_required = "icu.change_emergencycase"

    def get(self, request, *args, **kwargs):
        case = get_object_or_404(EmergencyCase, pk=self.kwargs["pk"])
        return self.render_to_response(
            {
                "form": ConvertAdmissionForm(),
                "case": case,
                "page_title": _("Convert to admission"),
            }
        )

    def post(self, request, *args, **kwargs):
        case = get_object_or_404(EmergencyCase, pk=self.kwargs["pk"])
        form = ConvertAdmissionForm(request.POST)
        if form.is_valid():
            try:
                services.convert_to_admission(
                    case=case,
                    doctor=form.cleaned_data["doctor"],
                    reason=form.cleaned_data.get("reason", ""),
                    actor=request.user,
                    request=request,
                )
            except Exception as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, _("Admission advice raised."))
                return redirect("icu:emergency_detail", pk=case.pk)
        return self.render_to_response(
            {"form": form, "case": case, "page_title": _("Convert to admission")}
        )


class EmergencyDischargeView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "icu.change_emergencycase"

    def post(self, request, *args, **kwargs):
        case = get_object_or_404(EmergencyCase, pk=self.kwargs["pk"])
        services.quick_discharge(case=case, actor=request.user, request=request)
        messages.success(request, _("Case discharged. Complete billing in Billing."))
        return redirect("icu:emergency_detail", pk=case.pk)


# ---------------------------------------------------------------------------
# Code Blue
# ---------------------------------------------------------------------------
class CodeBlueListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "icu/code_blue_list.html"
    context_object_name = "code_blues"
    paginate_by = 25
    permission_required = "icu.view_codebluealert"

    def get_queryset(self):
        self.status = self.request.GET.get("status", "")
        return selectors.code_blues(status=self.status)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Code Blue")
        context["status"] = self.status
        return context


class CodeBlueRaiseView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "icu/code_blue_form.html"
    permission_required = "icu.add_codebluealert"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {"form": CodeBlueForm(), "page_title": _("Raise Code Blue")}
        )

    def post(self, request, *args, **kwargs):
        form = CodeBlueForm(request.POST)
        if form.is_valid():
            alert = services.raise_code_blue(
                location=form.cleaned_data["location"],
                notes=form.cleaned_data.get("notes", ""),
                actor=request.user,
                request=request,
            )
            messages.error(
                request,
                _("CODE BLUE activated — %(n)s staff notified.")
                % {"n": alert.notified_count},
            )
            return redirect("icu:code_blue_list")
        return self.render_to_response(
            {"form": form, "page_title": _("Raise Code Blue")}
        )


class CodeBlueResolveView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "icu.resolve_codebluealert"

    def post(self, request, *args, **kwargs):
        alert = get_object_or_404(CodeBlueAlert, pk=self.kwargs["pk"])
        services.resolve_code_blue(
            alert=alert,
            notes=request.POST.get("notes", ""),
            actor=request.user,
            request=request,
        )
        messages.success(request, _("Code Blue resolved."))
        return redirect(request.META.get("HTTP_REFERER", "icu:code_blue_list"))


# ---------------------------------------------------------------------------
# Shift handover
# ---------------------------------------------------------------------------
class HandoverListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "icu/handover_list.html"
    context_object_name = "notes"
    paginate_by = 25
    permission_required = "icu.view_handovernote"

    def get_queryset(self):
        self.unit = self.request.GET.get("unit", "")
        return selectors.handover_notes(unit=self.unit)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Shift handover")
        context["unit"] = self.unit
        return context


class HandoverCreateView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "icu/handover_form.html"
    permission_required = "icu.add_handovernote"

    def _context(self, form):
        return {"form": form, "page_title": _("Handover note")}

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self._context(HandoverForm()))

    def post(self, request, *args, **kwargs):
        form = HandoverForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.record_handover(
                unit=data["unit"],
                shift=data["shift"],
                summary=data["summary"],
                pending_tasks=data.get("pending_tasks", ""),
                handover_to=data.get("handover_to"),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Handover note recorded."))
            return redirect("icu:handover_list")
        return self.render_to_response(self._context(form))


class HandoverAcknowledgeView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View
):
    permission_required = "icu.change_handovernote"

    def post(self, request, *args, **kwargs):
        note = get_object_or_404(HandoverNote, pk=self.kwargs["pk"])
        services.acknowledge_handover(note=note, actor=request.user, request=request)
        messages.success(request, _("Handover acknowledged."))
        return redirect(request.META.get("HTTP_REFERER", "icu:handover_list"))
