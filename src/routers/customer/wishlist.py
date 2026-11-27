# src/routers/customer/wishlist.py

from typing import Annotated
from fastapi import APIRouter, Depends, status

from src.dependencies import CurrentCustomer, get_wishlist_service
from src.schemas import ProductPublic, WishlistSyncRequest
from src.services import WishlistService
from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/wishlist", tags=["customer-wishlist"])
WishlistServiceDep = Annotated[WishlistService, Depends(get_wishlist_service)]


@router.get(
    "",
    response_model=list[ProductPublic],
    status_code=status.HTTP_200_OK,
    summary="List customer wishlist products",
)
async def list_wishlist(
    customer: CurrentCustomer,
    service: WishlistServiceDep,
) -> list[ProductPublic]:
    return await service.list_products(customer)


@router.post(
    "/sync",
    response_model=list[ProductPublic],
    status_code=status.HTTP_200_OK,
    summary="Sync locally saved product IDs into customer wishlist",
)
async def sync_wishlist(
    data: WishlistSyncRequest,
    customer: CurrentCustomer,
    service: WishlistServiceDep,
) -> list[ProductPublic]:
    return await service.sync_products(customer, data.product_ids)


@router.post(
    "/{product_id}",
    response_model=list[ProductPublic],
    status_code=status.HTTP_200_OK,
    summary="Add product to customer wishlist",
)
async def add_to_wishlist(
    product_id: int,
    customer: CurrentCustomer,
    service: WishlistServiceDep,
) -> list[ProductPublic]:
    return await service.add_product(customer, product_id)


@router.delete(
    "/{product_id}",
    response_model=list[ProductPublic],
    status_code=status.HTTP_200_OK,
    summary="Remove product from customer wishlist",
)
async def remove_from_wishlist(
    product_id: int,
    customer: CurrentCustomer,
    service: WishlistServiceDep,
) -> list[ProductPublic]:
    return await service.remove_product(customer, product_id)
