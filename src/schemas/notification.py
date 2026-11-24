# src/schemas/notification.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: str
    title: str
    message: str
    type: str
    created_at: str
    timestamp: Optional[datetime] = None
    is_read: bool = False
    action_type: Optional[str] = None
    action_payload: Optional[str] = None


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread_count: int
    total: int
