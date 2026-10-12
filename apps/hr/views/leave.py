"""Leave types, requests and the approval workflow."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, ListView, View
from django.views.generic.base import TemplateResponseMixin

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import LeaveFilterForm, LeaveRequestForm, LeaveTypeForm
from ..models import LeaveRequest, LeaveType


class LeaveTypeListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    model = LeaveType
    template_name = "hr/leave_type_list.html"
    context_object_name = "leave_types"
    permission_required = "hr.view_leavetype"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Leave Types")
        return context


class LeaveTypeCreateView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, CreateView
):
    model = LeaveType
    form_class = LeaveTypeForm
    template_name = "hr/leave_type_form.html"
    permission_required = "hr.add_leavetype"
    success_url = "/hr/leave-types/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Add Leave Type")
        context["is_create"] = True
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("Leave type added."))
        return response


class LeaveListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "hr/leave_list.html"
    context_object_name = "leaves"
    paginate_by = 30
    permission_required = "hr.view_leaverequest"

    def get_queryset(self):
        self.filter_form = LeaveFilterForm(self.request.GET or None)
        data = self.filter_form.cleaned_data if self.filter_form.is_valid() else {}
        return selectors.leave_list(
            status=data.get("status") or "", staff=data.get("staff") or None
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["page_title"] = _("Leave Requests")
        context["pending_count"] = selectors.pending_leave_count()
        return context


class LeaveApplyView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, CreateView):
    """Apply for leave; creation goes through the service (overlap checks)."""

    model = LeaveRequest
    template_name = "hr/leave_form.html"
    form_class = LeaveRequestForm
    permission_required = "hr.add_leaverequest"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Apply for Leave")
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            leave = services.apply_leave(
                staff=data["staff"],
                leave_type=data["leave_type"],
                start_date=data["start_date"],
                end_date=data["end_date"],
                reason=data.get("reason", ""),
                actor=self.request.user,
                request=self.request,
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _("Leave request submitted."))
        return redirect("hr:leave_detail", pk=leave.pk)


class LeaveDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "hr/leave_detail.html"
    permission_required = "hr.view_leaverequest"

    def get(self, request, *args, **kwargs):
        leave = get_object_or_404(
            LeaveRequest.objects.select_related("staff", "leave_type", "decided_by"),
            pk=kwargs["pk"],
        )
        return self.render_to_response(
            {"page_title": _("Leave Request"), "leave": leave}
        )


class LeaveDecisionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "hr.change_leaverequest"

    def post(self, request, *args, **kwargs):
        leave = get_object_or_404(LeaveRequest, pk=kwargs["pk"])
        action = request.POST.get("action")
        note = request.POST.get("note", "")
        try:
            if action == "approve":
                services.approve_leave(
                    leave=leave, note=note, actor=request.user, request=request
                )
                messages.success(request, _("Leave approved."))
            elif action == "reject":
                services.reject_leave(
                    leave=leave, note=note, actor=request.user, request=request
                )
                messages.success(request, _("Leave rejected."))
            elif action == "cancel":
                services.cancel_leave(leave=leave, actor=request.user, request=request)
                messages.success(request, _("Leave cancelled."))
            else:
                messages.error(request, _("Unknown action."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("hr:leave_detail", pk=leave.pk)


class LeaveCancelView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "hr.change_leaverequest"

    def post(self, request, *args, **kwargs):
        leave = get_object_or_404(LeaveRequest, pk=kwargs["pk"])
        try:
            services.cancel_leave(leave=leave, actor=request.user, request=request)
            messages.success(request, _("Leave cancelled."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("hr:leave_detail", pk=leave.pk)
