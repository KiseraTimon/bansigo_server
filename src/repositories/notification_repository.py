# src/repositories/notification_repository.py

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Notification
from .base_repository import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    def __init__(self, db: AsyncSession):
        super().__init__(Notification, db)

    async def list_for_user(
        self, user_id: int, *, filter_type: str | None = None, limit: int = 50
    ) -> list[Notification]:
        stmt = select(Notification).where(
            Notification.user_id == user_id,
            Notification.is_deleted.is_(False),
        )
        if filter_type and filter_type != "all":
            stmt = stmt.where(Notification.type == filter_type)
        stmt = stmt.order_by(Notification.id.desc()).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    async def existing_external_keys(self, user_id: int) -> set[str]:
        stmt = select(Notification.external_key).where(
            Notification.user_id == user_id,
            Notification.external_key.is_not(None),
        )
        return {k for k in (await self.db.execute(stmt)).scalars().all() if k}

    async def mark_read(self, user_id: int, notification_id: int) -> bool:
        stmt = (
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
                Notification.is_deleted.is_(False),
            )
            .values(is_read=True)
        )
        result = await self.db.execute(stmt)
        return (result.rowcount or 0) > 0

    async def mark_all_read(self, user_id: int) -> int:
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.is_deleted.is_(False),
            )
            .values(is_read=True)
        )
        result = await self.db.execute(stmt)
        return int(result.rowcount or 0)

    async def soft_delete(self, user_id: int, notification_id: int) -> bool:
        stmt = (
            update(Notification)
            .where(Notification.id == notification_id, Notification.user_id == user_id)
            .values(is_deleted=True)
        )
        result = await self.db.execute(stmt)
        return (result.rowcount or 0) > 0

    async def clear_for_user(self, user_id: int, *, read_only: bool = False) -> int:
        stmt = update(Notification).where(
            Notification.user_id == user_id,
            Notification.is_deleted.is_(False),
        )
        if read_only:
            stmt = stmt.where(Notification.is_read.is_(True))
        stmt = stmt.values(is_deleted=True)
        result = await self.db.execute(stmt)
        return int(result.rowcount or 0)

    async def unread_count(self, user_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.is_deleted.is_(False),
            )
        )
        return int((await self.db.execute(stmt)).scalar_one() or 0)
