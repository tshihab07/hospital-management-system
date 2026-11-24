"""Bangladesh income-tax engine and current NBR defaults (RULES Phase 14).

Tax is computed on **annual taxable income** and prorated to the monthly
payroll. The grid is data-driven (``TaxSlab`` + ``TaxBracket``) so a Finance
Act change needs a new slab row, never a code change. :data:`BD_TAX_DEFAULTS`
carries the current assessment-year values used to seed a fresh install.

The engine is deliberately dependency-free (it never imports Django models) so
it can be unit-tested in isolation and reused by reports.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

TAX_QUANT = Decimal("0.01")


def money(value) -> Decimal:
    """Return a 2-dp ``Decimal`` (half-up)."""
    return Decimal(str(value or "0")).quantize(TAX_QUANT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Current NBR defaults (assessment year 2025-2026, income year 2024-2025)
# ---------------------------------------------------------------------------
# Each bracket is (band_width, rate_pct, label). ``None`` width = top band.
BD_SLABS: dict[str, list[tuple]] = {
    # Women & senior citizens (65+) and persons with disability have a higher
    # tax-free threshold; the progressive rates above it are identical.
    "general": [
        (Decimal("350000"), Decimal("0"), "First 350,000"),
        (Decimal("100000"), Decimal("5"), "Next 100,000"),
        (Decimal("400000"), Decimal("10"), "Next 400,000"),
        (Decimal("500000"), Decimal("15"), "Next 500,000"),
        (Decimal("500000"), Decimal("20"), "Next 500,000"),
        (Decimal("2000000"), Decimal("25"), "Next 2,000,000"),
        (None, Decimal("30"), "Rest"),
    ],
}

# Category -> (tax-free threshold, minimum tax). The general bracket grid is
# reused with the category's own threshold applied.
BD_CATEGORY: dict[str, dict] = {
    "general": {"threshold": Decimal("350000"), "minimum_tax": Decimal("5000")},
    "female_senior": {"threshold": Decimal("400000"), "minimum_tax": Decimal("5000")},
    "disabled": {"threshold": Decimal("475000"), "minimum_tax": Decimal("5000")},
    "freedom_fighter": {"threshold": Decimal("500000"), "minimum_tax": Decimal("5000")},
}

# The reference assessment year / source note used when seeding.
BD_ASSESSMENT_YEAR = "2025-2026"
BD_SOURCE = (
    "Income Tax Act 2023 / Finance Act 2024 – NBR individual slab (AY 2025-2026)"
)


def compute_tax(
    taxable_income,
    brackets,
    *,
    tax_free_threshold=Decimal("0"),
    minimum_tax=Decimal("0"),
) -> Decimal:
    """Return the annual tax for ``taxable_income`` given progressive brackets.

    Args:
        taxable_income: Annual taxable income (total income).
        brackets: Iterable of ``(band_width, rate_pct)`` pairs, ordered from the
            lowest band upward. A width of ``None`` marks the open-ended top
            band. Percentages are applied to the portion of income inside each
            band.
        tax_free_threshold: The nil-rated threshold; a taxpayer with income at
            or below it pays nothing (minimum tax not triggered).
        minimum_tax: Floor applied only when income exceeds the threshold.

    Returns:
        The annual tax rounded to two decimals.
    """
    income = money(taxable_income)
    if income <= 0:
        return Decimal("0.00")

    remaining = income
    tax = Decimal("0")
    for band_width, rate in brackets:
        if remaining <= 0:
            break
        width = None if band_width is None else money(band_width)
        portion = remaining if width is None else min(remaining, width)
        rate = Decimal(str(rate))
        if rate and portion > 0:
            tax += portion * rate / Decimal("100")
        remaining -= portion

    if income > money(tax_free_threshold):
        tax = max(tax, money(minimum_tax))
    return money(tax)


def monthly_tax(annual_tax, months: int = 12) -> Decimal:
    """Spread an annual tax figure across ``months`` (default 12)."""
    months = int(months or 1)
    if months <= 0:
        months = 1
    return money(Decimal(str(annual_tax)) / Decimal(months))


def taxable_income(
    annual_gross,
    *,
    annual_pf=Decimal("0"),
    standard_deduction=Decimal("0"),
) -> Decimal:
    """Taxable income = annual gross − PF contribution − standard deduction."""
    value = money(annual_gross) - money(annual_pf) - money(standard_deduction)
    return value if value > 0 else Decimal("0.00")


def standard_deduction(
    annual_gross, *, ratio=Decimal("0.3333"), cap=Decimal("300000")
) -> Decimal:
    """Lower of ``ratio × gross`` and the statutory ``cap``."""
    cap = money(cap)
    if cap <= 0:
        return Decimal("0.00")
    value = money(annual_gross) * Decimal(str(ratio))
    return money(min(value, cap))
