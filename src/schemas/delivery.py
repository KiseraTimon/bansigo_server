# src/schemas/delivery.py

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from src.models import ApprovalStatus, DeliveryStatus, RiderStatus, VehicleType
from .common import ORMModel
from .types import Latitude, Longitude, PositiveMoney

_Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


# riders

class RiderApply(BaseModel):
    """a RIDER-role user completing their profile; it starts PENDING until an admin vets it"""
    model_config = ConfigDict(extra="forbid")

    national_id_number: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6,10}$")]
    vehicle_type: VehicleType = VehicleType.MOTORCYCLE
    vehicle_plate: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, max_length=15)] | None = None
    vehicle_description: str | None = Field(default=None, max_length=100)
    licence_number: Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)] | None = None
    licence_expiry: date | None = None

    @model_validator(mode="after")
    def _rules(self):
        if self.vehicle_type is not VehicleType.BICYCLE:
            if not self.vehicle_plate:
                raise ValueError("vehicle_plate is required for motorised vehicles")
            if not self.licence_number or self.licence_expiry is None:
                raise ValueError("licence_number and licence_expiry are required for motorised vehicles")
        return self


class RiderDecision(BaseModel):
    """admin's vetting outcome (reject / suspend need a reason)"""
    model_config = ConfigDict(extra="forbid")

    reason: _Reason | None = None


class RiderGoStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RiderStatus


class RiderLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: Latitude
    longitude: Longitude


class RiderOut(ORMModel):
    """what the rider sees about themselves"""
    id: int
    user_id: int
    approval_status: ApprovalStatus
    status: RiderStatus
    vehicle_type: VehicleType
    vehicle_plate: str | None
    vehicle_description: str | None
    licence_expiry: date | None
    rating_average: Decimal | None
    rating_count: int
    deliveries_completed: int
    last_seen_at: datetime | None


class RiderAdminOut(RiderOut):
    """admin view: adds the identity documents (never sent to customers or other riders)"""
    national_id_number: str | None
    licence_number: str | None
    approved_at: datetime | None
    approved_by: int | None


class RiderPublic(ORMModel):
    """what a customer sees once a rider is assigned to their order. Nothing identifying beyond what's needed"""
    id: int
    vehicle_type: VehicleType
    vehicle_plate: str | None
    rating_average: Decimal | None


# deliveries

class DeliveryAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rider_id: int


class DeliveryRespond(BaseModel):
    """the rider's answer to an offer"""
    model_config = ConfigDict(extra="forbid")

    accept: bool


class DeliveryComplete(BaseModel):
    """proof of delivery"""
    model_config = ConfigDict(extra="forbid")

    handover_code: Annotated[str, StringConstraints(pattern=r"^\d{4,8}$")]
    id_checked: bool = False                         # must be true when the order has age-restricted items
    proof_photo_url: str | None = Field(default=None, max_length=255)
    cash_collected: PositiveMoney | None = None      # required for cash-on-delivery orders


class DeliveryFail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: _Reason


class DeliveryOut(ORMModel):
    id: int
    order_id: int
    rider_id: int | None
    status: DeliveryStatus
    requires_id_check: bool
    rider_fee: Decimal
    assigned_at: datetime | None
    accepted_at: datetime | None
    picked_up_at: datetime | None
    arrived_at: datetime | None
    delivered_at: datetime | None
    failed_reason: str | None
    estimated_distance_m: int | None
    estimated_duration_s: int | None


class HandoverCodeOut(BaseModel):
    """shown to the CUSTOMER; they read it to the rider at the door"""
    order_id: int
    handover_code: str
