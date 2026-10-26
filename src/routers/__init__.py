# src/routers/__init__.py

from fastapi import APIRouter

from config import get_settings
from src.routers.server import (
    admin_router,
    server_auth_router,
    server_profiles_router,
)

# router object
router = APIRouter()

# public API routers
router.include_router(server_auth_router, prefix="/api/auth", tags=["auth"])   # auth ops
router.include_router(server_profiles_router, prefix="/api/users", tags=["users"])    # profile ops

# internal/back-office admin console (hidden from schemas, no /api prefix, obfuscated path)
settings = get_settings()
admin_portal_prefix = f"/{settings.admin_portal_path.strip('/')}/admin"
router.include_router(admin_router, prefix=admin_portal_prefix, include_in_schema=False)
