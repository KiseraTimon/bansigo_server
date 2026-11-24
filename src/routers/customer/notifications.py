# src/routers/customer/notifications.py

from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from src.dependencies import OptionalUser, get_notification_service
from src.services import NotificationService
from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["customer-notifications"])
NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]


class CustomerNotification(BaseModel):
    id: str
    title: str
    message: str
    type: str  # "order", "promo", "system", "delivery"
    created_at: str
    is_read: bool = False
    action_type: Optional[str] = None
    action_payload: Optional[str] = None


class NotificationListResponse(BaseModel):
    items: list[CustomerNotification]
    unread_count: int
    total: int


_SEED_NOTIFICATIONS: list[dict] = [
    {
        "id": "notif-1",
        "title": "Welcome to BansiGo Mega Store!",
        "message": "Enjoy 15-20 min lightning delivery right to your door in Wasweta & Migori.",
        "type": "system",
        "created_at": "10 minutes ago",
        "is_read": False,
        "action_type": "explore",
        "action_payload": "all",
    },
    {
        "id": "notif-2",
        "title": "Flash Sale: Up to 25% OFF Deli & Bakery",
        "message": "Freshly baked bread, savory meat pies and deli specials are on discount today.",
        "type": "promo",
        "created_at": "1 hour ago",
        "is_read": False,
        "action_type": "category",
        "action_payload": "bakery-pastries",
    },
    {
        "id": "notif-3",
        "title": "Delivery Zone Active • 7KM Supermarket Radius",
        "message": "Instant delivery available across all zones from Bansi Mega Supermarket.",
        "type": "delivery",
        "created_at": "3 hours ago",
        "is_read": False,
        "action_type": "address",
        "action_payload": "map",
    },
    {
        "id": "notif-4",
        "title": "Highland Honey Deal Live",
        "message": "Pure Kenyan Highland Honey 500g is today's featured deal with extra reward points.",
        "type": "promo",
        "created_at": "Yesterday",
        "is_read": True,
        "action_type": "product",
        "action_payload": "fresh_honey",
    },
]


@router.get(
    "/notifications",
    response_model=NotificationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List customer notifications",
)
async def list_notifications(
    user: OptionalUser,
    service: NotificationServiceDep,
    filter_type: Optional[str] = Query(None, description="Optional type filter (order, promo, delivery)"),
) -> NotificationListResponse:
    """
    Returns persisted order/delivery notifications for authenticated customers plus curated deals.
    """
    notifications: list[CustomerNotification] = []

    if user is not None:
        await service.ensure_default_notifications(user.id, _SEED_NOTIFICATIONS)
        db_notifs = await service.list_for_user(user.id, filter_type=filter_type, limit=50)
        for n in db_notifs:
            notifications.append(
                CustomerNotification(
                    id=f"db-{n.id}",
                    title=n.title,
                    message=n.message,
                    type=n.type,
                    created_at=n.created_at.strftime("%Y-%m-%d %H:%M UTC") if n.created_at else "Just now",
                    is_read=n.is_read,
                    action_type=n.action_type,
                    action_payload=n.action_payload,
                )
            )
    else:
        for item in _SEED_NOTIFICATIONS:
            if filter_type and filter_type != "all" and item["type"] != filter_type:
                continue
            notifications.append(
                CustomerNotification(
                    id=item["id"],
                    title=item["title"],
                    message=item["message"],
                    type=item["type"],
                    created_at=item["created_at"],
                    is_read=item.get("is_read", False),
                    action_type=item.get("action_type"),
                    action_payload=item.get("action_payload"),
                )
            )

    unread = sum(1 for n in notifications if not n.is_read)
    return NotificationListResponse(
        items=notifications,
        unread_count=unread,
        total=len(notifications),
    )


def _parse_db_notification_id(notification_id: str) -> Optional[int]:
    if notification_id.startswith("db-"):
        try:
            return int(notification_id[3:])
        except ValueError:
            return None
    if notification_id.isdigit():
        return int(notification_id)
    return None


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Mark notification as read",
)
async def mark_notification_read(
    notification_id: str,
    user: OptionalUser,
    service: NotificationServiceDep,
) -> dict:
    updated = False
    if user is not None:
        nid = _parse_db_notification_id(notification_id)
        if nid is not None:
            updated = await service.mark_read(user.id, nid)
    return {"status": "success", "id": notification_id, "is_read": True, "persisted": updated}


@router.post(
    "/notifications/read-all",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Mark all notifications as read",
)
async def mark_all_notifications_read(
    user: OptionalUser,
    service: NotificationServiceDep,
) -> dict:
    db_count = 0
    if user is not None:
        db_count = await service.mark_all_read(user.id)
    return {"status": "success", "marked_read": db_count}


@router.delete(
    "/notifications/{notification_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Dismiss/delete a notification",
)
async def delete_notification(
    notification_id: str,
    user: OptionalUser,
    service: NotificationServiceDep,
) -> dict:
    deleted = False
    if user is not None:
        nid = _parse_db_notification_id(notification_id)
        if nid is not None:
            deleted = await service.delete_notification(user.id, nid)
    return {"status": "success", "id": notification_id, "deleted": deleted}


@router.delete(
    "/notifications",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Clear notifications",
)
async def clear_notifications(
    user: OptionalUser,
    service: NotificationServiceDep,
    read_only: bool = Query(False, description="If true, only clears notifications already marked as read"),
) -> dict:
    cleared = 0
    if user is not None:
        cleared = await service.clear_notifications(user.id, read_only=read_only)
    return {"status": "success", "cleared": cleared}
