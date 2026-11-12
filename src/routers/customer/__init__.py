# src/routers/customer/__init__.py

from fastapi import APIRouter
from .addresses import router as customer_addresses_router
from .catalogue import router as customer_catalogue_router
from .delivery import router as customer_delivery_router
from .notifications import router as customer_notifications_router
from .orders import router as customer_orders_router
from .recommendations import router as customer_recommendations_router

customer_router = APIRouter()
customer_router.include_router(customer_addresses_router)
customer_router.include_router(customer_catalogue_router)
customer_router.include_router(customer_delivery_router)
customer_router.include_router(customer_notifications_router)
customer_router.include_router(customer_orders_router)
customer_router.include_router(customer_recommendations_router)

__all__ = ["customer_router"]
