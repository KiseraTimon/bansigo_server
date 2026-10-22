# src/schemas/payment.py

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

from src.models import PaymentChannel, PaymentStatus, RefundStatus
from .common import ORMModel
from .types import IdempotencyKey, Phone, PositiveMoney


# customer side

class StkPushRequest(BaseModel):
    """ask M-Pesa to prompt a phone for an order's total"""
    model_config = ConfigDict(extra="forbid")

    idempotency_key: IdempotencyKey      # one per tap of 'Pay'; a retry returns the same attempt
    phone: Phone | None = None           # defaults to the account's phone


class PaymentOut(ORMModel):
    id: int
    order_id: int
    channel: PaymentChannel
    status: PaymentStatus
    amount: Decimal
    currency: str
    payer_phone: str | None
    provider_receipt: str | None
    result_description: str | None
    paid_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class CashPaymentIn(BaseModel):
    """a rider/cashier recording cash received"""
    model_config = ConfigDict(extra="forbid")

    amount: PositiveMoney


# Daraja STK callback (shape fixed by Safaricom; field names are theirs)

class StkCallbackItem(BaseModel):
    Name: str
    Value: str | int | float | None = None


class StkCallbackMetadata(BaseModel):
    Item: list[StkCallbackItem] = []


class StkCallbackBody(BaseModel):
    MerchantRequestID: str
    CheckoutRequestID: str
    ResultCode: int
    ResultDesc: str
    CallbackMetadata: StkCallbackMetadata | None = None     # only present on success

    def metadata(self) -> dict[str, Any]:
        """{'Amount': 350.0, 'MpesaReceiptNumber': 'ABC...', 'TransactionDate': 2026..., 'PhoneNumber': 2547...}"""
        if self.CallbackMetadata is None:
            return {}
        return {item.Name: item.Value for item in self.CallbackMetadata.Item}


class StkCallbackInner(BaseModel):
    stkCallback: StkCallbackBody


class StkCallbackEnvelope(BaseModel):
    Body: StkCallbackInner


# Daraja C2B (customer pays our till/paybill and quotes the order number)

class C2BNotification(BaseModel):
    model_config = ConfigDict(extra="allow")     # Safaricom adds fields over time

    TransactionType: str | None = None
    TransID: Annotated[str, StringConstraints(min_length=1, max_length=30)]
    TransTime: str                                # yyyyMMddHHmmss, East Africa Time
    TransAmount: Decimal
    BusinessShortCode: str | None = None
    BillRefNumber: str = ""                       # what the customer typed as 'account': the order number
    MSISDN: str | None = None                     # hashed on newer Daraja versions
    FirstName: str | None = None


# what we answer Daraja with (it only needs to see a 200 + this body)

class DarajaAck(BaseModel):
    ResultCode: int = 0
    ResultDesc: str = "Accepted"


class C2BAck(BaseModel):
    ResultCode: str = "0"                         # C2B validation codes are STRINGS ("C2B00011" ... "C2B00016")
    ResultDesc: str = "Accepted"


# refunds

class RefundRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: PositiveMoney | None = None           # omitted = whatever is still refundable
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


class RefundRejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


class RefundOut(ORMModel):
    id: int
    payment_id: int
    requested_by: int | None
    approved_by: int | None
    amount: Decimal
    reason: str
    status: RefundStatus
    provider_receipt: str | None
    result_description: str | None
    processed_at: datetime | None
    created_at: datetime
