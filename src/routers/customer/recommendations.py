# src/routers/customer/recommendations.py

from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.dependencies import OptionalUser
from src.repositories import CustomerRepository
from src.schemas.recommendation import (
    RecommendationItemOut,
    RecommendationStatsOut,
    RecommendationTrackRequest,
    RecommendationTrackResponse,
)
from src.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/recommendations", tags=["customer-recommendations"])


def get_recommendation_service(db: Annotated[AsyncSession, Depends(get_db)]) -> RecommendationService:
    return RecommendationService(db)


RecommendationServiceDep = Annotated[RecommendationService, Depends(get_recommendation_service)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "",
    response_model=list[RecommendationItemOut],
    status_code=status.HTTP_200_OK,
    summary="Get product recommendations",
)
async def get_recommendations(
    service: RecommendationServiceDep,
    product_id: Optional[int] = Query(None, description="Optional target product ID for cross-sell"),
    product_ids: Optional[str] = Query(None, description="Optional comma-separated product IDs for cart cross-sell"),
    limit: int = Query(6, ge=1, le=20),
    algorithm: Optional[str] = Query(None, description="Force 'apriori' or 'fpgrowth'; if omitted, server chooses randomly"),
) -> list[RecommendationItemOut]:
    """
    Returns AI product recommendations powered by Apriori or FP-Growth.
    When algorithm is not specified, the server selects between them randomly
    to evaluate model performance and user acceptance.
    """
    target_list: list[int] = []
    if product_id is not None:
        target_list.append(product_id)
    if product_ids:
        for tok in product_ids.split(","):
            tok = tok.strip()
            if tok.isdigit():
                pid = int(tok)
                if pid not in target_list:
                    target_list.append(pid)
    return await service.get_recommendations(
        target_product_ids=target_list or None,
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
    user: OptionalUser,
    db: DbSessionDep,
) -> RecommendationTrackResponse:
    """
    Tracks recommendation impressions, clicks, cart adds, purchases, and ratings
    to analyze acceptance rate, usability, and algorithmic comparison.
    """
    customer = None
    if user is not None:
        customer = await CustomerRepository(db).get_by_user_id(user.id)
    return await service.track_event(data, customer=customer)


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
