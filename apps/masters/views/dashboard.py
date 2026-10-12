"""Master-data landing page (control tower for configuration)."""

from __future__ import annotations

from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from core.mixins import IHMSLoginRequiredMixin

from ..registry import MASTER_GROUPS


class MastersHomeView(IHMSLoginRequiredMixin, TemplateView):
    template_name = "masters/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        groups = []
        for name, specs in MASTER_GROUPS.items():
            cards = []
            for spec in specs:
                if not user.has_perm(spec.view_perm):
                    continue
                cards.append(
                    {
                        "label": spec.label_plural,
                        "slug": spec.slug,
                        "icon": spec.icon,
                        "url": reverse("masters:master_list", args=[spec.slug]),
                        "count": spec.model.objects.count(),
                    }
                )
            if cards:
                groups.append({"name": name, "cards": cards})
        context["groups"] = groups
        context["page_title"] = _("Master Data")
        return context
