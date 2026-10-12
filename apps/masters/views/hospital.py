"""Singleton hospital profile screen."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import UpdateView

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import services
from ..forms import HospitalProfileForm
from ..models import HospitalProfile


class HospitalProfileView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, UpdateView
):
    model = HospitalProfile
    form_class = HospitalProfileForm
    template_name = "masters/hospital_profile.html"
    success_url = reverse_lazy("masters:hospital_profile")
    permission_required = "masters.change_hospitalprofile"

    def get_object(self, queryset=None):
        return HospitalProfile.load()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Hospital Profile")
        return context

    def form_valid(self, form):
        self.object = services.update_master(
            instance=form.instance,
            data=form.cleaned_data,
            actor=self.request.user,
            request=self.request,
        )
        messages.success(self.request, _("Hospital profile updated."))
        return redirect(self.get_success_url())
