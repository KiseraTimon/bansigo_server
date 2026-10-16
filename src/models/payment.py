# src/models/payment.py

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin, UTCDateTime, str_enum
from .types import BigIntPK, Money

if TYPE_CHECKING:
    from .order import Order


class PaymentChannel(enum.Enum):
    """
    enum mapping how the money moves
    """

    MPESA_STK = "mpesa_stk"    # prompts via Daraja API/Lipa na MPESA Online
    MPESA_C2B = "mpesa_c2b"    # customer pays our till/paybill themselves, quoting the order number
    CASH = "cash"              # cash on delivery / at pickup


class PaymentStatus(enum.Enum):
    """
    payment lifeline
    """

    INITIATED = "initiated"
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"          # wrong PIN, insufficient funds, ...
    CANCELLED = "cancelled"    # dismissed prompts (Daraja code 1032)
    TIMEOUT = "timeout"        # (Daraja code 1037)


class Payment(Base, TimestampMixin):
    """
    schematic properties for one attempt to pay one order
    """

    __tablename__ = "payments"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign keys
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False)
    initiated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # what
    channel: Mapped[PaymentChannel] = mapped_column(str_enum(PaymentChannel), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(str_enum(PaymentStatus), nullable=False, default=PaymentStatus.INITIATED)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KES", server_default="KES")

    #idempotent key for the transaction
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # payer's details
    payer_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # provider identifiers
    provider_merchant_request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    provider_checkout_request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    provider_receipt: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, unique=True)

    # outcome
    result_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result_description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)      # the provider's transaction time
    expires_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)   # for polling Daraja's status query instead of waiting

    # relationships
    order: Mapped["Order"] = relationship(back_populates="payments", lazy="raise")
    events: Mapped[list["PaymentEvent"]] = relationship(back_populates="payment", lazy="raise")
    refunds: Mapped[list["Refund"]] = relationship(back_populates="payment", lazy="raise")

    # constraints + indexes
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        Index("idx_payment_order_status", "order_id", "status"),
        Index("idx_payment_status_expiry", "status", "expires_at"),    # a sweeper that resolves stuck PENDING payments
    )


class PaymentEventSource(enum.Enum):
    STK_CALLBACK = "stk_callback"                  # result of an STK push
    C2B_VALIDATION = "c2b_validation"
    C2B_CONFIRMATION = "c2b_confirmation"          # a till/paybill payment completed
    B2C_RESULT = "b2c_result"                      # outcome of a payout/refund we sent
    REVERSAL_RESULT = "reversal_result"            # outcome of a reversal we asked for


class PaymentEvent(Base):
    """
    schematic properties of Safaricom-sourced data
    """

    __tablename__ = "payment_events"

    # primary key
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)

    # foreign key
    payment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), nullable=True)

    # what arrived
    source: Mapped[PaymentEventSource] = mapped_column(str_enum(PaymentEventSource, length=24), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)    # CheckoutRequestID / TransID / ConversationID
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)    # the body, verbatim
    source_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    # truth fields
    is_authentic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    # processing result
    processed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    processing_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    received_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())

    # relationships
    payment: Mapped[Optional["Payment"]] = relationship(back_populates="events", lazy="raise")

    # constraints + indexes. Using a unique pair as a quality check that makes replayed callbacks harmless
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_payment_event_source_external"),
        Index("idx_payment_event_payment", "payment_id"),
        Index("idx_payment_event_unprocessed", "processed_at"),
    )


class RefundStatus(enum.Enum):
    REQUESTED = "requested"
    APPROVED = "approved"
    PROCESSING = "processing"    # sent to M-Pesa, waiting for the result
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class Refund(Base, TimestampMixin):
    """
    schematic attributes for money going back to a customer i.e.
    cancelled order, out-of-stock item, weighed-goods difference
    """

    __tablename__ = "refunds"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign keys
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False)
    requested_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)

    # the refund
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[RefundStatus] = mapped_column(str_enum(RefundStatus), nullable=False, default=RefundStatus.REQUESTED)

    # provider side
    provider_conversation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    provider_receipt: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, unique=True)
    result_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result_description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    # relationships
    payment: Mapped["Payment"] = relationship(back_populates="refunds", lazy="raise")

    # constraints
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_refund_amount_positive"),
        CheckConstraint("approved_by IS NULL OR approved_by <> requested_by", name="ck_refund_maker_checker"),
        Index("idx_refund_payment", "payment_id"),
    )
