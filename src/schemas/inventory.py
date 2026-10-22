# src/schemas/inventory.py

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from src.models import MovementType
from .common import ORMModel
from .types import MoneyAmount, NonNegativeQuantity, Quantity


class StockReceipt(BaseModel):
    """stock arriving from a supplier"""
    model_config = ConfigDict(extra="forbid")

    quantity: Quantity
    supplier_id: int | None = None
    unit_cost: MoneyAmount | None = None     # becomes the product's last purchase cost
    note: str | None = Field(default=None, max_length=255)


class StockWastage(BaseModel):
    """expired / damaged / stolen stock being written off"""
    model_config = ConfigDict(extra="forbid")

    quantity: Quantity
    note: str = Field(min_length=1, max_length=255)    # a write-off always needs a reason


class StockTake(BaseModel):
    """the result of a physical count: the system adjusts itself to this number"""
    model_config = ConfigDict(extra="forbid")

    counted_quantity: NonNegativeQuantity
    note: str | None = Field(default=None, max_length=255)


class ReorderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reorder_level: NonNegativeQuantity
    reorder_quantity: Quantity | None = None


class InventoryOut(ORMModel):
    product_id: int
    quantity_on_hand: Decimal
    quantity_reserved: Decimal
    reorder_level: Decimal
    reorder_quantity: Decimal | None
    last_counted_at: datetime | None

    @computed_field
    @property
    def available(self) -> Decimal:
        return self.quantity_on_hand - self.quantity_reserved


class StockMovementOut(ORMModel):
    id: int
    product_id: int
    supplier_id: int | None
    performed_by: int | None
    movement_type: MovementType
    quantity_change: Decimal
    quantity_after: Decimal
    unit_cost: Decimal | None
    reference_type: str | None
    reference_id: str | None
    note: str | None
    created_at: datetime
