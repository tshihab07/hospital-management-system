"""Staff profile screens (RULES Phase 5)."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors
from ..forms import StaffFilterForm, StaffForm
from ..models import LeaveBalance, Staff


class StaffListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "hr/staff_list.html"
    context_object_name = "staff_members"
    paginate_by = 20
    permission_required = "hr.view_staff"

    def get_queryset(self):
        self.filter_form = StaffFilterForm(self.request.GET or None)
        data = self.filter_form.cleaned_data if self.filter_form.is_valid() else {}
        return selectors.staff_list(
            search=data.get("q") or "",
            department=data.get("department") or None,
            designation=data.get("designation") or None,
            status=data.get("status") or "",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["page_title"] = _("Staff")
        return context


class StaffCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, CreateView):
    model = Staff
    form_class = StaffForm
    template_name = "hr/staff_form.html"
    permission_required = "hr.add_staff"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Add Staff")
        context["is_create"] = True
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("Staff member added."))
        return response

    def get_success_url(self):
        from django.urls import reverse

        return reverse("hr:staff_detail", args=[self.object.pk])


class StaffUpdateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, UpdateView):
    model = Staff
    form_class = StaffForm
    template_name = "hr/staff_form.html"
    permission_required = "hr.change_staff"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Edit Staff")
        context["is_create"] = False
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("Staff member updated."))
        return response

    def get_success_url(self):
        from django.urls import reverse

        return reverse("hr:staff_detail", args=[self.object.pk])


class StaffDetailView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView):
    model = Staff
    template_name = "hr/staff_detail.html"
    context_object_name = "member"
    permission_required = "hr.view_staff"

    def get_queryset(self):
        return Staff.objects.select_related("department", "designation", "shift")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = timezone.localdate().year
        context["page_title"] = self.object.display_name
        context["balances"] = LeaveBalance.objects.filter(
            staff=self.object, year=year
        ).select_related("leave_type")
        context["recent_attendance"] = self.object.attendance.order_by("-att_date")[:10]
        context["upcoming_duties"] = self.object.roster.filter(
            duty_date__gte=timezone.localdate()
        ).select_related("shift")[:10]
        return context
