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
    get_notification_service,
    get_review_service,
    get_rider_service,
)
from src.schemas import (
    DeliveryComplete,
    DeliveryFail,
    DeliveryOut,
    DeliveryPickup,
    DeliveryRespond,
    Detail,
    NotificationListOut,
    NotificationOut,
    RiderApply,
    RiderDeliveryDetailOut,
    RiderGoStatus,
    RiderLocation,
    RiderNavigationOut,
    RiderOut,
    RiderReviewsSummaryOut,
    RiderWalletOut,
    RiderWithdrawOut,
    RiderWithdrawRequest,
)
from src.services import DeliveryService, NotificationService, ReviewService, RiderService
from utilities import get_logger


log = get_logger(__name__)

# routing object
router = APIRouter(tags=["rider-deliveries"])

# Dependencies
DeliveryServiceDep = Annotated[DeliveryService, Depends(get_delivery_service)]
RiderServiceDep = Annotated[RiderService, Depends(get_rider_service)]
NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]
ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]


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
    delivery = await service.respond(
        delivery_id,
        user,
        data.accept,
        reason_code=data.reason_code,
        reason_text=data.reason_text,
    )
    return DeliveryOut.model_validate(delivery)


@router.post(
    "/deliveries/{delivery_id}/pickup",
    response_model=DeliveryOut,
    status_code=status.HTTP_200_OK,
    summary="Verify store pickup code and mark parcel picked up at Bansi Mega Supermarket",
)
async def pickup_delivery(
    delivery_id: int,
    data: DeliveryPickup,
    user: RiderUser,
    service: DeliveryServiceDep,
) -> DeliveryOut:
    delivery = await service.pick_up(delivery_id, user, data.pickup_code)
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


# Wallet & payouts

@router.get(
    "/wallet",
    response_model=RiderWalletOut,
    status_code=status.HTTP_200_OK,
    summary="Get rider earnings summary, COD cash in hand, and transaction ledger",
)
async def get_rider_wallet(
    user: RiderUser,
    service: RiderServiceDep,
) -> RiderWalletOut:
    wallet = await service.get_wallet(user)
    return RiderWalletOut(**wallet)


@router.post(
    "/wallet/withdraw",
    response_model=RiderWithdrawOut,
    status_code=status.HTTP_201_CREATED,
    summary="Request M-Pesa B2C payout withdrawal from available rider earnings",
)
async def withdraw_rider_wallet(
    data: RiderWithdrawRequest,
    user: RiderUser,
    service: RiderServiceDep,
) -> RiderWithdrawOut:
    payout, new_balance = await service.withdraw_wallet(user, data.amount, data.phone)
    ts = payout.created_at
    return RiderWithdrawOut(
        id=payout.id,
        amount=payout.amount,
        phone=payout.phone,
        reference_code=payout.reference_code,
        status=payout.status,
        timestamp=ts.strftime("%b %d, %I:%M %p") if ts else "Just now",
        available_balance=new_balance,
    )


# Rider notifications (pickup codes, dispatch offers, SLA warnings, penalties)

@router.get(
    "/notifications",
    response_model=NotificationListOut,
    status_code=status.HTTP_200_OK,
    summary="List notifications for the authenticated rider (including store pickup codes)",
)
async def get_rider_notifications(
    user: RiderUser,
    service: NotificationServiceDep,
    filter_type: Optional[str] = Query(None),
) -> NotificationListOut:
    rows = await service.list_for_user(user.id, filter_type=filter_type, limit=50)
    items = [
        NotificationOut(
            id=str(n.id),
            title=n.title,
            message=n.message,
            type=n.type,
            created_at=n.created_at.strftime("%Y-%m-%d %H:%M UTC") if n.created_at else "Just now",
            timestamp=n.created_at,
            is_read=n.is_read,
            action_type=n.action_type,
            action_payload=n.action_payload,
        )
        for n in rows
    ]
    unread = sum(1 for i in items if not i.is_read)
    return NotificationListOut(items=items, unread_count=unread, total=len(items))


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Mark a rider notification as read",
)
async def mark_rider_notification_read(
    notification_id: int,
    user: RiderUser,
    service: NotificationServiceDep,
) -> dict:
    await service.mark_read(user.id, notification_id)
    return {"status": "success", "id": str(notification_id), "is_read": True}


@router.post(
    "/notifications/read-all",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Mark all rider notifications as read",
)
async def mark_all_rider_notifications_read(
    user: RiderUser,
    service: NotificationServiceDep,
) -> dict:
    marked = await service.mark_all_read(user.id)
    return {"status": "success", "marked_read": marked}


@router.get(
    "/reviews",
    response_model=RiderReviewsSummaryOut,
    status_code=status.HTTP_200_OK,
    summary="List customer delivery reviews and average rating for the current rider",
)
async def get_rider_reviews(
    user: RiderUser,
    service: ReviewServiceDep,
) -> RiderReviewsSummaryOut:
    return await service.list_for_rider_user(user)
