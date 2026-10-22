# src/services/delivery_service.py

r"""
a delivery job from dispatch to the customer's door.

    UNASSIGNED --assign--> ASSIGNED --accept--> ACCEPTED --pick up--> PICKED_UP --arrive--> ARRIVED --handover--> DELIVERED
        ^                      |                                           \--------- fail ----------> FAILED
        +------ decline ------+

  * the dispatcher assigns an APPROVED + AVAILABLE rider; the rider becomes BUSY at once (one job at a time),
    and is freed again when the job ends (declined / delivered / failed / cancelled)
  * pick up requires the order to be READY, and moves the order to OUT_FOR_DELIVERY
  * handover needs the customer's code (they read it from their app), at most N wrong tries, plus an ID check
    for alcohol/tobacco. Cash orders are paid HERE: the rider enters the cash collected
"""

import hmac

from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from src.exceptions import AppError, BusinessRuleError, ForbiddenError, NotFoundError
from src.models import (
    ApprovalStatus, Customer, Delivery, DeliveryStatus, OrderPaymentStatus, OrderStatus, PaymentMethod,
    Rider, RiderStatus, User,
)
from src.repositories import DeliveryRepository, RiderRepository
from src.schemas import DeliveryComplete
from src.security import make_handover_code
from utilities import utc_now

from .audit_service import AuditService
from .order_service import OrderService, payable_amount
from .payment_service import PaymentService

_OPEN = (DeliveryStatus.ASSIGNED, DeliveryStatus.ACCEPTED, DeliveryStatus.PICKED_UP, DeliveryStatus.ARRIVED)


