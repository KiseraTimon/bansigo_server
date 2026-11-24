# src/services/notification_service.py

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Notification
from src.repositories import NotificationRepository


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.notifications = NotificationRepository(db)

    def stage(
        self,
        *,
        user_id: int,
        title: str,
        message: str,
        notif_type: str = "delivery",
        action_type: Optional[str] = None,
        action_payload: Optional[str] = None,
    ) -> Notification:
        """Stages a persistent notification inside the caller's transaction."""
        notif = Notification(
            user_id=user_id,
            title=title[:150],
            message=message,
            type=notif_type[:30],
            action_type=action_type[:40] if action_type else None,
            action_payload=action_payload[:255] if action_payload else None,
        )
        self.db.add(notif)
        return notif

    async def ensure_default_notifications(self, user_id: int, seed_items: list[dict]) -> None:
        """Idempotently seeds curated customer notifications into the database per user."""
        existing = await self.notifications.existing_external_keys(user_id)
        added = False
        for item in seed_items:
            key = item.get("id")
            if not key or key in existing:
                continue
            self.db.add(
                Notification(
                    user_id=user_id,
                    external_key=key[:64],
                    title=item["title"][:150],
                    message=item["message"],
                    type=item.get("type", "system")[:30],
                    is_read=bool(item.get("is_read", False)),
                    action_type=item.get("action_type"),
                    action_payload=item.get("action_payload"),
                )
            )
            added = True
        if added:
            await self.db.commit()

    async def list_for_user(
        self, user_id: int, *, filter_type: Optional[str] = None, limit: int = 50
    ) -> list[Notification]:
        return await self.notifications.list_for_user(user_id, filter_type=filter_type, limit=limit)

    async def mark_read(self, user_id: int, notification_id: int) -> bool:
        updated = await self.notifications.mark_read(user_id, notification_id)
        await self.db.commit()
        return updated

    async def mark_all_read(self, user_id: int) -> int:
        count = await self.notifications.mark_all_read(user_id)
        await self.db.commit()
        return count

    async def delete_notification(self, user_id: int, notification_id: int) -> bool:
        deleted = await self.notifications.soft_delete(user_id, notification_id)
        await self.db.commit()
        return deleted

    async def clear_notifications(self, user_id: int, *, read_only: bool = False) -> int:
        count = await self.notifications.clear_for_user(user_id, read_only=read_only)
        await self.db.commit()
        return count
