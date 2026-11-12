# src/routers/customer/recommendations.py

from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query, status

from src.database import get_db
from src.schemas.recommendation import (
    RecommendationItemOut,
    RecommendationStatsOut,
    RecommendationTrackRequest,
    RecommendationTrackResponse,
)
from src.services.recommendation_service import RecommendationService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/recommendations", tags=["customer-recommendations"])


def get_recommendation_service(db: Annotated[AsyncSession, Depends(get_db)]) -> RecommendationService:
    return RecommendationService(db)


RecommendationServiceDep = Annotated[RecommendationService, Depends(get_recommendation_service)]


@router.get(
    "",
    response_model=list[RecommendationItemOut],
    status_code=status.HTTP_200_OK,
    summary="Get product recommendations",
)
async def get_recommendations(
    service: RecommendationServiceDep,
    product_id: Optional[int] = Query(None, description="Optional target product ID for cross-sell"),
    limit: int = Query(6, ge=1, le=20),
    algorithm: Optional[str] = Query(None, description="Force 'apriori' or 'fpgrowth'; if omitted, server chooses randomly"),
) -> list[RecommendationItemOut]:
    """
    Returns AI product recommendations powered by Apriori or FP-Growth.
    When algorithm is not specified, the server selects between them randomly
    to evaluate model performance and user acceptance.
    """
    target_ids = [product_id] if product_id is not None else None
    return await service.get_recommendations(
        target_product_ids=target_ids,
        limit=limit,
        algorithm=algorithm,
    )


@router.post(
    "/track",
    response_model=RecommendationTrackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Track recommendation interaction",
)
async def track_recommendation(
    data: RecommendationTrackRequest,
    service: RecommendationServiceDep,
) -> RecommendationTrackResponse:
    """
    Tracks recommendation impressions, clicks, cart adds, purchases, and ratings
    to analyze acceptance rate, usability, and algorithmic comparison.
    """
    return await service.track_event(data)


@router.get(
    "/stats",
    response_model=RecommendationStatsOut,
    status_code=status.HTTP_200_OK,
    summary="Recommendation performance and acceptance metrics",
)
async def get_recommendation_stats(
    service: RecommendationServiceDep,
) -> RecommendationStatsOut:
    """
    Returns comparative metrics (impressions, clicks, CTR, acceptance rate, ratings)
    between the Apriori and FP-Growth recommendation engines.
    """
    return await service.get_stats()
