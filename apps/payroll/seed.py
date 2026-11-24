"""Idempotent provisioning of payroll defaults (RULES Phase 14).

Seeds the singleton :class:`PayrollSetting` and the current NBR income-tax
grid. Re-running never duplicates rows and only fills gaps, so it is safe on
every deploy and after a Finance Act adds a new assessment year.
"""

from __future__ import annotations

from . import tax
from .models import PayrollSetting, TaxBracket, TaxCategory, TaxSlab


def _build_brackets(slab: TaxSlab, threshold) -> None:
    """Create the progressive bands: category threshold then general bands."""
    bands = [(threshold, 0, "Tax-free threshold")]
    bands += list(tax.BD_SLABS["general"][1:])
    for order, (band_amount, rate, label) in enumerate(bands):
        TaxBracket.objects.create(
            slab=slab,
            order=order,
            band_amount=band_amount,
            rate=rate,
            label=label,
        )


def seed_tax_slabs(
    *, assessment_year: str = tax.BD_ASSESSMENT_YEAR, source: str = tax.BD_SOURCE
) -> dict:
    """Create the current slabs for every taxpayer category (idempotent)."""
    created = 0
    existing = 0
    for category in TaxCategory.values:
        info = tax.BD_CATEGORY.get(category, tax.BD_CATEGORY["general"])
        slab, made = TaxSlab.objects.get_or_create(
            assessment_year=assessment_year,
            category=category,
            defaults={
                "tax_free_threshold": info["threshold"],
                "minimum_tax": info["minimum_tax"],
                "source": source,
                "is_active": True,
            },
        )
        if made:
            created += 1
            _build_brackets(slab, info["threshold"])
        else:
            existing += 1
            if not slab.brackets.exists():
                _build_brackets(slab, info["threshold"])
    return {"created": created, "existing": existing}


def seed_payroll_defaults() -> dict:
    """Provision settings + tax slabs. Returns a summary dict."""
    setting = PayrollSetting.load()
    result = seed_tax_slabs()
    result["setting_id"] = setting.pk
    return result
