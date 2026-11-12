# src/routers/rider/deliveries.py

from decimal import Decimal
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query, status

from src.dependencies import (
    CurrentUser,
    RiderUser,
    get_delivery_service,
    get_rider_service,
)
from src.schemas import (
    DeliveryComplete,
    DeliveryFail,
    DeliveryOut,
    DeliveryRespond,
    Detail,
    RiderApply,
    RiderDeliveryDetailOut,
    RiderGoStatus,
    RiderLocation,
    RiderNavigationOut,
    RiderOut,
)
from src.services import DeliveryService, RiderService
from utilities import get_logger


log = get_logger(__name__)

# routing object
router = APIRouter(tags=["rider-deliveries"])

# Dependencies
DeliveryServiceDep = Annotated[DeliveryService, Depends(get_delivery_service)]
RiderServiceDep = Annotated[RiderService, Depends(get_rider_service)]


# Profile & availability

@router.post(
    "/profile/apply",
    response_model=RiderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit rider application and vehicle documents",
)
async def apply_for_rider(
    data: RiderApply,
    user: CurrentUser,
    service: RiderServiceDep,
) -> RiderOut:
    rider = await service.apply(user, data)
    return RiderOut.model_validate(rider)


@router.get(
    "/profile",
    response_model=RiderOut,
    status_code=status.HTTP_200_OK,
    summary="Get current rider profile and vetting status",
)
async def get_rider_profile(
    user: RiderUser,
    service: RiderServiceDep,
) -> RiderOut:
    rider = await service.for_user(user)
    return RiderOut.model_validate(rider)


@router.post(
    "/availability",
    response_model=RiderOut,
    status_code=status.HTTP_200_OK,
    summary="Toggle rider availability (go online / offline)",
)
async def set_availability(
    data: RiderGoStatus,
    user: RiderUser,
    service: RiderServiceDep,
) -> RiderOut:
    rider = await service.set_availability(user, data)
    return RiderOut.model_validate(rider)


@router.post(
    "/location",
    response_model=Detail,
    status_code=status.HTTP_200_OK,
    summary="Ping rider GPS location coordinates",
)
async def update_location(
    data: RiderLocation,
    user: RiderUser,
    service: RiderServiceDep,
) -> Detail:
    await service.update_location(user, data)
    return Detail(detail="Location updated successfully")


# Delivery operations

@router.get(
    "/deliveries/active",
    response_model=list[DeliveryOut],
    status_code=status.HTTP_200_OK,
    summary="List active deliveries assigned to current rider",
)
async def get_active_deliveries(
    user: RiderUser,
    service: DeliveryServiceDep,
) -> list[DeliveryOut]:
    deliveries = await service.my_active(user)
    return [DeliveryOut.model_validate(d) for d in deliveries]


@router.get(
    "/deliveries/{delivery_id}",
    response_model=RiderDeliveryDetailOut,
    status_code=status.HTTP_200_OK,
    summary="Get full delivery details with pickup and customer dropoff",
)
async def get_delivery_details(
    delivery_id: int,
    user: RiderUser,
    service: DeliveryServiceDep,
) -> RiderDeliveryDetailOut:
    detail = await service.get_rider_delivery_detail(delivery_id, user)
    return RiderDeliveryDetailOut(**detail)


@router.post(
    "/deliveries/{delivery_id}/respond",
    response_model=DeliveryOut,
    status_code=status.HTTP_200_OK,
    summary="Accept or decline a delivery assignment offer",
)
async def respond_to_delivery_offer(
    delivery_id: int,
    data: DeliveryRespond,
    user: RiderUser,
    service: DeliveryServiceDep,
) -> DeliveryOut:
    delivery = await service.respond(delivery_id, user, data.accept)
    return DeliveryOut.model_validate(delivery)


@router.post(
    "/deliveries/{delivery_id}/pickup",
    response_model=DeliveryOut,
    status_code=status.HTTP_200_OK,
    summary="Mark parcel picked up at Bansi Mega Supermarket",
)
async def pickup_delivery(
    delivery_id: int,
    user: RiderUser,
    service: DeliveryServiceDep,
) -> DeliveryOut:
    delivery = await service.pick_up(delivery_id, user)
    return DeliveryOut.model_validate(delivery)


@router.post(
    "/deliveries/{delivery_id}/arrive",
    response_model=DeliveryOut,
    status_code=status.HTTP_200_OK,
    summary="Mark arrived at customer drop-off location",
)
async def arrive_at_destination(
    delivery_id: int,
    user: RiderUser,
    service: DeliveryServiceDep,
) -> DeliveryOut:
    delivery = await service.arrive(delivery_id, user)
    return DeliveryOut.model_validate(delivery)


@router.post(
    "/deliveries/{delivery_id}/complete",
    response_model=DeliveryOut,
    status_code=status.HTTP_200_OK,
    summary="Handover parcel to customer with verification PIN and COD settlement",
)
async def complete_delivery(
    delivery_id: int,
    data: DeliveryComplete,
    user: RiderUser,
    service: DeliveryServiceDep,
) -> DeliveryOut:
    delivery = await service.complete(delivery_id, user, data)
    return DeliveryOut.model_validate(delivery)


@router.post(
    "/deliveries/{delivery_id}/fail",
    response_model=DeliveryOut,
    status_code=status.HTTP_200_OK,
    summary="Report delivery failure (customer unreachable / wrong pin)",
)
async def fail_delivery(
    delivery_id: int,
    data: DeliveryFail,
    user: RiderUser,
    service: DeliveryServiceDep,
) -> DeliveryOut:
    delivery = await service.fail(delivery_id, user, data.reason)
    return DeliveryOut.model_validate(delivery)


@router.get(
    "/deliveries/{delivery_id}/navigation",
    response_model=RiderNavigationOut,
    status_code=status.HTTP_200_OK,
    summary="Get active route navigation and turn steps from road network router",
)
async def get_navigation_route(
    delivery_id: int,
    user: RiderUser,
    service: DeliveryServiceDep,
    lat: Optional[Decimal] = Query(None, description="Optional rider current latitude override"),
    lon: Optional[Decimal] = Query(None, description="Optional rider current longitude override"),
) -> RiderNavigationOut:
    nav = await service.get_rider_navigation(delivery_id, user, lat, lon)
    return RiderNavigationOut(**nav)
