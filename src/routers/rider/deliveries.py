# src/routers/rider/deliveries.py

import os
import uuid
from decimal import Decimal
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

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


@router.post(
    "/documents/upload",
    summary="Upload rider vetting document or profile picture",
)
async def upload_rider_document(
    user: CurrentUser,
    doc_type: str = Query(..., description="Type: id_front, id_back, licence, vehicle_proof, or avatar"),
    file: UploadFile = File(...)
):
    valid_types = {"id_front", "id_back", "licence", "vehicle_proof", "avatar"}
    if doc_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid doc_type. Must be one of: {', '.join(valid_types)}"
        )

    # Validate file extension
    original_name = file.filename or "upload.jpg"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp", ".pdf"]:
        ext = ".jpg"

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File size exceeds 10MB limit")

    # Target save folder
    from src import MEDIA_DIR
    target_dir = os.path.join(MEDIA_DIR, "rider_documents")
    os.makedirs(target_dir, exist_ok=True)

    filename = f"rider_{user.id}_{doc_type}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(target_dir, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    file_url = f"/media/rider_documents/{filename}"
    log.info("Rider %s uploaded document %s -> %s", user.id, doc_type, file_url)
    return {"url": file_url, "doc_type": doc_type, "filename": filename}


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
