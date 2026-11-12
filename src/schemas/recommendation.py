# src/schemas/recommendation.py

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

from .catalogue import ProductPublic


class RecommendationItemOut(BaseModel):
    product: ProductPublic
    algorithm: Literal["apriori", "fpgrowth"]
    score: float
    reason: str
    recommendation_tag: str = "Recommended"


class RecommendationTrackRequest(BaseModel):
    product_id: int
    algorithm: Literal["apriori", "fpgrowth"]
    event_type: Literal["impression", "click", "add_to_cart", "purchase", "helpful", "unhelpful"]
    context: str | None = Field(default="home", max_length=50)
    session_id: str | None = Field(default=None, max_length=100)
    rating: int | None = Field(default=None, ge=1, le=5)
    feedback_text: str | None = Field(default=None, max_length=255)


class RecommendationTrackResponse(BaseModel):
    success: bool = True
    event_id: int
    message: str = "Event tracked successfully"


class AlgorithmMetrics(BaseModel):
    impressions: int = 0
    clicks: int = 0
    cart_adds: int = 0
    purchases: int = 0
    ctr: float = 0.0
    acceptance_rate: float = 0.0
    helpful_votes: int = 0
    unhelpful_votes: int = 0
    avg_rating: float = 0.0


class RecommendationStatsOut(BaseModel):
    total_events: int = 0
    apriori: AlgorithmMetrics = Field(default_factory=AlgorithmMetrics)
    fpgrowth: AlgorithmMetrics = Field(default_factory=AlgorithmMetrics)
    winner_by_ctr: str = "undecided"
    winner_by_acceptance: str = "undecided"
