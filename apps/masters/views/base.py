"""Generic, registry-driven CRUD views for master data."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.db.models import ProtectedError
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..registry import MASTER_BY_SLUG, MasterSpec


def resolve_value(obj: Any, accessor: str | callable) -> Any:
    """Resolve a column accessor (callable or dotted attribute path) for ``obj``."""
    if callable(accessor):
        return accessor(obj)
    value = obj
    for part in str(accessor).split("."):
        value = getattr(value, part, "")
    return value


def build_records(spec: MasterSpec, objects) -> list[dict[str, Any]]:
    """Pair each object with its rendered cells for the list template."""
    return [
        {
            "obj": obj,
            "cells": [resolve_value(obj, acc) for _, acc in spec.columns],
        }
        for obj in objects
    ]


class MasterSpecMixin(IHMSLoginRequiredMixin):
    """Resolve the :class:`MasterSpec` from the ``slug`` URL kwarg."""

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.spec = MASTER_BY_SLUG.get(kwargs.get("slug", ""))
        if self.spec is None:
            raise Http404("Unknown master type")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["spec"] = self.spec
        context["master_group"] = self.spec.group
        return context


class MasterListView(MasterSpecMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "masters/master_list.html"
    context_object_name = "objects"
    paginate_by = 20

    def get_permission_required(self):
        return (self.spec.view_perm,)

    def get_queryset(self):
        status = self.request.GET.get("status")
        is_active = None
        if status == "active":
            is_active = True
        elif status == "inactive":
            is_active = False
        return selectors.master_queryset(
            self.spec,
            search=self.request.GET.get("q") or None,
            is_active=is_active,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["columns"] = [header for header, _ in self.spec.columns]
        context["records"] = build_records(self.spec, context["objects"])
        context["search"] = self.request.GET.get("q", "")
        context["status"] = self.request.GET.get("status", "")
        context["page_title"] = self.spec.label_plural
        context["can_add"] = self.request.user.has_perm(self.spec.add_perm)
        return context


class MasterCreateView(MasterSpecMixin, IHMSPermissionRequiredMixin, CreateView):
    template_name = "masters/master_form.html"

    def get_permission_required(self):
        return (self.spec.add_perm,)

    def get_form_class(self):
        return self.spec.form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("New %(label)s") % {"label": self.spec.label}
        context["is_create"] = True
        return context

    def form_valid(self, form):
        self.object = services.create_master(
            model=self.spec.model,
            data=form.cleaned_data,
            actor=self.request.user,
            request=self.request,
        )
        messages.success(self.request, _("Created successfully."))
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("masters:master_list", args=[self.spec.slug])


class MasterUpdateView(MasterSpecMixin, IHMSPermissionRequiredMixin, UpdateView):
    template_name = "masters/master_form.html"

    def get_permission_required(self):
        return (
            f"{self.spec.model._meta.app_label}.change_{self.spec.model._meta.model_name}",
        )

    def get_form_class(self):
        return self.spec.form

    def get_queryset(self):
        return self.spec.model.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Edit %(label)s") % {"label": self.spec.label}
        context["is_create"] = False
        return context

    def form_valid(self, form):
        self.object = services.update_master(
            instance=form.instance,
            data=form.cleaned_data,
            actor=self.request.user,
            request=self.request,
        )
        messages.success(self.request, _("Updated successfully."))
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("masters:master_list", args=[self.spec.slug])


class MasterDeleteView(MasterSpecMixin, IHMSPermissionRequiredMixin, DeleteView):
    template_name = "masters/master_confirm_delete.html"

    def get_permission_required(self):
        return (
            f"{self.spec.model._meta.app_label}.delete_{self.spec.model._meta.model_name}",
        )

    def get_queryset(self):
        return self.spec.model.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Delete %(label)s") % {"label": self.spec.label}
        return context

    def form_valid(self, form):
        try:
            services.delete_master(
                instance=self.get_object(),
                actor=self.request.user,
                request=self.request,
            )
            messages.success(self.request, _("Deleted successfully."))
        except ProtectedError:
            messages.error(
                self.request,
                _(
                    "This record is in use and cannot be deleted. Deactivate it instead."
                ),
            )
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("masters:master_list", args=[self.spec.slug])


class MasterToggleActiveView(MasterSpecMixin, IHMSPermissionRequiredMixin, View):
    """POST-only toggle of the ``is_active`` flag."""

    http_method_names = ["post"]

    def get_permission_required(self):
        return (
            f"{self.spec.model._meta.app_label}.change_{self.spec.model._meta.model_name}",
        )

    def post(self, request, *args, **kwargs):
        instance = get_object_or_404(self.spec.model, pk=kwargs["pk"])
        services.toggle_master_active(
            instance=instance, actor=request.user, request=request
        )
        state = _("activated") if instance.is_active else _("deactivated")
        messages.success(request, _("Record %(state)s.") % {"state": state})
        return redirect(reverse("masters:master_list", args=[self.spec.slug]))

    def get(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(["POST"])
