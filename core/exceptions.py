"""Domain exceptions for IHMS.

All custom exceptions derive from :class:`IHMSException` so callers can catch a
single base type. Each exception carries a stable ``code`` used by the error
catalogue (``docs/error-codes.md``) and by API/serializer layers.
"""

from __future__ import annotations


class IHMSException(Exception):
    """Base class for every IHMS domain error."""

    code = "IHMS-0000"
    default_message = "An unexpected error occurred."

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        self.message = message or self.default_message
        if code:
            self.code = code
        super().__init__(self.message)


# -- Generic ---------------------------------------------------------------
class ValidationError(IHMSException):
    code = "IHMS-1001"
    default_message = "The provided data is invalid."


class NotFoundError(IHMSException):
    code = "IHMS-1002"
    default_message = "The requested record was not found."


class PermissionDeniedError(IHMSException):
    code = "IHMS-1003"
    default_message = "You do not have permission to perform this action."


class ImmutableRecordError(IHMSException):
    code = "IHMS-1004"
    default_message = "This record is locked and can no longer be modified."


class ConfigurationError(IHMSException):
    code = "IHMS-1005"
    default_message = "The system is not configured correctly."


# -- Patient ---------------------------------------------------------------
class DuplicatePatientError(IHMSException):
    code = "IHMS-2001"
    default_message = "A patient with similar details already exists."


class PatientHasDuesError(IHMSException):
    code = "IHMS-2002"
    default_message = "The patient has outstanding dues and cannot be discharged."


# -- Clinical --------------------------------------------------------------
class BedUnavailableError(IHMSException):
    code = "IHMS-3001"
    default_message = "The selected bed is not available."


class DischargeBlockedError(IHMSException):
    code = "IHMS-3002"
    default_message = "Discharge is blocked pending clearance."


class DrugInteractionError(IHMSException):
    code = "IHMS-3003"
    default_message = "A dangerous drug interaction was detected."


# -- Pharmacy --------------------------------------------------------------
class InsufficientStockError(IHMSException):
    code = "IHMS-4001"
    default_message = "Insufficient stock available."


class ExpiredBatchError(IHMSException):
    code = "IHMS-4002"
    default_message = "The selected batch has expired and cannot be dispensed."


# -- Billing / finance -----------------------------------------------------
class BillingError(IHMSException):
    code = "IHMS-5001"
    default_message = "A billing error occurred."


class PaymentError(IHMSException):
    code = "IHMS-5002"
    default_message = "The payment could not be processed."


class DiscountApprovalRequiredError(IHMSException):
    code = "IHMS-5003"
    default_message = "This discount exceeds the allowed threshold and needs approval."


class LedgerImbalanceError(IHMSException):
    code = "IHMS-5004"
    default_message = "The journal entry is not balanced."
