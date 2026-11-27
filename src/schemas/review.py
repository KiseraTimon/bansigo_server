# src/schemas/review.py

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models import ReviewTargetType


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: ReviewTargetType
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=500)
    order_id: Optional[int] = None
    product_id: Optional[int] = None
    rider_id: Optional[int] = None

    @field_validator("comment")
    @classmethod
    def _clean_comment(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _validate_target(self):
        if self.target_type == ReviewTargetType.PRODUCT and self.product_id is None:
            raise ValueError("product_id is required when reviewing a product")
        if self.target_type in (ReviewTargetType.RIDER, ReviewTargetType.DELIVERY):
            if self.order_id is None and self.rider_id is None:
                raise ValueError("order_id or rider_id is required when reviewing a rider or delivery")
        return self


class ReviewOut(BaseModel):
    id: int
    customer_name: str
    target_type: ReviewTargetType
    order_id: Optional[int] = None
    order_number: Optional[str] = None
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    rider_id: Optional[int] = None
    rider_name: Optional[str] = None
    rating: int
    comment: Optional[str] = None
    sentiment: str
    is_published: bool = True
    verified_purchase: bool = False
    created_at: datetime


class ProductReviewsSummaryOut(BaseModel):
    product_id: int
    average_rating: Optional[Decimal] = None
    total_reviews: int = 0
    reviews: list[ReviewOut] = Field(default_factory=list)


class OrderProductReviewItemOut(BaseModel):
    product_id: int
    product_name: str
    sku: str
    already_reviewed: bool = False
    existing_review: Optional[ReviewOut] = None


class OrderReviewStatusOut(BaseModel):
    order_id: int
    order_number: str
    order_status: str
    can_review_delivery: bool = False
    rider_id: Optional[int] = None
    rider_name: Optional[str] = None
    delivery_reviewed: bool = False
    existing_delivery_review: Optional[ReviewOut] = None
    reviewable_products: list[OrderProductReviewItemOut] = Field(default_factory=list)


class RiderReviewsSummaryOut(BaseModel):
    rider_id: int
    average_rating: Optional[Decimal] = None
    rating_count: int = 0
    reviews: list[ReviewOut] = Field(default_factory=list)