class DeliveryService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self.deliveries = DeliveryRepository(db)
        self.riders = RiderRepository(db)
        self.orders = OrderService(db, settings)
        self.payments = PaymentService(db, settings)      # cash only: no Daraja client needed here
        self.audit = AuditService(db)


    # lookups
    async def _locked_delivery(self, delivery_id: int) -> Delivery:
        delivery = await self.deliveries.get_for_update(delivery_id)
        if delivery is None:
            raise NotFoundError("Delivery not found")
        return delivery

    async def _my_delivery(self, delivery_id: int, rider_user: User) -> tuple[Delivery, Rider]:
        """a rider may only touch deliveries assigned to THEM (another rider's job behaves like a missing one)"""
        rider = await self.riders.get_by_user_id(rider_user.id)
        if rider is None:
            raise ForbiddenError("Only riders can do this")
        delivery = await self._locked_delivery(delivery_id)
        if delivery.rider_id != rider.id:
            raise NotFoundError("Delivery not found")
        return delivery, rider

    async def _free(self, rider_id: int | None) -> None:
        if rider_id is None:
            return
        rider = await self.riders.get_for_update(rider_id)
        if rider is not None and rider.status is RiderStatus.BUSY:
            rider.status = RiderStatus.AVAILABLE


    # dispatcher
    async def unassigned_queue(self) -> list[Delivery]:
        return await self.deliveries.list_unassigned()


    async def assign(self, delivery_id: int, rider_id: int, dispatcher: User) -> Delivery:
        delivery = await self._locked_delivery(delivery_id)
        if delivery.status is not DeliveryStatus.UNASSIGNED:
            raise BusinessRuleError("This delivery already has a rider")

        rider = await self.riders.get_for_update(rider_id)
        if rider is None:
            raise NotFoundError("Rider not found")
        if rider.approval_status is not ApprovalStatus.APPROVED:
            raise BusinessRuleError("This rider is not approved")
        if rider.status is not RiderStatus.AVAILABLE:
            raise BusinessRuleError("This rider is not available")

        delivery.rider_id = rider.id
        delivery.status = DeliveryStatus.ASSIGNED
        delivery.assigned_at = utc_now()
        rider.status = RiderStatus.BUSY            # reserved the moment the offer is made

        self.audit.record(actor_id=dispatcher.id, action="delivery.assigned", entity_type="delivery",
                          entity_id=delivery_id, after={"rider_id": rider.id})
        await self.db.commit()
        return delivery


    # the rider
    async def my_active(self, rider_user: User) -> list[Delivery]:
        rider = await self.riders.get_by_user_id(rider_user.id)
        if rider is None:
            raise ForbiddenError("Only riders can do this")
        return await self.deliveries.list_for_rider(rider.id, active_only=True)


    async def respond(self, delivery_id: int, rider_user: User, accept: bool) -> Delivery:
        delivery, rider = await self._my_delivery(delivery_id, rider_user)
        if delivery.status is not DeliveryStatus.ASSIGNED:
            raise BusinessRuleError("This offer is no longer open")

        if accept:
            delivery.status = DeliveryStatus.ACCEPTED
            delivery.accepted_at = utc_now()
        else:
            # back to the dispatcher's queue
            delivery.status = DeliveryStatus.UNASSIGNED
            delivery.rider_id = None
            delivery.assigned_at = None
            rider.status = RiderStatus.AVAILABLE

        await self.db.commit()
        return delivery


    async def pick_up(self, delivery_id: int, rider_user: User) -> Delivery:
        delivery, _ = await self._my_delivery(delivery_id, rider_user)
        if delivery.status is not DeliveryStatus.ACCEPTED:
            raise BusinessRuleError("Accept the delivery first")

        order = await self.orders.get_locked(delivery.order_id)
        if order.status is not OrderStatus.READY:
            raise BusinessRuleError("The order is not packed yet")

        await self.orders.advance(order, OrderStatus.OUT_FOR_DELIVERY, actor_id=rider_user.id, note="left the shop")
        delivery.status = DeliveryStatus.PICKED_UP
        delivery.picked_up_at = utc_now()
        await self.db.commit()
        return delivery


    async def arrive(self, delivery_id: int, rider_user: User) -> Delivery:
        delivery, _ = await self._my_delivery(delivery_id, rider_user)
        if delivery.status is not DeliveryStatus.PICKED_UP:
            raise BusinessRuleError("Pick up the order first")

        delivery.status = DeliveryStatus.ARRIVED
        delivery.arrived_at = utc_now()
        await self.db.commit()
        return delivery


    async def complete(self, delivery_id: int, rider_user: User, data: DeliveryComplete) -> Delivery:
        delivery, rider = await self._my_delivery(delivery_id, rider_user)
        if delivery.status is not DeliveryStatus.ARRIVED:
            raise BusinessRuleError("Mark yourself as arrived first")

        if delivery.handover_attempts >= self.settings.handover_max_attempts:
            raise BusinessRuleError("Too many wrong codes. Contact dispatch")

        expected = make_handover_code(
            self.settings.secret_key.get_secret_value(), delivery.id, self.settings.handover_code_length
        )
        if not hmac.compare_digest(data.handover_code, expected):
            delivery.handover_attempts += 1
            await self.db.commit()                 # the failed attempt must persist even though we raise
            raise AppError("Incorrect handover code")

        if delivery.requires_id_check and not data.id_checked:
            raise AppError("Check the customer's ID before handing over age-restricted items")

        order = await self.orders.get_locked(delivery.order_id)

        # cash on delivery is settled at the door
        if order.payment_method is PaymentMethod.CASH and order.payment_status is not OrderPaymentStatus.PAID:
            if data.cash_collected is None:
                raise AppError(f"Collect KES {payable_amount(order)} in cash and enter the amount")
            await self.payments.record_cash(order.id, data.cash_collected, rider_user)
            order = await self.orders.get_locked(order.id)      # re-read: record_cash committed and released the lock

        await self.orders.advance(order, OrderStatus.COMPLETED, actor_id=rider_user.id, note="delivered")

        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = utc_now()
        delivery.proof_photo_url = data.proof_photo_url
        rider.status = RiderStatus.AVAILABLE
        rider.deliveries_completed += 1

        await self.db.commit()
        return delivery


    async def fail(self, delivery_id: int, rider_user: User, reason: str) -> Delivery:
        """
        customer unreachable / refused / wrong address. The parcel returns to the shop: the order goes back to
        READY so dispatch can retry or staff can cancel it (and refund)
        """
        delivery, rider = await self._my_delivery(delivery_id, rider_user)
        if delivery.status not in (DeliveryStatus.PICKED_UP, DeliveryStatus.ARRIVED):
            raise BusinessRuleError("Only a delivery that is under way can fail")

        order = await self.orders.get_locked(delivery.order_id)
        await self.orders.advance(order, OrderStatus.READY, actor_id=rider_user.id, note=f"delivery failed: {reason}")

        delivery.status = DeliveryStatus.FAILED
        delivery.failed_reason = reason[:255]
        rider.status = RiderStatus.AVAILABLE
        await self.db.commit()
        return delivery


    async def reopen(self, order_id: int, dispatcher: User) -> Delivery:
        """
        after a FAILED attempt: a fresh UNASSIGNED job for the same order (Delivery.order_id is UNIQUE, so the
        failed row is reset rather than duplicated; the failure stays in the audit trail)
        """
        order = await self.orders.get_locked(order_id)
        delivery = await self._locked_delivery(order.delivery.id) if order.delivery else None
        if delivery is None or delivery.status is not DeliveryStatus.FAILED:
            raise BusinessRuleError("Only a failed delivery can be re-opened")
        if order.status is not OrderStatus.READY:
            raise BusinessRuleError("The order must be back in READY to re-dispatch it")

        self.audit.record(actor_id=dispatcher.id, action="delivery.reopened", entity_type="delivery",
                          entity_id=delivery.id, before={"failed_reason": delivery.failed_reason,
                                                         "rider_id": delivery.rider_id})
        delivery.status = DeliveryStatus.UNASSIGNED
        delivery.rider_id = None
        for field in ("assigned_at", "accepted_at", "picked_up_at", "arrived_at", "failed_reason"):
            setattr(delivery, field, None)
        delivery.handover_attempts = 0
        await self.db.commit()
        return delivery


    # the customer (their own order's code + rider)
    async def handover_code_for(self, customer: Customer, order_id: int) -> tuple[int, str]:
        order = await self.orders.get_for_customer(customer, order_id)
        delivery = order.delivery
        if delivery is None or delivery.status not in _OPEN:
            raise BusinessRuleError("There is no active delivery for this order")

        return order.id, make_handover_code(
            self.settings.secret_key.get_secret_value(), delivery.id, self.settings.handover_code_length
        )
