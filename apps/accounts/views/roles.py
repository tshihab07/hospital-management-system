"""Role & permission management views (admins only)."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import RoleForm
from ..models import Role


class RoleListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    """List all roles with their permission counts."""

    model = Role
    template_name = "accounts/role_list.html"
    context_object_name = "roles"
    permission_required = "accounts.view_role"

    def get_queryset(self):
        return selectors.role_list(search=self.request.GET.get("q") or None)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Roles & Permissions"
        context["search"] = self.request.GET.get("q", "")
        return context


class RoleCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, CreateView):
    """Create a role and assign permissions."""

    model = Role
    form_class = RoleForm
    template_name = "accounts/role_form.html"
    success_url = reverse_lazy("accounts:role_list")
    permission_required = "accounts.add_role"

    def form_valid(self, form):
        self.object = services.create_role(
            data={
                "name": form.cleaned_data["name"],
                "description": form.cleaned_data["description"],
            },
            permissions=form.cleaned_data["permissions"],
            actor=self.request.user,
            request=self.request,
        )
        messages.success(self.request, f"Role '{self.object.name}' created.")
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Add role"
        context["is_create"] = True
        context["permission_catalog"] = selectors.permission_catalog()
        context["selected_perms"] = set()
        return context


class RoleUpdateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, UpdateView):
    """Rename a role and adjust its permission grants."""

    model = Role
    form_class = RoleForm
    template_name = "accounts/role_form.html"
    success_url = reverse_lazy("accounts:role_list")
    permission_required = "accounts.change_role"

    def form_valid(self, form):
        self.object = services.update_role(
            role=form.instance,
            data={
                "name": form.cleaned_data["name"],
                "description": form.cleaned_data["description"],
            },
            permissions=form.cleaned_data["permissions"],
            actor=self.request.user,
            request=self.request,
        )
        messages.success(self.request, f"Role '{self.object.name}' updated.")
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Edit {self.object.name}"
        context["is_create"] = False
        context["permission_catalog"] = selectors.permission_catalog()
        context["selected_perms"] = set(
            self.object.permissions.values_list("id", flat=True)
        )
        return context


class RoleDetailView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView):
    """Show a role's permissions and members."""

    model = Role
    template_name = "accounts/role_detail.html"
    context_object_name = "role"
    permission_required = "accounts.view_role"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.object.name
        context["members"] = self.object.users.order_by("username")
        context["permission_catalog"] = selectors.permission_catalog()
        context["selected_perms"] = set(
            self.object.permissions.values_list("id", flat=True)
        )
        return context


class RoleDeleteView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DeleteView):
    """Delete a non-system role after confirmation."""

    model = Role
    template_name = "accounts/role_confirm_delete.html"
    success_url = reverse_lazy("accounts:role_list")
    permission_required = "accounts.delete_role"

    def form_valid(self, form):
        role = self.get_object()
        try:
            services.delete_role(
                role=role, actor=self.request.user, request=self.request
            )
            messages.success(self.request, f"Role '{role.name}' deleted.")
        except ValueError as exc:
            messages.error(self.request, str(exc))
        return redirect(self.success_url)
