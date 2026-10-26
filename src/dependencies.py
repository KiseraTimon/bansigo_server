# src/dependencies.py

import hmac
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings, get_settings
from src.database import get_db
from src.exceptions import ForbiddenError, UnauthorizedError
from src.models import Admin, AdminLevel, Customer, User, UserRole
from src.repositories import AdminRepository, CustomerRepository, UserRepository
from src.security import decode_access_token
from src.services import (
    AddressService, AdminService, AuthService, CatalogueService, DeliveryService, InventoryService, OrderService,
    PaymentService, RefundService, RiderService, UserService, VerificationService,
)

from utilities import Mailer, MpesaClient


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# service factories
def get_auth_service(settings: SettingsDep, db: DbSession) -> AuthService:
    return AuthService(db, settings)


def get_user_service(db: DbSession) -> UserService:
    return UserService(db)


def get_verification_service(settings: SettingsDep, db: DbSession) -> VerificationService:
    return VerificationService(db, settings)


def get_mailer(settings: SettingsDep) -> Mailer:
    return Mailer(settings)


def get_catalogue_service(db: DbSession) -> CatalogueService:
    return CatalogueService(db)


def get_inventory_service(db: DbSession) -> InventoryService:
    return InventoryService(db)


def get_address_service(db: DbSession) -> AddressService:
    return AddressService(db)


def get_order_service(settings: SettingsDep, db: DbSession) -> OrderService:
    return OrderService(db, settings)


def get_refund_service(db: DbSession) -> RefundService:
    return RefundService(db)


def get_rider_service(db: DbSession) -> RiderService:
    return RiderService(db)


def get_delivery_service(settings: SettingsDep, db: DbSession) -> DeliveryService:
    return DeliveryService(db, settings)


def get_admin_service(settings: SettingsDep, db: DbSession) -> AdminService:
    return AdminService(db, settings)


@lru_cache
def get_mpesa_client() -> MpesaClient:
    """
    ONE client per process: it caches the Daraja OAuth token and keeps a connection pool.
    Close it on shutdown (see lifespan in src/__init__.py)
    """
    return MpesaClient(get_settings())


def get_payment_service(
    settings: SettingsDep, db: DbSession, mpesa: Annotated[MpesaClient, Depends(get_mpesa_client)]
) -> PaymentService:
    return PaymentService(db, settings, mpesa)


# authentication
async def get_current_user(
        token: Annotated[str, Depends(oauth2_scheme)],
        settings: SettingsDep,
        db: DbSession
) -> User:
    """
    resolves the active user using the token
    :param token: OAuth2PasswordBearer
    :param settings: Settings
    :param db: AsyncSession
    :return:
    """

    try:
        payload = decode_access_token(token, settings.secret_key.get_secret_value())
        user_id = int(payload["sub"])

    except (jwt.PyJWTError, KeyError, ValueError):
        raise UnauthorizedError()

    user = await UserRepository(db).get_by_id(user_id)
    if (user is None) or (not user.is_active) or (user.deleted_at is not None):
        raise UnauthorizedError()

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """
    role gate for child models
    usage: user: Annotated[User, Depends(require_roles(UserRole.STAFF, UserRole.ADMIN))]
    :param roles: UserRole
    :return:
    """

    async def checker(user: CurrentUser) -> User:
        """
        :param user: CurrentUser
        :return: User
        """
        if user.role not in roles:
            raise ForbiddenError()

        return user

    return checker


async def get_current_customer(
    user: Annotated[User, Depends(require_roles(UserRole.CUSTOMER))], db: DbSession
) -> Customer:
    """
    the Customer profile row behind a CUSTOMER user (orders, addresses and payments hang off it, not off User)
    """
    customer = await CustomerRepository(db).get_by_user_id(user.id)
    if customer is None:
        raise ForbiddenError("This account has no customer profile")
    return customer


CurrentCustomer = Annotated[Customer, Depends(get_current_customer)]


async def get_current_admin(
    request: Request,
    settings: SettingsDep,
    db: DbSession,
) -> tuple[User, Admin]:
    """
    resolves the active administrator via Authorization header or session cookie
    """
    token: str | None = None
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    elif "access_token" in request.cookies:
        token = request.cookies.get("access_token")

    if not token:
        raise UnauthorizedError("Authentication credentials not provided")

    try:
        payload = decode_access_token(token, settings.secret_key.get_secret_value())
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise UnauthorizedError("Invalid or expired session token")

    user = await UserRepository(db).get_by_id(user_id)
    if (user is None) or (not user.is_active) or (user.deleted_at is not None):
        raise UnauthorizedError("User account not active")

    if user.role != UserRole.ADMIN:
        raise ForbiddenError("Administrative privileges required")

    admin = await AdminRepository(db).get_by_user_id(user.id)
    if admin is None:
        # Default or bootstrap to SUPER for first admin or OPERATIONS
        admin = Admin(user_id=user.id, level=AdminLevel.SUPER)
        db.add(admin)
        await db.commit()
        await db.refresh(admin)

    return user, admin


CurrentAdmin = Annotated[tuple[User, Admin], Depends(get_current_admin)]


def require_admin_level(*levels: AdminLevel):
    """
    privilege gate ensuring an administrator holds required authority (e.g. SUPER)
    """
    async def checker(admin_tuple: CurrentAdmin) -> tuple[User, Admin]:
        _, admin = admin_tuple
        if admin.level not in levels:
            raise ForbiddenError("Insufficient administrator privileges for this operation")
        return admin_tuple

    return checker


# Daraja callbacks (no user logs in: these requests come from Safaricom)
def verify_callback_secret(secret: str, settings: SettingsDep) -> None:
    """
    Daraja cannot sign its callbacks, so the URL we register carries a long random token:
        https://api.example.com/api/payments/mpesa/{secret}/stk
    A wrong token is a 404 (no hint that the route exists). Combine with the source-IP allowlist in PaymentService.
    """
    expected = settings.mpesa_callback_secret.get_secret_value() if settings.mpesa_callback_secret else ""
    if not expected or not hmac.compare_digest(secret, expected):
        raise HTTPException(status.HTTP_404_NOT_FOUND)


def get_source_ip(request: Request) -> str | None:
    """
    the caller's address for the allowlist.
    Behind Cloudflare the real client is in CF-Connecting-IP. Only trust that header if the origin is reachable
    ONLY through Cloudflare, otherwise anyone can forge it.
    """
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else None)
