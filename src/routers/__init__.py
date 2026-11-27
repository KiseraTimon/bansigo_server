# src/routers/__init__.py

from fastapi import APIRouter

from config import get_settings
from src.routers.customer import customer_router
from src.routers.rider import rider_router
from src.routers.server import (
    admin_router,
    mpesa_callbacks_router,
    server_auth_router,
    server_profiles_router,
    staff_router,
)

# router object
router = APIRouter()

# public API routers
router.include_router(server_auth_router, prefix="/api/auth", tags=["auth"])   # auth ops
router.include_router(server_profiles_router, prefix="/api/users", tags=["users"])    # profile ops
router.include_router(mpesa_callbacks_router, prefix="/api/payments", tags=["payments"])  # Daraja callbacks
router.include_router(customer_router, prefix="/api/customer", tags=["customer"])    # customer ops
router.include_router(rider_router, prefix="/api/rider", tags=["rider"])    # rider ops

# internal/back-office admin & staff consoles (hidden from schemas, no /api prefix, obfuscated path)
settings = get_settings()
admin_portal_prefix = f"/{settings.admin_portal_path.strip('/')}/admin"
staff_portal_prefix = f"/{settings.admin_portal_path.strip('/')}/staff"
router.include_router(admin_router, prefix=admin_portal_prefix, include_in_schema=False)
router.include_router(staff_router, prefix=staff_portal_prefix, include_in_schema=False)
