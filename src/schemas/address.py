# src/schemas/address.py

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .common import ORMModel
from .types import Latitude, Longitude, MoneyAmount, Phone

_Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
_Person = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
_Area = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


# delivery zones (admin-managed)

class DeliveryZoneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    delivery_fee: MoneyAmount = Decimal("0")
    min_order_amount: MoneyAmount = Decimal("0")
    estimated_minutes: int | None = Field(default=None, gt=0, le=1440)


class DeliveryZoneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    delivery_fee: MoneyAmount | None = None
    min_order_amount: MoneyAmount | None = None
    estimated_minutes: int | None = Field(default=None, gt=0, le=1440)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("no fields provided")
        for field in self.model_fields_set - {"estimated_minutes"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class DeliveryZoneOut(ORMModel):
    id: int
    name: str
    delivery_fee: Decimal
    min_order_amount: Decimal
    estimated_minutes: int | None
    is_active: bool


# customer addresses

class AddressCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: _Label = "Home"
    recipient_name: _Person
    recipient_phone: Phone
    zone_id: int
    area: _Area
    street_address: str | None = Field(default=None, max_length=200)
    landmark: str | None = Field(default=None, max_length=200)
    directions: str | None = Field(default=None, max_length=255)
    latitude: Latitude
    longitude: Longitude
    is_default: bool = False


class AddressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: _Label | None = None
    recipient_name: _Person | None = None
    recipient_phone: Phone | None = None
    zone_id: int | None = None
    area: _Area | None = None
    street_address: str | None = Field(default=None, max_length=200)
    landmark: str | None = Field(default=None, max_length=200)
    directions: str | None = Field(default=None, max_length=255)
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    is_default: bool | None = None

    @model_validator(mode="after")
    def _validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("no fields provided")

        nullable = {"street_address", "landmark", "directions"}
        for field in self.model_fields_set - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")

        # a pin is moved as a pair, never half
        if ("latitude" in self.model_fields_set) != ("longitude" in self.model_fields_set):
            raise ValueError("latitude and longitude must be sent together")
        return self


class AddressOut(ORMModel):
    id: int
    label: str
    recipient_name: str
    recipient_phone: str
    zone_id: int | None
    zone: DeliveryZoneOut | None
    area: str
    street_address: str | None
    landmark: str | None
    directions: str | None
    latitude: Decimal
    longitude: Decimal
    is_default: bool
    created_at: datetime
