# src/repositories/review_repository.py

from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import Customer, Review, ReviewTargetType, Rider
from .base_repository import BaseRepository


class ReviewRepository(BaseRepository[Review]):
    """
    repository handling database queries for customer ratings and reviews
    """

    _FULL = (
        selectinload(Review.customer).selectinload(Customer.user),
        selectinload(Review.rider).selectinload(Rider.user),
        selectinload(Review.product),
        selectinload(Review.order),
    )

    def __init__(self, db: AsyncSession):
        super().__init__(Review, db)

    async def list_recent(
        self,
        *,
        limit: int = 50,
        target_type: Optional[ReviewTargetType] = None,
        rating: Optional[int] = None,
        published_only: bool = False,
    ) -> list[Review]:
        """
        retrieves recent reviews with customer, rider, order and product relations eager loaded
        """
        stmt = select(Review).options(*self._FULL).order_by(Review.id.desc()).limit(limit)

        if published_only:
            stmt = stmt.where(Review.is_published.is_(True))
        if target_type is not None:
            stmt = stmt.where(Review.target_type == target_type)
        if rating is not None:
            stmt = stmt.where(Review.rating == rating)

        return list((await self.db.execute(stmt)).scalars().all())

    async def get_summary_stats(self) -> dict[str, Any]:
        """
        computes average rating and distribution statistics from the database
        """
        total = (await self.db.execute(select(func.count(Review.id)))).scalar_one() or 0
        if total == 0:
            return {
                "average_rating": "0.00",
                "total_reviews": 0,
                "satisfaction_rate": "N/A",
                "five_star_pct": "0%",
                "four_star_pct": "0%",
                "critical_pct": "0%",
            }

        avg_val = (await self.db.execute(select(func.avg(Review.rating)))).scalar_one() or Decimal("5.0")
        five_count = (await self.db.execute(select(func.count(Review.id)).where(Review.rating == 5))).scalar_one() or 0
        four_count = (await self.db.execute(select(func.count(Review.id)).where(Review.rating == 4))).scalar_one() or 0
        crit_count = (await self.db.execute(select(func.count(Review.id)).where(Review.rating <= 2))).scalar_one() or 0

        five_pct = int(round((five_count / total) * 100))
        four_pct = int(round((four_count / total) * 100))
        crit_pct = int(round((crit_count / total) * 100))
        satisfaction = int(round(((five_count + four_count) / total) * 100))

        return {
            "average_rating": f"{float(avg_val):.2f}",
            "total_reviews": total,
            "satisfaction_rate": f"{satisfaction}%",
            "five_star_pct": f"{five_pct}%",
            "four_star_pct": f"{four_pct}%",
            "critical_pct": f"{crit_pct}%",
        }

    async def list_for_product(self, product_id: int, *, limit: int = 50) -> list[Review]:
        stmt = (
            select(Review)
            .options(*self._FULL)
            .where(
                Review.product_id == product_id,
                Review.target_type == ReviewTargetType.PRODUCT,
                Review.is_published.is_(True),
            )
            .order_by(Review.id.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_product_rating_stats(self, product_id: int) -> tuple[Optional[Decimal], int]:
        stmt = select(
            func.avg(Review.rating),
            func.count(Review.id),
        ).where(
            Review.product_id == product_id,
            Review.target_type == ReviewTargetType.PRODUCT,
            Review.is_published.is_(True),
        )
        row = (await self.db.execute(stmt)).one()
        avg_val, count_val = row[0], int(row[1] or 0)
        if count_val == 0 or avg_val is None:
            return None, 0
        return Decimal(str(round(float(avg_val), 2))), count_val

    async def list_for_rider(self, rider_id: int, *, limit: int = 50) -> list[Review]:
        stmt = (
            select(Review)
            .options(*self._FULL)
            .where(
                Review.rider_id == rider_id,
                Review.target_type.in_((ReviewTargetType.RIDER, ReviewTargetType.DELIVERY)),
                Review.is_published.is_(True),
            )
            .order_by(Review.id.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_rider_rating_stats(self, rider_id: int) -> tuple[Optional[Decimal], int]:
        stmt = select(
            func.avg(Review.rating),
            func.count(Review.id),
        ).where(
            Review.rider_id == rider_id,
            Review.target_type.in_((ReviewTargetType.RIDER, ReviewTargetType.DELIVERY)),
            Review.is_published.is_(True),
        )
        row = (await self.db.execute(stmt)).one()
        avg_val, count_val = row[0], int(row[1] or 0)
        if count_val == 0 or avg_val is None:
            return None, 0
        return Decimal(str(round(float(avg_val), 2))), count_val

    async def list_for_order_by_customer(self, customer_id: int, order_id: int) -> list[Review]:
        stmt = (
            select(Review)
            .options(*self._FULL)
            .where(Review.customer_id == customer_id, Review.order_id == order_id)
            .order_by(Review.id.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_by_customer(self, customer_id: int, *, limit: int = 50) -> list[Review]:
        stmt = (
            select(Review)
            .options(*self._FULL)
            .where(Review.customer_id == customer_id)
            .order_by(Review.id.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def find_existing(
        self,
        *,
        customer_id: int,
        target_type: ReviewTargetType,
        order_id: Optional[int] = None,
        product_id: Optional[int] = None,
        rider_id: Optional[int] = None,
    ) -> Optional[Review]:
        stmt = select(Review).options(*self._FULL).where(Review.customer_id == customer_id)
        if target_type in (ReviewTargetType.RIDER, ReviewTargetType.DELIVERY) and order_id is not None:
            stmt = stmt.where(
                Review.order_id == order_id,
                Review.target_type.in_((ReviewTargetType.RIDER, ReviewTargetType.DELIVERY)),
            )
        elif target_type == ReviewTargetType.PRODUCT and product_id is not None:
            stmt = stmt.where(
                Review.target_type == ReviewTargetType.PRODUCT,
                Review.product_id == product_id,
            )
            if order_id is not None:
                stmt = stmt.where(Review.order_id == order_id)
            else:
                stmt = stmt.where(Review.order_id.is_(None))
        else:
            stmt = stmt.where(Review.target_type == target_type)
            if order_id is not None:
                stmt = stmt.where(Review.order_id == order_id)
            if rider_id is not None:
                stmt = stmt.where(Review.rider_id == rider_id)
        return (await self.db.execute(stmt.order_by(Review.id.desc()).limit(1))).scalar_one_or_none()
