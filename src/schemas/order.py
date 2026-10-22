# src/schemas/order.py

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from src.models import (
    FulfilmentType, OrderPaymentStatus, OrderStatus, PaymentMethod, PickStatus, TaxClass, UnitType,
)
from .common import ORMModel
from .types import IdempotencyKey, NonNegativeQuantity, Quantity


# checkout

class OrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int
    quantity: Quantity


class CheckoutRequest(BaseModel):
    """
    what the customer app sends to place an order.
    PRICES ARE NEVER ACCEPTED FROM THE CLIENT: the server reads them from the catalogue and snapshots them
    """
    model_config = ConfigDict(extra="forbid")

    # the app generates this once per checkout attempt (a UUID) so a retry after a dropped connection
    # returns the same order instead of creating a second one
    idempotency_key: IdempotencyKey
    items: Annotated[list[OrderLineIn], Field(min_length=1, max_length=100)]
    fulfilment_type: FulfilmentType = FulfilmentType.DELIVERY
    payment_method: PaymentMethod = PaymentMethod.MPESA
    address_id: int | None = None
    customer_note: str | None = Field(default=None, max_length=500)
    scheduled_for: datetime | None = None

    @model_validator(mode="after")
    def _rules(self):
        if self.fulfilment_type is FulfilmentType.DELIVERY and self.address_id is None:
            raise ValueError("address_id is required for delivery orders")

        if self.fulfilment_type is FulfilmentType.PICKUP and self.address_id is not None:
            raise ValueError("address_id must not be sent for pickup orders")

        ids = [line.product_id for line in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("each product may appear only once; adjust the quantity instead")

        # the UTCDateTime column refuses naive datetimes, so refuse them at the door
        if self.scheduled_for is not None and self.scheduled_for.tzinfo is None:
            raise ValueError("scheduled_for must include a timezone offset")
        return self


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


# order read models

class OrderItemOut(ORMModel):
    id: int
    product_id: int
    product_name: str
    sku: str
    unit: UnitType
    unit_price: Decimal
    tax_class: TaxClass
    tax_rate: Decimal
    quantity: Decimal
    quantity_picked: Decimal | None
    pick_status: PickStatus
    substitute_product_id: int | None
    line_total: Decimal
    final_line_total: Decimal | None


class StatusHistoryOut(ORMModel):
    from_status: OrderStatus | None
    to_status: OrderStatus
    note: str | None
    created_at: datetime


class OrderSummary(ORMModel):
    """one row of 'my orders' / the staff queue"""
    id: int
    order_number: str
    status: OrderStatus
    payment_status: OrderPaymentStatus
    payment_method: PaymentMethod
    fulfilment_type: FulfilmentType
    total: Decimal
    adjusted_total: Decimal | None
    created_at: datetime


class OrderDetail(OrderSummary):
    subtotal: Decimal
    delivery_fee: Decimal
    discount_total: Decimal
    rounding_adjustment: Decimal
    tax_total: Decimal

    delivery_recipient_name: str | None
    delivery_recipient_phone: str | None
    delivery_address_text: str | None
    delivery_latitude: Decimal | None
    delivery_longitude: Decimal | None

    customer_note: str | None
    scheduled_for: datetime | None
    confirmed_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None

    items: list[OrderItemOut]
    status_history: list[StatusHistoryOut]


# staff: picking + status

class PickItemIn(BaseModel):
    """what the picker found on the shelf for one order line"""
    model_config = ConfigDict(extra="forbid")

    pick_status: PickStatus
    quantity_picked: NonNegativeQuantity = Decimal("0")
    substitute_product_id: int | None = None

    @model_validator(mode="after")
    def _rules(self):
        s = self.pick_status
        if s is PickStatus.PENDING:
            raise ValueError("a line cannot be set back to pending")
        if s is PickStatus.OUT_OF_STOCK and self.quantity_picked != 0:
            raise ValueError("quantity_picked must be 0 when the item is out of stock")
        if s in (PickStatus.PICKED, PickStatus.SHORT, PickStatus.SUBSTITUTED) and self.quantity_picked <= 0:
            raise ValueError("quantity_picked must be greater than 0")
        if s is PickStatus.SUBSTITUTED and self.substitute_product_id is None:
            raise ValueError("substitute_product_id is required for a substitution")
        if s is not PickStatus.SUBSTITUTED and self.substitute_product_id is not None:
            raise ValueError("substitute_product_id is only valid for a substitution")
        return self


class StaffStatusChange(BaseModel):
    """manual forward moves by staff (preparing / ready / completed-for-pickup). Cancelling has its own endpoint"""
    model_config = ConfigDict(extra="forbid")

    to_status: OrderStatus
    note: str | None = Field(default=None, max_length=255)
