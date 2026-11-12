# src/routers/rider/__init__.py

from fastapi import APIRouter
from .deliveries import router as rider_deliveries_router

rider_router = APIRouter()
rider_router.include_router(rider_deliveries_router)

__all__ = ["rider_router"]
