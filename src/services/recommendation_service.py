# src/services/recommendation_service.py

from typing import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.algorithms.recommenders import Basket, HybridRecommenderEngine
from src.models import Customer, Order, OrderItem, OrderStatus, Product
from src.repositories.recommendation_repository import RecommendationRepository
from src.schemas import ProductPublic
from src.schemas.recommendation import (
    AlgorithmMetrics,
    RecommendationItemOut,
    RecommendationStatsOut,
    RecommendationTrackRequest,
    RecommendationTrackResponse,
)
from utilities import get_logger

log = get_logger(__name__)


class RecommendationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = RecommendationRepository(db)
        self.engine = HybridRecommenderEngine()

    async def _fetch_baskets(self) -> list[Basket]:
        """Loads historical completed or confirmed order itemsets from MySQL."""
        stmt = (
            select(Order.id, OrderItem.product_id)
            .join(OrderItem, Order.id == OrderItem.order_id)
            .where(Order.status != OrderStatus.CANCELLED)
        )
        rows = (await self.db.execute(stmt)).all()

        basket_map: dict[int, set[int]] = {}
        for order_id, product_id in rows:
            if order_id not in basket_map:
                basket_map[order_id] = set()
            basket_map[order_id].add(product_id)

        return [
            Basket(ref=str(oid), items=frozenset(items))
            for oid, items in basket_map.items()
            if len(items) >= 2
        ]

    async def get_recommendations(
        self,
        target_product_ids: Sequence[int] | None = None,
        limit: int = 6,
        algorithm: str | None = None,
    ) -> list[RecommendationItemOut]:
        """
        Recommends products using either Apriori or FP-Growth (chosen at random by server).
        """
        # Fetch active products
        prod_stmt = (
            select(Product)
            .options(selectinload(Product.brand), selectinload(Product.category))
            .where(Product.is_active.is_(True))
        )
        products = list((await self.db.execute(prod_stmt)).scalars().all())
        prod_lookup = {p.id: p for p in products}

        # Fetch transaction history
        baskets = await self._fetch_baskets()

        # Run hybrid engine (picks at random if algorithm is None)
        recommendations, chosen_algo = self.engine.recommend(
            baskets=baskets,
            target_product_ids=target_product_ids,
            available_product_ids=list(prod_lookup.keys()),
            limit=limit,
            algorithm=algorithm,
        )

        output: list[RecommendationItemOut] = []
        for rec in recommendations:
            product_obj = prod_lookup.get(rec.product_id)
            if product_obj is not None:
                output.append(
                    RecommendationItemOut(
                        product=ProductPublic.model_validate(product_obj),
                        algorithm=chosen_algo,  # type: ignore
                        score=rec.score,
                        reason=rec.reason,
                        recommendation_tag="⭐ Recommended" if chosen_algo == "fpgrowth" else "AI Pick",
                    )
                )

        return output

    async def track_event(
        self, data: RecommendationTrackRequest, customer: Customer | None = None
    ) -> RecommendationTrackResponse:
        """Records user interaction with recommendation for metric tracking."""
        event = await self.repo.create_event(
            product_id=data.product_id,
            algorithm=data.algorithm,
            event_type=data.event_type,
            customer_id=customer.id if customer else None,
            context=data.context,
            session_id=data.session_id,
            rating=data.rating,
            feedback_text=data.feedback_text,
        )
        return RecommendationTrackResponse(
            success=True,
            event_id=event.id,
            message="Event recorded successfully",
        )

    async def get_stats(self) -> RecommendationStatsOut:
        """Calculates comparative usability, acceptance rate, and CTR between Apriori and FP-Growth."""
        metrics_dict = await self.repo.get_metrics_by_algorithm()

        def _calc_metrics(d: dict) -> AlgorithmMetrics:
            imp = d.get("impressions", 0)
            clicks = d.get("clicks", 0)
            adds = d.get("cart_adds", 0)
            purchases = d.get("purchases", 0)
            ctr = (clicks / imp) if imp > 0 else 0.0
            acceptance = ((clicks + adds + purchases) / imp) if imp > 0 else 0.0
            return AlgorithmMetrics(
                impressions=imp,
                clicks=clicks,
                cart_adds=adds,
                purchases=purchases,
                ctr=round(ctr, 4),
                acceptance_rate=round(acceptance, 4),
                helpful_votes=d.get("helpful_votes", 0),
                unhelpful_votes=d.get("unhelpful_votes", 0),
                avg_rating=d.get("avg_rating", 0.0),
            )

        apriori_m = _calc_metrics(metrics_dict["apriori"])
        fpgrowth_m = _calc_metrics(metrics_dict["fpgrowth"])

        total_ev = (
            apriori_m.impressions
            + apriori_m.clicks
            + apriori_m.cart_adds
            + fpgrowth_m.impressions
            + fpgrowth_m.clicks
            + fpgrowth_m.cart_adds
        )

        winner_ctr = (
            "fpgrowth"
            if fpgrowth_m.ctr > apriori_m.ctr
            else ("apriori" if apriori_m.ctr > fpgrowth_m.ctr else "tied")
        )
        winner_acc = (
            "fpgrowth"
            if fpgrowth_m.acceptance_rate > apriori_m.acceptance_rate
            else ("apriori" if apriori_m.acceptance_rate > fpgrowth_m.acceptance_rate else "tied")
        )

        return RecommendationStatsOut(
            total_events=total_ev,
            apriori=apriori_m,
            fpgrowth=fpgrowth_m,
            winner_by_ctr=winner_ctr,
            winner_by_acceptance=winner_acc,
        )
