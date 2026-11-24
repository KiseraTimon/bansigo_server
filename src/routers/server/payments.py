# src/routers/server/payments.py

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from config import Settings
from src.dependencies import SettingsDep, get_payment_service
from src.exceptions import ForbiddenError
from src.schemas import C2BAck, C2BNotification, DarajaAck, StkCallbackEnvelope
from src.services import PaymentService
from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/mpesa", tags=["mpesa-callbacks"])
PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _verify_callback_secret(settings: Settings, provided: str | None) -> None:
    expected = settings.mpesa_callback_secret.get_secret_value() if settings.mpesa_callback_secret else None
    if expected:
        if not provided or not hmac.compare_digest(provided, expected):
            raise ForbiddenError("Invalid callback token")


@router.get("/health", status_code=status.HTTP_200_OK, summary="Verify M-Pesa callback tunnel reachability")
async def mpesa_callback_health() -> dict:
    return {"status": "ok", "service": "bansigo-mpesa-callbacks"}


@router.post("/stk-callback", response_model=DarajaAck, status_code=status.HTTP_200_OK)
@router.post("/stk-callback/{callback_secret}", response_model=DarajaAck, status_code=status.HTTP_200_OK)
async def stk_callback(
    request: Request,
    envelope: StkCallbackEnvelope,
    settings: SettingsDep,
    payments: PaymentServiceDep,
    callback_secret: str | None = None,
) -> DarajaAck:
    _verify_callback_secret(settings, callback_secret)
    raw = await request.json()
    await payments.handle_stk_callback(envelope, raw, _client_ip(request))
    return DarajaAck()


@router.post("/c2b/validation", response_model=C2BAck, status_code=status.HTTP_200_OK)
@router.post("/c2b/validation/{callback_secret}", response_model=C2BAck, status_code=status.HTTP_200_OK)
async def c2b_validation(
    notif: C2BNotification,
    settings: SettingsDep,
    payments: PaymentServiceDep,
    callback_secret: str | None = None,
) -> C2BAck:
    _verify_callback_secret(settings, callback_secret)
    return await payments.validate_c2b(notif)


@router.post("/c2b/confirmation", response_model=C2BAck, status_code=status.HTTP_200_OK)
@router.post("/c2b/confirmation/{callback_secret}", response_model=C2BAck, status_code=status.HTTP_200_OK)
async def c2b_confirmation(
    request: Request,
    notif: C2BNotification,
    settings: SettingsDep,
    payments: PaymentServiceDep,
    callback_secret: str | None = None,
) -> C2BAck:
    _verify_callback_secret(settings, callback_secret)
    raw = await request.json()
    await payments.handle_c2b_confirmation(notif, raw, _client_ip(request))
    return C2BAck()
