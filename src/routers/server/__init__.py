# src/routers/server/__init__.py

from .admin import router as admin_router
from .auth import router as server_auth_router
from .profiles import router as server_profiles_router

__all__ = [
    "admin_router",
    "server_auth_router",
    "server_profiles_router",
]
