# src/routers/customer/delivery.py

from decimal import Decimal
from typing import Annotated
from fastapi import APIRouter, Depends, Query, status

from config import Settings
from src.dependencies import CurrentCustomer, SettingsDep, get_delivery_service
from src.schemas import (
    CoverageCheckResponse,
    DeliveryEstimateRequest,
    DeliveryEstimateResponse,
    DeliveryTrackingOut,
    HandoverCodeOut,
)
from src.services import DeliveryService
from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["customer-delivery"])
DeliveryServiceDep = Annotated[DeliveryService, Depends(get_delivery_service)]


@router.post(
    "/delivery/estimate",
    response_model=DeliveryEstimateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get delivery route estimate and fee quote",
)
async def estimate_delivery_route(
    data: DeliveryEstimateRequest,
    service: DeliveryServiceDep,
) -> DeliveryEstimateResponse:
    """
    Computes road network routing from Bansi Mega Supermarket to target coordinates.
    Returns distance, travel time, dynamic fee, waypoints, and randomized engine choice.
    """
    quote = service.estimate_delivery(data.latitude, data.longitude)
    return DeliveryEstimateResponse(**quote)


@router.get(
    "/delivery/coverage",
    response_model=CoverageCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Check if a coordinate is within the 7km Bansi delivery radius",
)
async def check_delivery_coverage(
    lat: Annotated[float, Query(ge=-90, le=90, description="Destination latitude")],
    lon: Annotated[float, Query(ge=-180, le=180, description="Destination longitude")],
    settings: SettingsDep,
) -> CoverageCheckResponse:
    from src.algorithms.route_engines import get_router
    router = get_router()

    is_covered, dist_m = router.is_within_coverage(lat, lon)
    return CoverageCheckResponse(
        is_covered=is_covered,
        distance_to_store_m=round(dist_m, 1),
        max_radius_km=router.max_delivery_radius_km,
        supermarket_name=settings.supermarket_name,
        supermarket_coords={
            "latitude": float(settings.supermarket_latitude),
            "longitude": float(settings.supermarket_longitude),
        },
    )


@router.get(
    "/orders/{order_id}/tracking",
    response_model=DeliveryTrackingOut,
    status_code=status.HTTP_200_OK,
    summary="Real-time delivery tracking for customer order",
)
async def track_order_delivery(
    order_id: int,
    customer: CurrentCustomer,
    service: DeliveryServiceDep,
) -> DeliveryTrackingOut:
    """
    Returns live delivery lifecycle state, rider location, waypoints from Bansi Mega Supermarket,
    and the secure handover code if active.
    """
    tracking = await service.get_tracking_for_customer(customer, order_id)
    return DeliveryTrackingOut(**tracking)


@router.get(
    "/orders/{order_id}/handover-code",
    response_model=HandoverCodeOut,
    status_code=status.HTTP_200_OK,
    summary="Retrieve customer handover code for order receipt",
)
async def get_handover_code(
    order_id: int,
    customer: CurrentCustomer,
    service: DeliveryServiceDep,
) -> HandoverCodeOut:
    """
    Retrieves the customer's 4-digit handover PIN to confirm parcel receipt with the delivery rider.
    """
    ord_id, code = await service.handover_code_for(customer, order_id)
    return HandoverCodeOut(order_id=ord_id, handover_code=code)
