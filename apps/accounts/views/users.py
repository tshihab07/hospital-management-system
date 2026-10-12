"""User administration views (admins only)."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views.generic.edit import FormView

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import AdminSetPasswordForm, UserCreateForm, UserFilterForm, UserUpdateForm
from ..models import User


class UserListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    """Paginated, filterable list of user accounts."""

    model = User
    template_name = "accounts/user_list.html"
    context_object_name = "users"
    paginate_by = 25
    permission_required = "accounts.view_user"

    def get_queryset(self):
        form = UserFilterForm(self.request.GET or None)
        data = form.cleaned_data if form.is_valid() else {}
        active = data.get("is_active")
        return selectors.user_list(
            search=data.get("q") or None,
            is_active=None if active in (None, "") else active == "1",
            role_id=data.get("role").pk if data.get("role") else None,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Users"
        context["filter_form"] = UserFilterForm(self.request.GET or None)
        return context


class UserCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, CreateView):
    """Create a new staff/portal user."""

    model = User
    form_class = UserCreateForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:user_list")
    permission_required = "accounts.add_user"

    def form_valid(self, form):
        self.object = services.create_user(
            data=form.cleaned_data,
            actor=self.request.user,
            request=self.request,
        )
        messages.success(self.request, f"User '{self.object.username}' created.")
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Add user"
        context["is_create"] = True
        return context


class UserUpdateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, UpdateView):
    """Edit an existing user's profile, status and roles."""

    model = User
    form_class = UserUpdateForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:user_list")
    permission_required = "accounts.change_user"

    def form_valid(self, form):
        self.object = services.update_user(
            user=form.instance,
            data=form.cleaned_data,
            actor=self.request.user,
            request=self.request,
        )
        messages.success(self.request, f"User '{self.object.username}' updated.")
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Edit {self.object.username}"
        context["is_create"] = False
        return context


class UserDetailView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView):
    """Read-only user profile with roles and recent activity."""

    model = User
    template_name = "accounts/user_detail.html"
    context_object_name = "account"
    permission_required = "accounts.view_user"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.object.username
        context["roles"] = self.object.roles.order_by("name")
        return context


class UserSetActiveView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Activate/deactivate a user (POST only)."""

    permission_required = "accounts.change_user"

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user.pk == request.user.pk:
            messages.error(request, "You cannot deactivate your own account.")
            return redirect("accounts:user_detail", pk=pk)
        services.set_user_active(
            user=user,
            is_active=not user.is_active,
            actor=request.user,
            request=request,
        )
        state = "activated" if user.is_active else "deactivated"
        messages.success(request, f"User '{user.username}' {state}.")
        return redirect("accounts:user_detail", pk=pk)


class UserSetPasswordView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, FormView
):
    """Force-set another user's password."""

    form_class = AdminSetPasswordForm
    template_name = "accounts/user_set_password.html"
    permission_required = "accounts.change_user"

    def get_target(self) -> User:
        return get_object_or_404(User, pk=self.kwargs["pk"])

    def form_valid(self, form):
        user = self.get_target()
        services.set_user_password(
            user=user,
            raw_password=form.cleaned_data["password1"],
            must_change=form.cleaned_data["must_change"],
            actor=self.request.user,
            request=self.request,
        )
        messages.success(self.request, f"Password set for '{user.username}'.")
        return redirect("accounts:user_detail", pk=user.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Set password"
        context["target"] = self.get_target()
        return context
