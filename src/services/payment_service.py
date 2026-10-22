# src/services/payment_service.py

"""
M-Pesa + cash, built around ONE rule: money state changes only from facts we can trust, exactly once.

STK Push flow
    1. initiate_stk()      Payment(INITIATED) is committed BEFORE Daraja is called (we can always explain a prompt),
                           then Daraja is called, then Payment becomes PENDING with Daraja's ids
    2. handle_stk_callback Daraja posts the result. The raw body is stored FIRST (insert-first idempotency on the
                           UNIQUE (source, external_id) pair), so a replayed callback cannot pay an order twice
    3. resolve_stuck()     SWEEPER for prompts that never got a callback: asks Daraja's STK Query (authoritative)

Trust rules
    * a callback is applied only if it comes from a Safaricom address (settings.mpesa_callback_ips) AND, in the
      router, carries our secret URL token. Anything else is stored but left unprocessed for a human
    * the callback amount must equal the Payment amount (else: stored, flagged, order NOT confirmed)
    * the order is confirmed only inside the same transaction that marks the payment SUCCEEDED
    * a payment that lands on an already-cancelled order is kept and a refund is requested automatically

Known gap: if the push request itself times out we mark the attempt FAILED, but the prompt MAY have reached the
phone. A late callback then arrives with a CheckoutRequestID we never stored: it lands in the event table
unmatched (processed_at NULL, see PaymentEventRepository.list_unprocessed) for manual reconciliation.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from src.exceptions import AppError, BusinessRuleError, ConflictError, NotFoundError, ProviderError
from src.models import (
    Customer, OrderPaymentStatus, OrderStatus, Payment, PaymentChannel, PaymentEvent, PaymentEventSource,
    PaymentMethod, PaymentStatus, User,
)
from src.repositories import PaymentEventRepository, PaymentRepository
from src.schemas import C2BAck, C2BNotification, StkCallbackEnvelope, StkPushRequest
from utilities import EAT, STILL_PROCESSING, MpesaClient, MpesaError, get_logger, utc_now

from services.order_service import OrderService, payable_amount
from .refund_service import RefundService

log = get_logger(__name__)

# Daraja result codes that mean the customer did not pay
_RESULT_STATUS = {1032: PaymentStatus.CANCELLED, 1037: PaymentStatus.TIMEOUT}


def parse_daraja_time(value: str | int) -> datetime:
    """Daraja stamps yyyyMMddHHmmss in East Africa Time; we store UTC"""
    return datetime.strptime(str(value), "%Y%m%d%H%M%S").replace(tzinfo=EAT).astimezone(timezone.utc)


class PaymentService:
    def __init__(self, db: AsyncSession, settings: Settings, mpesa: MpesaClient | None = None):
        """
        :param mpesa: None for flows that never call Daraja (cash, callbacks)
        """
        self.db = db
        self.settings = settings
        self.mpesa = mpesa
        self.payments = PaymentRepository(db)
        self.events = PaymentEventRepository(db)
        self.orders = OrderService(db, settings)
        self.refunds = RefundService(db)


    # 1. customer taps 'Pay with M-Pesa'
    async def initiate_stk(self, customer: Customer, user: User, order_id: int, data: StkPushRequest) -> Payment:
        if self.mpesa is None:
            raise ProviderError()

        order = await self.orders.get_locked(order_id)
        if order.customer_id != customer.id:
            raise NotFoundError("Order not found")

        # a retry of the same tap returns the same attempt
        existing = await self.payments.get_by_idempotency_key(data.idempotency_key)
        if existing is not None:
            if existing.order_id != order.id:
                raise ConflictError(["idempotency_key"])
            return existing

        if order.payment_method is not PaymentMethod.MPESA or order.status is not OrderStatus.PENDING_PAYMENT:
            raise BusinessRuleError("This order is not awaiting an M-Pesa payment")

        now = utc_now()
        if any(p.status in (PaymentStatus.INITIATED, PaymentStatus.PENDING) and p.expires_at and p.expires_at > now
               for p in order.payments):
            raise BusinessRuleError("A payment prompt is already open on your phone. Complete it or wait for it to expire")

        amount = payable_amount(order)
        if amount != amount.to_integral_value():
            raise AppError("This order total is not a whole-shilling amount; it cannot be paid through M-Pesa")

        phone = data.phone or user.phone                    # +2547XXXXXXXX
        payment = Payment(
            order_id=order.id, initiated_by=user.id, channel=PaymentChannel.MPESA_STK,
            status=PaymentStatus.INITIATED, amount=amount, idempotency_key=data.idempotency_key,
            payer_phone=phone, expires_at=now + timedelta(seconds=self.settings.mpesa_stk_window_seconds),
        )
        self.db.add(payment)
        await self.db.commit()          # the attempt exists on record BEFORE we ask Daraja

        try:
            reply = await self.mpesa.stk_push(
                phone=phone.lstrip("+"), amount=amount, account_reference=order.order_number,
                description="BansiGo",
            )
        except MpesaError as exc:
            payment.status = PaymentStatus.FAILED
            payment.result_description = str(exc)[:255]
            await self.db.commit()
            log.warning("STK push failed for %s: %s", order.order_number, exc)
            raise ProviderError() from exc

        payment.status = PaymentStatus.PENDING
        payment.provider_merchant_request_id = reply.get("MerchantRequestID")
        payment.provider_checkout_request_id = reply.get("CheckoutRequestID")
        await self.db.commit()
        return payment


    # 2. Daraja's STK callback
    def is_safaricom_address(self, ip: str | None) -> bool:
        allow = self.settings.mpesa_callback_ips
        return not allow or (ip is not None and ip in allow)     # an empty allowlist = sandbox/dev

    async def handle_stk_callback(self, envelope: StkCallbackEnvelope, raw: dict, source_ip: str | None) -> None:
        """
        never raises: Daraja only needs a 200. Failures are recorded on the event row for the sweeper / a human
        """
        cb = envelope.Body.stkCallback
        event, is_new = await self.events.add_if_new(PaymentEvent(
            source=PaymentEventSource.STK_CALLBACK, external_id=cb.CheckoutRequestID, payload=raw,
            source_ip=source_ip, is_authentic=self.is_safaricom_address(source_ip),
        ))
        event_id = event.id
        await self.db.commit()                      # the raw body is safe from here on, whatever happens next

        if not is_new and event.processed_at is not None:
            return                                  # a replay of something already handled

        try:
            await self._apply_stk_result(event_id, cb)
            await self.db.commit()
        except Exception as exc:                    # noqa: BLE001 - must not bubble to Daraja
            await self.db.rollback()
            log.exception("could not apply STK callback %s", cb.CheckoutRequestID)
            stored = await self.events.get_by_id(event_id)
            stored.processing_error = f"{type(exc).__name__}: {exc}"[:500]
            await self.db.commit()


    async def _apply_stk_result(self, event_id: int, cb) -> None:
        event = await self.events.get_by_id(event_id)
        now = utc_now()

        payment = await self.payments.get_by_checkout_id(cb.CheckoutRequestID, for_update=True)
        if payment is None:
            event.processing_error = "no payment matches this CheckoutRequestID"
            return                                  # left unprocessed on purpose: a human must look
        event.payment_id = payment.id

        if not event.is_authentic:
            event.processing_error = "callback did not come from a Safaricom address; not applied"
            return

        if payment.status is PaymentStatus.SUCCEEDED:
            event.processed_at = now                # already settled; nothing to do
            return

        payment.result_code = cb.ResultCode
        payment.result_description = cb.ResultDesc[:255]

        if cb.ResultCode == 0:
            meta = cb.metadata()
            settled = await self._settle(
                payment, event=event, amount=meta.get("Amount"), receipt=meta.get("MpesaReceiptNumber"),
                paid_at=parse_daraja_time(meta["TransactionDate"]) if meta.get("TransactionDate") else now,
                phone=str(meta["PhoneNumber"]) if meta.get("PhoneNumber") else None,
            )
            if not settled:
                return                              # mismatch flagged on the event; stays for a human
        else:
            # a late success can still arrive after this (the settle path accepts any non-SUCCEEDED state)
            payment.status = _RESULT_STATUS.get(cb.ResultCode, PaymentStatus.FAILED)

        event.processed_at = now


    async def _settle(
        self, payment: Payment, *, event: PaymentEvent | None, amount, receipt: str | None,
        paid_at: datetime, phone: str | None,
    ) -> bool:
        """
        the ONE place a payment becomes SUCCEEDED and moves its order. Returns False (and flags the event) when
        the facts do not add up, in which case nothing is confirmed
        """
        try:
            received = Decimal(str(amount)) if amount is not None else None
        except InvalidOperation:
            received = None

        if not receipt or received is None or received != payment.amount:
            msg = f"amount/receipt mismatch: expected {payment.amount}, got {amount!r}, receipt {receipt!r}"
            log.error("payment %s: %s", payment.id, msg)
            if event is not None:
                event.processing_error = msg
            return False

        payment.status = PaymentStatus.SUCCEEDED
        payment.provider_receipt = receipt
        payment.paid_at = paid_at
        if phone:
            payment.payer_phone = phone[:30]

        order = await self.orders.get_locked(payment.order_id)
        if order.status is OrderStatus.CANCELLED:
            # the customer paid after we cancelled (or after the order expired): keep the money trail, give it back
            order.payment_status = OrderPaymentStatus.PAID
            await self.refunds.request_for_order(
                order, actor_id=None, reason="Payment received after the order was cancelled"
            )
        else:
            await self.orders.confirm_paid(order)
        return True


    # 3. sweeper
    async def resolve_stuck(self, limit: int = 50) -> int:
        """
        SWEEPER: prompts past their window that never produced a callback. Asks Daraja's STK Query.
        NOTE: the query reports paid/not paid but carries NO receipt number, so a payment confirmed this way is
        SUCCEEDED with provider_receipt NULL (to be filled by the transaction report / C2B confirmation).
        :return: int  how many payments were resolved
        """
        if self.mpesa is None:
            raise ProviderError()

        resolved = 0
        now = utc_now()
        for stale in await self.payments.list_stale_pending(now, limit):
            if not stale.provider_checkout_request_id:
                stale.status = PaymentStatus.FAILED
                stale.result_description = "no CheckoutRequestID (push never accepted)"
                await self.db.commit()
                resolved += 1
                continue

            try:
                reply = await self.mpesa.stk_query(stale.provider_checkout_request_id)
            except MpesaError as exc:
                if exc.code == STILL_PROCESSING and now < stale.expires_at + timedelta(minutes=5):
                    continue                        # the customer is still deciding; look again next sweep
                if exc.code == STILL_PROCESSING:
                    stale.status = PaymentStatus.TIMEOUT
                    await self.db.commit()
                    resolved += 1
                continue                            # Daraja unreachable: try again next sweep

            payment = await self.payments.get_by_checkout_id(stale.provider_checkout_request_id, for_update=True)
            if payment.status is PaymentStatus.SUCCEEDED:
                continue

            code = int(reply.get("ResultCode", -1))
            payment.result_code = code
            payment.result_description = str(reply.get("ResultDesc", ""))[:255]
            if code == 0:
                payment.status = PaymentStatus.SUCCEEDED
                payment.paid_at = now
                order = await self.orders.get_locked(payment.order_id)
                if order.status is OrderStatus.CANCELLED:
                    order.payment_status = OrderPaymentStatus.PAID
                    await self.refunds.request_for_order(order, actor_id=None, reason="Payment received after cancellation")
                else:
                    await self.orders.confirm_paid(order)
            else:
                payment.status = _RESULT_STATUS.get(code, PaymentStatus.FAILED)

            await self.db.commit()
            resolved += 1
        return resolved


    # C2B: the customer pays our till/paybill themselves, quoting the order number
    async def validate_c2b(self, notif: C2BNotification) -> C2BAck:
        """
        Daraja asks 'should I accept this payment?' BEFORE taking the money.
        (Only used when C2B validation is enabled on the shortcode.)
        """
        order = await self.orders.orders.get_by_number(notif.BillRefNumber.strip().upper())
        if order is None or order.status is not OrderStatus.PENDING_PAYMENT:
            return C2BAck(ResultCode="C2B00012", ResultDesc="Rejected")          # invalid account number
        if notif.TransAmount != order.total:
            return C2BAck(ResultCode="C2B00013", ResultDesc="Rejected")          # invalid amount
        return C2BAck()


    async def handle_c2b_confirmation(self, notif: C2BNotification, raw: dict, source_ip: str | None) -> None:
        """
        the money HAS moved. Always recorded; the order is confirmed only when everything matches,
        otherwise the payment waits for staff to match it by hand (and that is audited)
        """
        event, is_new = await self.events.add_if_new(PaymentEvent(
            source=PaymentEventSource.C2B_CONFIRMATION, external_id=notif.TransID, payload=raw,
            source_ip=source_ip, is_authentic=self.is_safaricom_address(source_ip),
        ))
        event_id = event.id
        await self.db.commit()
        if not is_new and event.processed_at is not None:
            return

        try:
            event = await self.events.get_by_id(event_id)
            if not event.is_authentic:
                event.processing_error = "confirmation did not come from a Safaricom address; not applied"
                await self.db.commit()
                return

            order = await self.orders.orders.get_by_number(notif.BillRefNumber.strip().upper())
            if order is None:
                event.processing_error = f"no order numbered {notif.BillRefNumber!r}; match manually"
                await self.db.commit()
                return

            payment = Payment(
                order_id=order.id, channel=PaymentChannel.MPESA_C2B, status=PaymentStatus.SUCCEEDED,
                amount=notif.TransAmount, idempotency_key=f"c2b:{notif.TransID}",
                provider_receipt=notif.TransID, result_code=0, paid_at=parse_daraja_time(notif.TransTime),
                # newer Daraja versions send a 64-char hash instead of the number: it does not fit, so skip it
                payer_phone=notif.MSISDN if notif.MSISDN and len(notif.MSISDN) <= 30 else None,
            )
            self.db.add(payment)
            await self.db.flush()
            event.payment_id = payment.id

            locked = await self.orders.get_locked(order.id)
            if locked.status is OrderStatus.CANCELLED:
                locked.payment_status = OrderPaymentStatus.PAID
                await self.refunds.request_for_order(locked, actor_id=None, reason="Payment received after cancellation")
            elif locked.status is OrderStatus.PENDING_PAYMENT and notif.TransAmount == locked.total:
                await self.orders.confirm_paid(locked)
            else:
                event.processing_error = "paid amount/state does not match the order; match manually"
                await self.db.commit()
                return                              # money recorded, order untouched

            event.processed_at = utc_now()
            await self.db.commit()
        except Exception as exc:                    # noqa: BLE001
            await self.db.rollback()
            log.exception("could not apply C2B confirmation %s", notif.TransID)
            stored = await self.events.get_by_id(event_id)
            stored.processing_error = f"{type(exc).__name__}: {exc}"[:500]
            await self.db.commit()


    # cash
    async def record_cash(self, order_id: int, amount: Decimal, actor: User) -> Payment:
        """
        a rider (at the door) or cashier (at pickup) received cash. Must equal what the customer owes
        """
        order = await self.orders.get_locked(order_id)
        if order.payment_method is not PaymentMethod.CASH:
            raise BusinessRuleError("This order is not a cash order")
        if order.payment_status is OrderPaymentStatus.PAID:
            raise BusinessRuleError("This order is already paid")
        if order.status is OrderStatus.CANCELLED:
            raise BusinessRuleError("This order was cancelled")

        owed = payable_amount(order)
        if amount != owed:
            raise BusinessRuleError(f"Cash collected must be exactly KES {owed}")

        payment = Payment(
            order_id=order.id, initiated_by=actor.id, channel=PaymentChannel.CASH, status=PaymentStatus.SUCCEEDED,
            amount=owed, idempotency_key=f"cash:{order.order_number}", paid_at=utc_now(), result_code=0,
        )
        self.db.add(payment)
        order.payment_status = OrderPaymentStatus.PAID
        await self.db.commit()
        return payment
