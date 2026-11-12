# src/repositories/recommendation_repository.py

from typing import Any
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import RecommendationEvent
from .base_repository import BaseRepository


class RecommendationRepository(BaseRepository[RecommendationEvent]):
    def __init__(self, db: AsyncSession):
        super().__init__(RecommendationEvent, db)

    async def create_event(
        self,
        product_id: int,
        algorithm: str,
        event_type: str,
        customer_id: int | None = None,
        context: str | None = None,
        session_id: str | None = None,
        rating: int | None = None,
        feedback_text: str | None = None,
    ) -> RecommendationEvent:
        event = RecommendationEvent(
            product_id=product_id,
            algorithm=algorithm,
            event_type=event_type,
            customer_id=customer_id,
            context=context,
            session_id=session_id,
            rating=rating,
            feedback_text=feedback_text,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def get_metrics_by_algorithm(self) -> dict[str, dict[str, Any]]:
        """
        Aggregates impressions, clicks, cart adds, purchases, ratings by algorithm.
        """
        stmt = (
            select(
                RecommendationEvent.algorithm,
                RecommendationEvent.event_type,
                func.count(RecommendationEvent.id).label("count"),
            )
            .group_by(RecommendationEvent.algorithm, RecommendationEvent.event_type)
        )
        rows = (await self.db.execute(stmt)).all()

        metrics: dict[str, dict[str, Any]] = {
            "apriori": {
                "impressions": 0,
                "clicks": 0,
                "cart_adds": 0,
                "purchases": 0,
                "helpful_votes": 0,
                "unhelpful_votes": 0,
                "ratings": [],
            },
            "fpgrowth": {
                "impressions": 0,
                "clicks": 0,
                "cart_adds": 0,
                "purchases": 0,
                "helpful_votes": 0,
                "unhelpful_votes": 0,
                "ratings": [],
            },
        }

        for algo, event_type, count in rows:
            if algo not in metrics:
                continue
            if event_type == "impression":
                metrics[algo]["impressions"] += count
            elif event_type == "click":
                metrics[algo]["clicks"] += count
            elif event_type == "add_to_cart":
                metrics[algo]["cart_adds"] += count
            elif event_type == "purchase":
                metrics[algo]["purchases"] += count
            elif event_type == "helpful":
                metrics[algo]["helpful_votes"] += count
            elif event_type == "unhelpful":
                metrics[algo]["unhelpful_votes"] += count

        # Ratings
        rating_stmt = (
            select(
                RecommendationEvent.algorithm,
                func.avg(RecommendationEvent.rating).label("avg_rating"),
            )
            .where(RecommendationEvent.rating.is_not(None))
            .group_by(RecommendationEvent.algorithm)
        )
        rating_rows = (await self.db.execute(rating_stmt)).all()
        for algo, avg_r in rating_rows:
            if algo in metrics and avg_r is not None:
                metrics[algo]["avg_rating"] = float(round(avg_r, 2))

        return metrics
