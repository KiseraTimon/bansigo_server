# src/routers/customer/notifications.py

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["customer-notifications"])


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


# In-memory store for notification state per session/read flags
_READ_NOTIFICATION_IDS: set[str] = set()

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
    filter_type: Optional[str] = Query(None, description="Optional type filter (order, promo, delivery)"),
) -> NotificationListResponse:
    """
    Returns curated notifications for the customer, including delivery updates and deals.
    """
    notifications: list[CustomerNotification] = []
    for item in _SEED_NOTIFICATIONS:
        if filter_type and filter_type != "all" and item["type"] != filter_type:
            continue
        is_read = item["id"] in _READ_NOTIFICATION_IDS or item.get("is_read", False)
        notifications.append(
            CustomerNotification(
                id=item["id"],
                title=item["title"],
                message=item["message"],
                type=item["type"],
                created_at=item["created_at"],
                is_read=is_read,
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


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Mark notification as read",
)
async def mark_notification_read(notification_id: str) -> dict:
    _READ_NOTIFICATION_IDS.add(notification_id)
    return {"status": "success", "id": notification_id, "is_read": True}


@router.post(
    "/notifications/read-all",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Mark all notifications as read",
)
async def mark_all_notifications_read() -> dict:
    for item in _SEED_NOTIFICATIONS:
        _READ_NOTIFICATION_IDS.add(item["id"])
    return {"status": "success", "marked_read": len(_SEED_NOTIFICATIONS)}
