# src/services/refund_service.py

r"""
money going back to a customer: cancelled paid order, short/out-of-stock lines, weighed-goods difference.

    REQUESTED --approve--> APPROVED --(B2C sent)--> PROCESSING --(result)--> COMPLETED | FAILED
        \--reject--> REJECTED

Maker-checker: whoever requests a refund cannot approve it (also enforced by ck_refund_maker_checker).
Refunds the SYSTEM raises itself (requested_by = NULL) can be approved by any finance/admin user.

TODO (next step): the B2C send. approve() leaves the refund APPROVED; a dispatcher job will call Daraja's B2C
endpoint, set PROCESSING, and apply_result() below is what the B2C result callback must call.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from src.models import Order, OrderPaymentStatus, PaymentChannel, Refund, RefundStatus, User
from src.repositories import PaymentRepository, RefundRepository
from utilities import get_logger, utc_now

from services.audit_service import AuditService

log = get_logger(__name__)


class RefundService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.refunds = RefundRepository(db)
        self.payments = PaymentRepository(db)
        self.audit = AuditService(db)


    async def request_for_order(
        self, order: Order, *, actor_id: int | None, reason: str, amount: Decimal | None = None
    ) -> Refund | None:
        """
        stages a refund against the order's successful payment. Does NOT commit (the caller's use case does).
        :param order: Order
        :param actor_id: int | None   None = raised by the system
        :param reason: str
        :param amount: Decimal | None   None = everything still refundable
        :return: Refund | None   None when there is nothing to refund (cash, unpaid, already fully claimed)
        """
        payment = await self.payments.latest_succeeded(order.id)
        if payment is None:
            return None

        if payment.channel is PaymentChannel.CASH:
            # cash is handed back over the counter, not through M-Pesa
            log.info("order %s was paid in cash; refund must be handled manually", order.order_number)
            return None

        remaining = payment.amount - await self.refunds.sum_active(payment.id)
        amount = remaining if amount is None else min(amount, remaining)
        if amount <= 0:
            return None

        refund = Refund(payment_id=payment.id, requested_by=actor_id, amount=amount, reason=reason[:255])
        self.db.add(refund)
        await self.db.flush()
        self.audit.record(actor_id=actor_id, action="refund.requested", entity_type="refund", entity_id=refund.id,
                          after={"payment_id": payment.id, "amount": amount, "reason": reason})
        return refund


    async def request_manual(self, payment_id: int, amount: Decimal | None, reason: str, actor: User) -> Refund:
        """
        staff-initiated refund against a specific payment
        """
        payment = await self.payments.get_by_id(payment_id)
        if payment is None:
            raise NotFoundError("Payment not found")

        order = await self.db.get(Order, payment.order_id)
        refund = await self.request_for_order(order, actor_id=actor.id, reason=reason, amount=amount)
        if refund is None:
            raise BusinessRuleError("Nothing left to refund on this payment")

        await self.db.commit()
        return refund


    async def approve(self, refund_id: int, approver: User) -> Refund:
        refund = await self.refunds.get_for_update(refund_id)
        if refund is None:
            raise NotFoundError("Refund not found")
        if refund.status is not RefundStatus.REQUESTED:
            raise BusinessRuleError(f"A {refund.status.value} refund cannot be approved")
        if refund.requested_by is not None and refund.requested_by == approver.id:
            raise ForbiddenError("You cannot approve a refund you requested")

        refund.status = RefundStatus.APPROVED
        refund.approved_by = approver.id
        self.audit.record(actor_id=approver.id, action="refund.approved", entity_type="refund", entity_id=refund.id,
                          before={"status": RefundStatus.REQUESTED}, after={"status": RefundStatus.APPROVED})
        await self.db.commit()
        return refund


    async def reject(self, refund_id: int, approver: User, reason: str) -> Refund:
        refund = await self.refunds.get_for_update(refund_id)
        if refund is None:
            raise NotFoundError("Refund not found")
        if refund.status is not RefundStatus.REQUESTED:
            raise BusinessRuleError(f"A {refund.status.value} refund cannot be rejected")

        refund.status = RefundStatus.REJECTED
        refund.result_description = reason[:255]
        self.audit.record(actor_id=approver.id, action="refund.rejected", entity_type="refund", entity_id=refund.id,
                          after={"reason": reason})
        await self.db.commit()
        return refund


    async def apply_result(
        self, refund: Refund, *, success: bool, receipt: str | None, code: int | None, description: str | None
    ) -> None:
        """
        records the B2C outcome (called by the B2C result callback handler). Stages only; caller commits
        """
        refund.result_code = code
        refund.result_description = (description or "")[:255] or None
        refund.processed_at = utc_now()

        if not success:
            refund.status = RefundStatus.FAILED
            return

        refund.status = RefundStatus.COMPLETED
        refund.provider_receipt = receipt

        payment = await self.payments.get_by_id(refund.payment_id)
        order = await self.db.get(Order, payment.order_id)
        refunded = await self.refunds.sum_active(payment.id)   # includes this one (now COMPLETED)
        order.payment_status = (
            OrderPaymentStatus.REFUNDED if refunded >= payment.amount else OrderPaymentStatus.PARTIALLY_REFUNDED
        )
