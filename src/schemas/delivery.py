# src/schemas/delivery.py

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

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
    id_card_front_url: str | None = Field(default=None, max_length=255)
    id_card_back_url: str | None = Field(default=None, max_length=255)
    vehicle_type: VehicleType = VehicleType.MOTORCYCLE
    vehicle_plate: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, max_length=15)] | None = None
    vehicle_description: str | None = Field(default=None, max_length=100)
    vehicle_proof_url: str | None = Field(default=None, max_length=255)
    licence_number: Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)] | None = None
    licence_expiry: date | None = None
    driving_licence_url: str | None = Field(default=None, max_length=255)

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
    vehicle_proof_url: str | None = None
    national_id_number: str | None = None
    id_card_front_url: str | None = None
    id_card_back_url: str | None = None
    licence_number: str | None = None
    licence_expiry: date | None
    driving_licence_url: str | None = None
    rating_average: Decimal | None
    rating_count: int
    deliveries_completed: int
    last_seen_at: datetime | None
    unjustified_rejections_count: int = 0
    total_rejections_count: int = 0
    overdue_deliveries_count: int = 0
    penalty_points: int = 0
    dispatch_cooldown_until: datetime | None = None


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
    reason_code: str | None = Field(default=None, max_length=50)
    reason_text: str | None = Field(default=None, max_length=255)


class DeliveryPickup(BaseModel):
    """store pickup verification using the pickup code sent to the rider"""
    model_config = ConfigDict(extra="forbid")

    pickup_code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{4,8}$")]


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
    routing_algorithm: str | None = None
    pickup_latitude: Decimal | None = None
    pickup_longitude: Decimal | None = None
    offer_expires_at: datetime | None = None
    pickup_due_at: datetime | None = None
    delivery_due_at: datetime | None = None
    is_overdue: bool = False
    needs_manual_assignment: bool = False
    manual_assignment_reason: str | None = None
    rejection_count: int = 0


class HandoverCodeOut(BaseModel):
    """shown to the CUSTOMER; they read it to the rider at the door"""
    order_id: int
    handover_code: str


# OpenStreetMap routing & tracking schemas

class DeliveryEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: Latitude
    longitude: Longitude
    address_id: int | None = None


class DeliveryEstimateResponse(BaseModel):
    is_deliverable: bool
    distance_m: int
    duration_s: int
    estimated_minutes: int
    delivery_fee: Decimal
    routing_algorithm: str
    supermarket_name: str
    supermarket_coords: dict[str, float]
    destination_coords: dict[str, float]
    waypoints: list[list[float]] = []


class CoverageCheckResponse(BaseModel):
    is_covered: bool
    distance_to_store_m: float
    max_radius_km: float
    supermarket_name: str
    supermarket_coords: dict[str, float]


class DeliveryTrackingOut(BaseModel):
    order_id: int
    order_number: str
    order_status: str | None = None
    delivery_id: int | None
    status: str
    is_delivered: bool
    is_overdue: bool = False
    routing_algorithm: str | None = None
    estimated_distance_m: int | None = None
    estimated_duration_s: int | None = None
    estimated_minutes: int | None = None
    offer_expires_at: datetime | None = None
    pickup_due_at: datetime | None = None
    delivery_due_at: datetime | None = None
    supermarket_location: dict[str, Any]
    delivery_location: dict[str, Any]
    rider: RiderPublic | None = None
    rider_location: dict[str, Any] | None = None
    route_waypoints: list[list[float]] = []
    handover_code: str | None = None


class RiderDeliveryDetailOut(BaseModel):
    delivery_id: int
    order_id: int
    order_number: str
    status: DeliveryStatus
    requires_id_check: bool
    rider_fee: Decimal
    pickup_location: dict[str, Any]
    dropoff_location: dict[str, Any]
    customer_note: str | None = None
    payment_method: str
    cash_to_collect: Decimal | None = None
    estimated_distance_m: int | None = None
    estimated_duration_s: int | None = None
    routing_algorithm: str | None = None
    route_waypoints: list[list[float]] = []
    offer_expires_at: datetime | None = None
    pickup_due_at: datetime | None = None
    delivery_due_at: datetime | None = None
    is_overdue: bool = False
    items_summary: list[str] = []


class RiderNavigationOut(BaseModel):
    delivery_id: int
    leg: str  # "to_supermarket" or "to_customer"
    destination_name: str
    distance_m: int
    duration_s: int
    estimated_minutes: int
    routing_algorithm: str
    steps: list[dict[str, Any]]
    waypoints: list[list[float]]


class RiderWalletTransactionOut(BaseModel):
    id: str
    order_number: str
    amount: Decimal
    type: str  # DELIVERY_EARNING, PAYOUT_WITHDRAWAL
    description: str
    timestamp: str
    distance_km: float | None = None
    status: str
    reference_code: str


class RiderWalletOut(BaseModel):
    total_earnings: Decimal
    available_balance: Decimal
    cod_cash_in_hand: Decimal
    today_earnings: Decimal
    weekly_earnings: Decimal
    completed_trips_count: int
    pending_payouts: Decimal
    average_trip_fee: Decimal
    total_distance_km: float
    transactions: list[RiderWalletTransactionOut] = []


class RiderWithdrawRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: PositiveMoney
    phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=9, max_length=20)]


class RiderWithdrawOut(BaseModel):
    id: int
    amount: Decimal
    phone: str
    reference_code: str
    status: str
    timestamp: str
    available_balance: Decimal
