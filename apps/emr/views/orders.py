"""CPOE views: prescriptions (with print/PDF) and diagnostic/procedure orders."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView, View
from django.views.generic.base import TemplateResponseMixin

from apps.masters.models import HospitalProfile
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import (LabOrderForm, OrderStatusForm, PrescriptionFilterForm,
                     PrescriptionForm, PrescriptionItemFormSet,
                     ProcedureOrderForm, RadiologyOrderForm)
from ..models import (Encounter, LabOrder, Prescription, PrescriptionItem,
                      PrescriptionStatus, ProcedureOrder, RadiologyOrder,
                      Route)

ORDER_MODELS = {
    "lab": LabOrder,
    "radiology": RadiologyOrder,
    "procedure": ProcedureOrder,
}


def _interaction_text(interactions) -> str:
    parts = [
        _("%(a)s + %(b)s (%(sev)s)")
        % {"a": r.drug_a, "b": r.drug_b, "sev": r.get_severity_display()}
        for r in interactions
    ]
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Prescriptions
# ---------------------------------------------------------------------------
class PrescriptionCreateView(
    IHMSLoginRequiredMixin,
    IHMSPermissionRequiredMixin,
    TemplateResponseMixin,
    View,
):
    template_name = "emr/prescription_form.html"
    permission_required = "emr.add_prescription"

    def _encounter(self, pk):
        return get_object_or_404(
            Encounter.objects.select_related("patient", "doctor"), pk=pk
        )

    def _check_open(self, request, encounter):
        """Refuse new CPOE orders on a closed encounter."""
        if not encounter.is_open:
            messages.warning(
                request, _("This encounter is closed. Re-open it to place orders.")
            )
            return redirect("emr:encounter_detail", pk=encounter.pk)
        return None

    def _context(self, encounter, form, formset):
        return {
            "page_title": _("New Prescription"),
            "encounter": encounter,
            "form": form,
            "formset": formset,
        }

    def get(self, request, *args, **kwargs):
        encounter = self._encounter(kwargs["pk"])
        blocked = self._check_open(request, encounter)
        if blocked is not None:
            return blocked
        form = PrescriptionForm()
        formset = PrescriptionItemFormSet(queryset=PrescriptionItem.objects.none())
        return self.render_to_response(self._context(encounter, form, formset))

    def post(self, request, *args, **kwargs):
        encounter = self._encounter(kwargs["pk"])
        blocked = self._check_open(request, encounter)
        if blocked is not None:
            return blocked
        form = PrescriptionForm(request.POST)
        formset = PrescriptionItemFormSet(
            request.POST, queryset=PrescriptionItem.objects.none()
        )
        if form.is_valid() and formset.is_valid():
            items = []
            for item_form in formset.forms:
                data = item_form.cleaned_data
                if not data or data.get("DELETE") or not data.get("drug"):
                    continue
                items.append(
                    {
                        "drug": data["drug"],
                        "dose": data.get("dose", ""),
                        "route": data.get("route") or Route.ORAL,
                        "frequency": data.get("frequency", ""),
                        "duration_days": data.get("duration_days") or 1,
                        "quantity": data.get("quantity") or 1,
                        "is_prn": data.get("is_prn", False),
                        "instructions": data.get("instructions", ""),
                    }
                )
            if not items:
                messages.error(request, _("Add at least one drug line."))
                return self.render_to_response(self._context(encounter, form, formset))
            prescription, interactions = services.issue_prescription(
                encounter=encounter,
                items=items,
                notes=form.cleaned_data.get("notes", ""),
                actor=request.user,
                request=request,
            )
            messages.success(
                request,
                _("Prescription #%(pk)s issued.") % {"pk": prescription.pk},
            )
            if interactions:
                messages.warning(
                    request,
                    _("Drug interaction alert: %(list)s")
                    % {"list": _interaction_text(interactions)},
                )
            return redirect("emr:prescription_detail", pk=prescription.pk)
        messages.error(request, _("Please review the highlighted fields."))
        return self.render_to_response(self._context(encounter, form, formset))


class PrescriptionListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView
):
    template_name = "emr/prescription_list.html"
    context_object_name = "prescriptions"
    paginate_by = 30
    permission_required = "emr.view_prescription"

    def get_queryset(self):
        self.filter_form = PrescriptionFilterForm(self.request.GET or None)
        data = self.filter_form.cleaned_data if self.filter_form.is_valid() else {}
        return selectors.prescription_list(
            doctor=data.get("doctor") or None, search=data.get("q") or ""
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["page_title"] = _("Prescriptions")
        return context


class PrescriptionDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView
):
    model = Prescription
    template_name = "emr/prescription_detail.html"
    context_object_name = "prescription"
    permission_required = "emr.view_prescription"

    def get_queryset(self):
        return Prescription.objects.select_related(
            "patient", "doctor", "encounter"
        ).prefetch_related("items__drug")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Prescription #%(pk)s") % {"pk": self.object.pk}
        context["can_void"] = self.object.status == PrescriptionStatus.ISSUED
        return context


class PrescriptionCancelView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "emr.change_prescription"

    def post(self, request, *args, **kwargs):
        prescription = get_object_or_404(Prescription, pk=kwargs["pk"])
        services.cancel_prescription(
            instance=prescription, actor=request.user, request=request
        )
        messages.success(request, _("Prescription cancelled."))
        return redirect("emr:prescription_detail", pk=prescription.pk)


class PrescriptionPrintView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView
):
    model = Prescription
    template_name = "emr/prescription_print.html"
    context_object_name = "prescription"
    permission_required = "emr.view_prescription"

    def get_queryset(self):
        return Prescription.objects.select_related(
            "patient", "doctor", "encounter"
        ).prefetch_related("items__drug")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["hospital"] = HospitalProfile.load()
        context["pdf_mode"] = False
        return context


class PrescriptionPdfView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView
):
    model = Prescription
    context_object_name = "prescription"
    permission_required = "emr.view_prescription"

    def get_queryset(self):
        return Prescription.objects.select_related(
            "patient", "doctor", "encounter"
        ).prefetch_related("items__drug")

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            from weasyprint import HTML
        except ImportError:  # pragma: no cover - defensive
            messages.error(request, _("PDF generation is unavailable."))
            return redirect("emr:prescription_print", pk=self.object.pk)

        context = self.get_context_data(object=self.object)
        context["pdf_mode"] = True
        html = render_to_string(
            "emr/prescription_print.html",
            context,
            request=request,
        )
        pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="prescription-{self.object.pk}.pdf"'
        )
        return response


# ---------------------------------------------------------------------------
# Diagnostic & procedure orders
# ---------------------------------------------------------------------------
class _OrderCreateView(
    IHMSLoginRequiredMixin,
    IHMSPermissionRequiredMixin,
    TemplateResponseMixin,
    View,
):
    template_name = "emr/order_form.html"
    form_class = None
    kind = ""
    submit_label = ""

    def _encounter(self, pk):
        return get_object_or_404(
            Encounter.objects.select_related("patient", "doctor"), pk=pk
        )

    def _check_open(self, request, encounter):
        """Refuse new CPOE orders on a closed encounter."""
        if not encounter.is_open:
            messages.warning(
                request, _("This encounter is closed. Re-open it to place orders.")
            )
            return redirect("emr:encounter_detail", pk=encounter.pk)
        return None

    def _context(self, encounter, form):
        return {
            "page_title": self.title,
            "encounter": encounter,
            "form": form,
            "kind": self.kind,
            "submit_label": self.submit_label,
        }

    def get(self, request, *args, **kwargs):
        encounter = self._encounter(kwargs["pk"])
        blocked = self._check_open(request, encounter)
        if blocked is not None:
            return blocked
        return self.render_to_response(self._context(encounter, self.form_class()))

    def _save(self, encounter, data, request):
        raise NotImplementedError

    def post(self, request, *args, **kwargs):
        encounter = self._encounter(kwargs["pk"])
        blocked = self._check_open(request, encounter)
        if blocked is not None:
            return blocked
        form = self.form_class(request.POST)
        if form.is_valid():
            order = self._save(encounter, form.cleaned_data, request)
            messages.success(
                request,
                _("Order placed (#%(pk)s).") % {"pk": order.pk},
            )
            return redirect("emr:encounter_detail", pk=encounter.pk)
        messages.error(request, _("Please review the highlighted fields."))
        return self.render_to_response(self._context(encounter, form))


class LabOrderCreateView(_OrderCreateView):
    permission_required = "emr.add_laborder"
    form_class = LabOrderForm
    kind = "lab"
    title = _("New Lab Order")
    submit_label = _("Place lab order")

    def _save(self, encounter, data, request):
        return services.create_lab_order(
            encounter=encounter,
            tests=list(data["tests"]),
            priority=data.get("priority"),
            notes=data.get("notes", ""),
            actor=request.user,
            request=request,
        )


class RadiologyOrderCreateView(_OrderCreateView):
    permission_required = "emr.add_radiologyorder"
    form_class = RadiologyOrderForm
    kind = "radiology"
    title = _("New Radiology Order")
    submit_label = _("Place radiology order")

    def _save(self, encounter, data, request):
        return services.create_radiology_order(
            encounter=encounter,
            tests=list(data["tests"]),
            priority=data.get("priority"),
            clinical_indication=data.get("clinical_indication", ""),
            notes=data.get("notes", ""),
            actor=request.user,
            request=request,
        )


class ProcedureOrderCreateView(_OrderCreateView):
    permission_required = "emr.add_procedureorder"
    form_class = ProcedureOrderForm
    kind = "procedure"
    title = _("New Procedure Order")
    submit_label = _("Place procedure order")

    def _context(self, encounter, form):
        return {
            "page_title": self.title,
            "encounter": encounter,
            "form": form,
            "kind": None,
            "submit_label": self.submit_label,
        }

    def _save(self, encounter, data, request):
        return services.create_procedure_order(
            encounter=encounter,
            procedure=data["procedure"],
            priority=data.get("priority"),
            scheduled_for=data.get("scheduled_for"),
            notes=data.get("notes", ""),
            actor=request.user,
            request=request,
        )


class OrderStatusView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    def get_permission_required(self):
        model = ORDER_MODELS.get(self.kwargs.get("kind"))
        if model is None:
            return ()
        return (f"emr.change_{model._meta.model_name}",)

    def post(self, request, *args, **kwargs):
        model = ORDER_MODELS.get(kwargs["kind"])
        if model is None:
            messages.error(request, _("Unknown order type."))
            return redirect("emr:encounter_list")
        order = get_object_or_404(model, pk=kwargs["pk"])
        encounter_id = order.encounter_id
        form = OrderStatusForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("Unknown order status."))
            return redirect("emr:encounter_detail", pk=encounter_id)
        try:
            services.set_order_status(
                instance=order,
                status=form.cleaned_data["status"],
                actor=request.user,
                request=request,
            )
            messages.success(
                request,
                _("Order status changed to “%(status)s”.")
                % {"status": order.get_status_display()},
            )
        except (ValueError, KeyError) as exc:
            messages.error(request, str(exc))
        return redirect("emr:encounter_detail", pk=encounter_id)
