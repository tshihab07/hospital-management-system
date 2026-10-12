"""Doctor master + availability management (RULES Phase 4)."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, ListView, UpdateView, View
from django.views.generic.base import TemplateResponseMixin

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors
from ..forms import WEEKDAYS, AvailabilitySlotForm, DoctorForm
from ..models import AvailabilitySlot, Doctor


class DoctorListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "opd/doctor_list.html"
    context_object_name = "doctors"
    paginate_by = 20
    permission_required = "opd.view_doctor"

    def get_queryset(self):
        self.search = self.request.GET.get("q", "")
        return selectors.doctor_list(search=self.search)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Doctors")
        context["search"] = self.search
        return context


class DoctorCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, CreateView):
    model = Doctor
    form_class = DoctorForm
    template_name = "opd/doctor_form.html"
    permission_required = "opd.add_doctor"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Add Doctor")
        context["is_create"] = True
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("Doctor added."))
        return response

    def get_success_url(self):
        return reverse_doctor_availability(self.object.pk)


class DoctorUpdateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, UpdateView):
    model = Doctor
    form_class = DoctorForm
    template_name = "opd/doctor_form.html"
    permission_required = "opd.change_doctor"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Edit Doctor")
        context["is_create"] = False
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("Doctor updated."))
        return response

    def get_success_url(self):
        return reverse_doctor_availability(self.object.pk)


class DoctorAvailabilityView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    """List a doctor's weekly blocks and add new ones."""

    template_name = "opd/doctor_availability.html"
    permission_required = "opd.change_doctor"

    def get_doctor(self):
        return get_object_or_404(Doctor, pk=self.kwargs["pk"])

    def get_context(self, doctor, form=None):
        return {
            "page_title": _("Availability · %(doctor)s") % {"doctor": doctor.name_en},
            "doctor": doctor,
            "slots": selectors.doctor_slots(doctor),
            "form": form or AvailabilitySlotForm(doctor=doctor),
            "weekdays": WEEKDAYS,
        }

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self.get_context(self.get_doctor()))

    def post(self, request, *args, **kwargs):
        doctor = self.get_doctor()
        form = AvailabilitySlotForm(request.POST, doctor=doctor)
        if form.is_valid():
            form.save()
            messages.success(request, _("Availability block added."))
            return redirect("opd:doctor_availability", pk=doctor.pk)
        return self.render_to_response(self.get_context(doctor, form))


class AvailabilityToggleView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "opd.change_doctor"

    def post(self, request, *args, **kwargs):
        slot = get_object_or_404(AvailabilitySlot, pk=kwargs["pk"])
        slot.is_active = not slot.is_active
        slot.save(update_fields=["is_active", "updated_at"])
        messages.success(request, _("Availability block updated."))
        return redirect("opd:doctor_availability", pk=slot.doctor_id)


def reverse_doctor_availability(pk: int) -> str:
    from django.urls import reverse

    return reverse("opd:doctor_availability", kwargs={"pk": pk})
