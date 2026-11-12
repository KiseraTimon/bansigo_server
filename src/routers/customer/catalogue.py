# src/routers/customer/catalogue.py

from typing import Annotated
from fastapi import APIRouter, Depends, Query, status

from decimal import Decimal

from src.dependencies import get_catalogue_service
from src.schemas import CategoryTree, Page, ProductPublic, ProductQuery
from src.services import CatalogueService
from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["customer-catalogue"])
CatalogueServiceDep = Annotated[CatalogueService, Depends(get_catalogue_service)]


@router.get(
    "/categories",
    response_model=list[CategoryTree],
    status_code=status.HTTP_200_OK,
    summary="List product category tree",
)
async def list_categories(
    service: CatalogueServiceDep,
) -> list[CategoryTree]:
    """
    Returns active category hierarchy for customer navigation.
    """
    return await service.category_tree(active_only=True)


@router.get(
    "/products",
    response_model=Page[ProductPublic],
    status_code=status.HTTP_200_OK,
    summary="Search and list products",
)
async def list_products(
    service: CatalogueServiceDep,
    q: str | None = Query(None, max_length=100),
    category_id: int | None = Query(None),
    brand_id: int | None = Query(None),
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    in_stock_only: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> Page[ProductPublic]:
    """
    Returns paginated public products matching filters.
    """
    query = ProductQuery(
        q=q,
        category_id=category_id,
        brand_id=brand_id,
        min_price=min_price,
        max_price=max_price,
        in_stock_only=in_stock_only,
        page=page,
        per_page=per_page,
    )
    return await service.search_public(query)


@router.get(
    "/products/{product_id}",
    response_model=ProductPublic,
    status_code=status.HTTP_200_OK,
    summary="Get product detail",
)
async def get_product(
    product_id: int,
    service: CatalogueServiceDep,
) -> ProductPublic:
    """
    Returns public product details by id.
    """
    return await service.get_public(product_id)


@router.get(
    "/products/{product_id}/related",
    response_model=list[ProductPublic],
    status_code=status.HTTP_200_OK,
    summary="Get related cross-sell products",
)
async def get_related_products(
    product_id: int,
    service: CatalogueServiceDep,
    limit: int = Query(6, ge=1, le=20),
) -> list[ProductPublic]:
    """
    Returns recommended products in the same category or bestsellers.
    """
    try:
        product = await service.get_public(product_id)
        cat_id = product.category_id
    except Exception:
        cat_id = None

    query = ProductQuery(category_id=cat_id, page=1, per_page=limit + 1)
    page_res = await service.search_public(query)
    related = [p for p in page_res.items if p.id != product_id][:limit]

    # If not enough in category, fetch general items
    if len(related) < limit:
        fallback_query = ProductQuery(page=1, per_page=limit + 1)
        fallback_res = await service.search_public(fallback_query)
        for p in fallback_res.items:
            if p.id != product_id and not any(r.id == p.id for r in related):
                related.append(p)
            if len(related) >= limit:
                break

    return related
