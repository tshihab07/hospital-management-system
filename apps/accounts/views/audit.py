"""Audit log browser views (admins only)."""

from __future__ import annotations

from django.views.generic import DetailView, ListView

from core.audit import AuditLog
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors
from ..forms import AuditFilterForm


class AuditLogListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    """Paginated, filterable audit trail."""

    model = AuditLog
    template_name = "accounts/audit_log.html"
    context_object_name = "entries"
    paginate_by = 50
    permission_required = "core.view_auditlog"

    def get_queryset(self):
        form = AuditFilterForm(self.request.GET or None)
        data = form.cleaned_data if form.is_valid() else {}
        return selectors.audit_log_list(
            action=data.get("action") or None,
            model_name=data.get("model_name") or None,
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            search=data.get("q") or None,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Audit Log"
        context["filter_form"] = AuditFilterForm(self.request.GET or None)
        return context


class AuditLogDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView
):
    """Full detail of a single audit entry."""

    model = AuditLog
    template_name = "accounts/audit_detail.html"
    context_object_name = "entry"
    permission_required = "core.view_auditlog"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Audit entry"
        return context
