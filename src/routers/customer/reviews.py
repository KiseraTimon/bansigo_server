# src/routers/customer/reviews.py

from typing import Annotated
from fastapi import APIRouter, Depends, Query, status

from src.dependencies import CurrentCustomer, get_review_service
from src.schemas import (
    OrderReviewStatusOut, ProductReviewsSummaryOut, ReviewCreate, ReviewOut,
)
from src.services import ReviewService
from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["customer-reviews"])
ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]


@router.get(
    "/products/{product_id}/reviews",
    response_model=ProductReviewsSummaryOut,
    status_code=status.HTTP_200_OK,
    summary="List published reviews and average rating for a product",
)
async def get_product_reviews(
    product_id: int,
    service: ReviewServiceDep,
    limit: int = Query(50, ge=1, le=100),
) -> ProductReviewsSummaryOut:
    return await service.list_for_product(product_id, limit=limit)


@router.get(
    "/orders/{order_id}/reviews",
    response_model=OrderReviewStatusOut,
    status_code=status.HTTP_200_OK,
    summary="Get reviewable products and rider delivery review status for an order",
)
async def get_order_reviews_status(
    order_id: int,
    customer: CurrentCustomer,
    service: ReviewServiceDep,
) -> OrderReviewStatusOut:
    return await service.get_order_review_status(customer, order_id)


@router.get(
    "/reviews/mine",
    response_model=list[ReviewOut],
    status_code=status.HTTP_200_OK,
    summary="List reviews submitted by the authenticated customer",
)
async def list_my_reviews(
    customer: CurrentCustomer,
    service: ReviewServiceDep,
) -> list[ReviewOut]:
    return await service.list_by_customer(customer)


@router.post(
    "/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit or update a review for a product or rider delivery",
)
async def create_review(
    data: ReviewCreate,
    customer: CurrentCustomer,
    service: ReviewServiceDep,
) -> ReviewOut:
    return await service.submit_review(customer, data)
