"""Online payment gateway abstraction for Billing (RULES Phase 12).

The hospital accepts Cash, Card, bKash, Nagad, Rocket and Bank Transfer. Live
acquirer credentials are not part of v1 (see ``docs/MISTAKES.md`` deferrals), so
the module ships a pluggable gateway interface with a **sandbox/mock provider**
that produces deterministic transaction ids end-to-end. Swapping in a real
SSLCommerz / bKash provider only requires implementing :class:`BaseGateway` and
registering it in :data:`_PROVIDERS`.

Only the mobile-wallet / card channels route through a gateway; cash and bank
transfer are captured directly by the cashier.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .models import PaymentMode

#: Channels that require an online gateway handshake.
GATEWAY_MODES = frozenset(
    {PaymentMode.CARD, PaymentMode.BKASH, PaymentMode.NAGAD, PaymentMode.ROCKET}
)


@dataclass(frozen=True)
class GatewayResult:
    """Outcome of a gateway ``initiate`` call."""

    provider: str
    txn_id: str
    gateway_ref: str
    redirect_url: str = ""
    status: str = "pending"


class GatewayError(Exception):
    """Raised when a gateway channel is misconfigured or unavailable."""


class BaseGateway:
    """Interface every payment provider must implement."""

    provider = "base"

    def initiate(self, *, bill, amount) -> GatewayResult:  # pragma: no cover
        raise NotImplementedError

    def confirm(self, *, txn_id: str, payload: dict | None = None) -> bool:
        return True


class MockGateway(BaseGateway):
    """Deterministic sandbox provider used in v1 (no external calls)."""

    provider = "sandbox"

    def __init__(self, channel: str):
        self.channel = channel

    def initiate(self, *, bill, amount) -> GatewayResult:
        token = uuid.uuid4().hex[:16]
        txn_id = f"{self.channel.upper()}-{bill.bill_no}-{token}"
        return GatewayResult(
            provider=f"{self.provider}:{self.channel}",
            txn_id=txn_id,
            gateway_ref=f"SANDBOX-{token}",
            redirect_url=f"/billing/gateway/confirm/?txn={txn_id}",
            status="pending",
        )


#: Provider registry keyed by :class:`PaymentMode` value.
_PROVIDERS: dict[str, type[BaseGateway]] = {
    PaymentMode.CARD: MockGateway,
    PaymentMode.BKASH: MockGateway,
    PaymentMode.NAGAD: MockGateway,
    PaymentMode.ROCKET: MockGateway,
}


def get_gateway(method: str) -> BaseGateway:
    """Return the gateway provider for ``method``.

    Cash / bank transfer do not need a gateway; calling here with such a method
    raises :class:`GatewayError` so the caller uses direct collection instead.
    """
    provider = _PROVIDERS.get(method)
    if provider is None:
        raise GatewayError(
            _("Channel '%(m)s' does not use an online gateway.") % {"m": method}
        )
    return provider(method)


def gateway_enabled() -> bool:
    """True when an online gateway is configured for this deployment."""
    return bool(settings.IHMS.get("PAYMENT_GATEWAY_ENABLED", True))


def confirm_status(success: bool) -> str:
    return "success" if success else "cancelled"
