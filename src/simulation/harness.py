# src/simulation/harness.py

"""
Simulation execution harness providing:
  - InMemoryMailbox: non-invasive OTP capture from Mailer.send without external SMTP.
  - Offline Daraja Sandbox MpesaClient patch: deterministic STK initiation + webhook callbacks.
  - AgentSession: isolated HTTP client per synthetic actor with automatic DB event telemetry.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
import re
import time
from typing import Any, Callable, Coroutine
import uuid

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from config import Settings
from src.schemas import SimulationEventIn
from utilities import EAT, Mail, Mailer, MpesaClient, MpesaError, get_logger

log = get_logger(__name__)

_OTP_REGEX = re.compile(r"\b(\d{4,8})\b")


class InMemoryMailbox:
    """
    Captures outbound verification / security OTP emails dispatched via utilities.mail.Mailer.
    """

    def __init__(self) -> None:
        self._messages: dict[str, list[Mail]] = defaultdict(list)
        self.total_captured: int = 0

    def record(self, mail: Mail) -> None:
        recipient = (mail.to or "").strip().lower()
        if recipient:
            self._messages[recipient].append(mail)
            self.total_captured += 1

    def latest_code_for(self, email: str) -> str | None:
        msgs = self._messages.get(email.strip().lower(), [])
        if not msgs:
            return None
        latest = msgs[-1]
        matches = _OTP_REGEX.findall(latest.body or "")
        return matches[0] if matches else None


class AgentSession:
    """
    Represents an isolated HTTP session for one autonomous simulation agent,
    automatically timing and persisting every operational action to `simulation_events`.
    """

    def __init__(
        self,
        *,
        app: FastAPI,
        actor_role: str,
        actor_subrole: str,
        agent_code: str,
        event_sink: Callable[[SimulationEventIn], Coroutine[Any, Any, None]],
    ):
        self.app = app
        self.actor_role = actor_role
        self.actor_subrole = actor_subrole
        self.agent_code = agent_code
        self._event_sink = event_sink

        self.user_id: int | None = None
        self.profile_id: int | None = None  # customer_id, rider_id, staff_id, or admin_id
        self.access_token: str | None = None
        self.session_id: str = f"sess-{agent_code}-01"
        self.session_counter: int = 1

        transport = ASGITransport(app=app)
        self.client = AsyncClient(transport=transport, base_url="http://bansigo.sim")

    def rotate_session(self) -> str:
        """Creates a fresh logical browsing/working session ID for multi-session actor activity."""
        self.session_counter += 1
        self.session_id = f"sess-{self.agent_code}-{self.session_counter:02d}-{uuid.uuid4().hex[:6]}"
        return self.session_id

    def set_token(self, token: str) -> None:
        self.access_token = token
        self.client.headers["Authorization"] = f"Bearer {token}"

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        phase: str,
        action: str,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        payload_summary: dict[str, Any] | None = None,
        record_event: bool = True,
        **kwargs: Any,
    ):
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Accept", "application/json")
        headers.setdefault("X-Simulation-Agent", self.agent_code)
        headers.setdefault("X-Simulation-Session", self.session_id)

        t0 = time.perf_counter()
        resp = await self.client.request(method, endpoint, headers=headers, **kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if record_event:
            await self._event_sink(
                SimulationEventIn(
                    phase=phase,
                    actor_role=self.actor_role,
                    actor_subrole=self.actor_subrole,
                    actor_user_id=self.user_id,
                    session_id=self.session_id,
                    action=action,
                    http_method=method.upper(),
                    endpoint=endpoint[:180],
                    http_status=resp.status_code,
                    latency_ms=latency_ms,
                    entity_type=entity_type,
                    entity_id=str(entity_id) if entity_id is not None else None,
                    payload_summary=payload_summary,
                )
            )
        return resp

    async def aclose(self) -> None:
        await self.client.aclose()


class SimulationHarness:
    """
    Context manager patching external network side effects (SMTP & live Safaricom HTTP)
    while keeping 100% of FastAPI routes, authentication, HMAC tokens, and database transactions real.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.mailbox = InMemoryMailbox()

    def build_stk_callback_url(self) -> str:
        secret = (
            self.settings.mpesa_callback_secret.get_secret_value()
            if self.settings.mpesa_callback_secret
            else ""
        )
        if secret:
            return f"/api/payments/mpesa/stk-callback/{secret}"
        return "/api/payments/mpesa/stk-callback"

    def build_c2b_confirmation_url(self) -> str:
        secret = (
            self.settings.mpesa_callback_secret.get_secret_value()
            if self.settings.mpesa_callback_secret
            else ""
        )
        if secret:
            return f"/api/payments/mpesa/c2b/confirmation/{secret}"
        return "/api/payments/mpesa/c2b/confirmation"

    def trusted_safaricom_headers(self) -> dict[str, str]:
        if self.settings.mpesa_callback_ips:
            return {"cf-connecting-ip": self.settings.mpesa_callback_ips[0]}
        return {"cf-connecting-ip": "196.201.214.200"}

    @staticmethod
    def eat_timestamp_int() -> int:
        return int(datetime.now(EAT).strftime("%Y%m%d%H%M%S"))

    @staticmethod
    def eat_timestamp_str() -> str:
        return datetime.now(EAT).strftime("%Y%m%d%H%M%S")

    @asynccontextmanager
    async def activate(self):
        orig_mail_send = Mailer.send
        orig_stk_push = MpesaClient.stk_push
        orig_stk_query = MpesaClient.stk_query
        orig_suppress = self.settings.mail_suppress_send
        orig_mpesa_env = self.settings.mpesa_env
        mailbox = self.mailbox

        async def _patched_mail_send(mailer_self: Mailer, mail: Mail) -> bool:
            mailbox.record(mail)
            log.info("SIM_MAILBOX captured -> %s | %s", mail.to, mail.subject)
            return True

        async def _patched_stk_push(mpesa_self: MpesaClient, **kwargs: Any) -> dict[str, Any]:
            # Triggers PaymentService's built-in sandbox simulation branch immediately without external TCP timeout
            raise MpesaError("M-Pesa credentials are not configured (simulation sandbox)")

        async def _patched_stk_query(mpesa_self: MpesaClient, checkout_request_id: str) -> dict[str, Any]:
            return {
                "ResponseCode": "0",
                "ResponseDescription": "The service request has been accepted successfully",
                "MerchantRequestID": "SIM-MERCHANT",
                "CheckoutRequestID": checkout_request_id,
                "ResultCode": "0",
                "ResultDesc": "The service request is processed successfully.",
            }

        Mailer.send = _patched_mail_send  # type: ignore[assignment]
        MpesaClient.stk_push = _patched_stk_push  # type: ignore[assignment]
        MpesaClient.stk_query = _patched_stk_query  # type: ignore[assignment]
        self.settings.mail_suppress_send = True
        self.settings.mpesa_env = "sandbox"

        try:
            yield self
        finally:
            Mailer.send = orig_mail_send  # type: ignore[assignment]
            MpesaClient.stk_push = orig_stk_push  # type: ignore[assignment]
            MpesaClient.stk_query = orig_stk_query  # type: ignore[assignment]
            self.settings.mail_suppress_send = orig_suppress
            self.settings.mpesa_env = orig_mpesa_env
