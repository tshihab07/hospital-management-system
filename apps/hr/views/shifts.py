"""Shift template screens."""

from __future__ import annotations

from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, ListView, UpdateView

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from ..forms import ShiftForm
from ..models import Shift


class ShiftListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    model = Shift
    template_name = "hr/shift_list.html"
    context_object_name = "shifts"
    permission_required = "hr.view_shift"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Shift Templates")
        return context


class ShiftCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, CreateView):
    model = Shift
    form_class = ShiftForm
    template_name = "hr/shift_form.html"
    permission_required = "hr.add_shift"
    success_url = "/hr/shifts/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Add Shift")
        context["is_create"] = True
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("Shift added."))
        return response


class ShiftUpdateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, UpdateView):
    model = Shift
    form_class = ShiftForm
    template_name = "hr/shift_form.html"
    permission_required = "hr.change_shift"
    success_url = "/hr/shifts/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Edit Shift")
        context["is_create"] = False
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("Shift updated."))
        return response
