# utilities/mpesa.py

"""
thin async client for Safaricom Daraja (STK Push + STK Query).

It ONLY talks to Daraja. It never touches the database; PaymentService owns every state change.
Create ONE instance per process (see get_mpesa_client in dependencies.py) so the OAuth token is cached.

Daraja facts this relies on:
    - amounts are whole shillings
    - AccountReference is at most 12 chars (an order number is exactly 12)
    - timestamps in callbacks are East Africa Time (UTC+3), NOT UTC
"""

import asyncio
import base64
import time
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from config import Settings

EAT = ZoneInfo("Africa/Nairobi")

_BASES = {
    "sandbox": "https://sandbox.safaricom.co.ke",
    "production": "https://api.safaricom.co.ke",
}

# the status query answers this while the customer is still looking at the prompt
STILL_PROCESSING = "500.001.1001"


class MpesaError(Exception):
    """raised for any Daraja failure; `code` carries Daraja's errorCode when there is one"""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class MpesaClient:
    def __init__(self, settings: Settings):
        """
        constructor
        :param settings: Settings
        """
        self.s = settings
        self._http = httpx.AsyncClient(base_url=_BASES[settings.mpesa_env], timeout=settings.mpesa_http_timeout)
        self._token: str | None = None
        self._token_expiry = 0.0
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    # internals
    def _timestamp(self) -> str:
        return datetime.now(EAT).strftime("%Y%m%d%H%M%S")

    def _password(self, timestamp: str) -> str:
        passkey = self.s.mpesa_passkey.get_secret_value() if self.s.mpesa_passkey else ""
        return base64.b64encode(f"{self.s.mpesa_shortcode}{passkey}{timestamp}".encode()).decode()

    async def _access_token(self) -> str:
        async with self._lock:
            if self._token and time.monotonic() < self._token_expiry:
                return self._token

            if not (self.s.mpesa_consumer_key and self.s.mpesa_consumer_secret):
                raise MpesaError("M-Pesa credentials are not configured")

            try:
                resp = await self._http.get(
                    "/oauth/v1/generate",
                    params={"grant_type": "client_credentials"},
                    auth=(
                        self.s.mpesa_consumer_key.get_secret_value(),
                        self.s.mpesa_consumer_secret.get_secret_value(),
                    ),
                )
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise MpesaError(f"could not obtain a Daraja token: {exc}") from exc

            self._token = data["access_token"]
            self._token_expiry = time.monotonic() + int(data.get("expires_in", 3599)) - 60
            return self._token

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        token = await self._access_token()
        try:
            resp = await self._http.post(path, json=body, headers={"Authorization": f"Bearer {token}"})
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            # NOTE: a timeout here is ambiguous (the prompt may or may not have been sent); never auto-retry a push
            raise MpesaError(f"Daraja request failed: {exc}") from exc

        if resp.status_code >= 400 or "errorCode" in data:
            raise MpesaError(data.get("errorMessage", "Daraja rejected the request"), code=data.get("errorCode"))
        return data

    # public API
    async def stk_push(
        self, *, phone: str, amount: Decimal, account_reference: str, description: str
    ) -> dict[str, Any]:
        """
        asks Daraja to prompt `phone` for `amount`
        :param phone: str   254XXXXXXXXX (no '+')
        :param amount: Decimal   whole shillings
        :param account_reference: str   <= 12 chars
        :param description: str
        :return: dict   MerchantRequestID, CheckoutRequestID, ResponseCode, CustomerMessage
        """
        if amount != amount.to_integral_value():
            raise MpesaError("STK Push only accepts whole shillings")

        ts = self._timestamp()
        data = await self._post("/mpesa/stkpush/v1/processrequest", {
            "BusinessShortCode": self.s.mpesa_shortcode,
            "Password": self._password(ts),
            "Timestamp": ts,
            "TransactionType": self.s.mpesa_transaction_type,
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": self.s.mpesa_party_b or self.s.mpesa_shortcode,
            "PhoneNumber": phone,
            "CallBackURL": self.s.mpesa_callback_url,
            "AccountReference": account_reference[:12],
            "TransactionDesc": description[:13],
        })

        if str(data.get("ResponseCode")) != "0":
            raise MpesaError(data.get("ResponseDescription", "STK push was not accepted"))
        return data

    async def stk_query(self, checkout_request_id: str) -> dict[str, Any]:
        """
        asks Daraja what happened to a push. ResultCode "0" = paid. NOTE: carries no receipt number.
        raises MpesaError(code=STILL_PROCESSING) while the customer has not answered
        :param checkout_request_id: str
        :return: dict
        """
        ts = self._timestamp()
        return await self._post("/mpesa/stkpushquery/v1/query", {
            "BusinessShortCode": self.s.mpesa_shortcode,
            "Password": self._password(ts),
            "Timestamp": ts,
            "CheckoutRequestID": checkout_request_id,
        })
