# src/routers/__init__.py

from fastapi import APIRouter

from src.routers.server.auth import router as server_auth_router
from src.routers.server.profiles import router as server_profiles_router


# router object
router = APIRouter()


# related routers
router.include_router(server_auth_router, prefix="/api/auth", tags=["auth"])   # auth ops
router.include_router(server_profiles_router, prefix="/api/users", tags=["users"])    # profile ops
