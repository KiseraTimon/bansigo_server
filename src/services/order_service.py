# src/services/order_service.py

"""
the order lifecycle: checkout -> (payment) -> picking -> ready -> delivery/pickup -> completed | cancelled

    PENDING_PAYMENT --paid--> CONFIRMED --start picking--> PREPARING --finish picking--> READY
         |  (cash skips straight to CONFIRMED)                                            |
         |                                              delivery: OUT_FOR_DELIVERY -> COMPLETED   (DeliveryService)
         |                                              pickup:   COMPLETED                       (staff)
         +--> CANCELLED (from any non-terminal state)

Rules that make the numbers trustworthy:
  * the server prices everything; the client sends product ids + quantities only
  * everything the order needs later (names, prices, tax, address) is COPIED onto it (snapshot rule)
  * stock is RESERVED at checkout, consumed at picking, released on cancel
  * every state change takes a row lock on the order and writes an OrderStatusHistory line
"""

import hashlib
import secrets
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from src.exceptions import AppError, BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from src.models import (
    Customer, Delivery, DeliveryStatus, FulfilmentType, Order, OrderItem, OrderPaymentStatus, OrderStatus,
    OrderStatusHistory, PaymentMethod, PickStatus, RiderStatus, TaxClass, User,
)
from src.repositories import (
    DeliveryRepository, OrderRepository, ProductRepository, RiderRepository, StaffRepository, AddressRepository,
)
from src.schemas import CheckoutRequest, PickItemIn
from src.security import make_handover_code
from utilities import ZERO, get_logger, money, utc_now, vat_contained, whole_shillings

from .audit_service import AuditService
from .inventory_service import InventoryService
from .refund_service import RefundService

log = get_logger(__name__)

# order numbers are quoted by customers in M-Pesa's 'account number' box (C2B), so no look-alike characters
_NUMBER_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING_PAYMENT: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {OrderStatus.OUT_FOR_DELIVERY, OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    # READY again = the delivery failed and the parcel came back to the shop for re-dispatch
    OrderStatus.OUT_FOR_DELIVERY: {OrderStatus.COMPLETED, OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}

_CUSTOMER_CANCELLABLE = {OrderStatus.PENDING_PAYMENT, OrderStatus.CONFIRMED}


def payable_amount(order: Order) -> Decimal:
    """what the customer owes: the post-picking figure when there is one, else the checkout total"""
    return order.adjusted_total if order.adjusted_total is not None else order.total


class OrderService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self.orders = OrderRepository(db)
        self.products = ProductRepository(db)
        self.addresses = AddressRepository(db)
        self.deliveries = DeliveryRepository(db)
        self.riders = RiderRepository(db)
        self.staff = StaffRepository(db)
        self.inventory = InventoryService(db)
        self.refunds = RefundService(db)
        self.audit = AuditService(db)


    # reads (ownership-scoped: another customer's order behaves exactly like a missing one)
    async def get_for_customer(self, customer: Customer, order_id: int) -> Order:
        order = await self.orders.get_full(order_id)
        if order is None or order.customer_id != customer.id:
            raise NotFoundError("Order not found")
        return order


    async def list_for_customer(self, customer: Customer, page: int, per_page: int, statuses=None):
        return await self.orders.list_for_customer(customer.id, statuses=statuses, page=page, per_page=per_page)


    async def get_for_staff(self, order_id: int) -> Order:
        order = await self.orders.get_full(order_id)
        if order is None:
            raise NotFoundError("Order not found")
        return order


    async def list_for_staff(self, status, fulfilment_type, page: int, per_page: int):
        return await self.orders.list_for_staff(
            status=status, fulfilment_type=fulfilment_type, page=page, per_page=per_page
        )


    async def get_locked(self, order_id: int) -> Order:
        """the order, whole, with a row lock held until the caller commits (payments/deliveries use this too)"""
        order = await self.orders.get_full(order_id, for_update=True)
        if order is None:
            raise NotFoundError("Order not found")
        return order


    # checkout
    async def checkout(self, customer: Customer, user: User, data: CheckoutRequest) -> Order:
        """
        turns a basket into an order, or returns the order a previous identical attempt already created
        """
        existing = await self.orders.get_by_idempotency(customer.id, data.idempotency_key)
        if existing is not None:
            return existing

        if data.scheduled_for is not None and data.scheduled_for <= utc_now():
            raise AppError("scheduled_for must be in the future")

        # destination + fee
        address, delivery_fee = None, ZERO
        if data.fulfilment_type is FulfilmentType.DELIVERY:
            address = await self.addresses.get_for_customer(data.address_id, customer.id)
            if address is None:
                raise NotFoundError("Delivery address not found")
            if address.zone is None or not address.zone.is_active:
                raise BusinessRuleError("We do not deliver to this address yet")
            delivery_fee = address.zone.delivery_fee

        # lines: priced HERE, from the catalogue
        products = {p.id: p for p in await self.products.get_many(line.product_id for line in data.items)}
        items: list[OrderItem] = []
        subtotal = tax_total = ZERO
        wanted: dict[int, Decimal] = {}
        names: dict[int, str] = {}

        for line in data.items:
            product = products.get(line.product_id)
            if product is None or not product.is_active:
                raise NotFoundError(f"Product {line.product_id} is not available")
            self._check_quantity(product, line.quantity)

            line_total = money(product.price * line.quantity)
            rate = self.settings.vat_standard_rate if product.tax_class is TaxClass.STANDARD else ZERO
            tax_total += vat_contained(line_total, rate)
            subtotal += line_total
            wanted[product.id] = line.quantity
            names[product.id] = product.name

            items.append(OrderItem(
                product_id=product.id, product_name=product.name, sku=product.sku, unit=product.unit,
                unit_price=product.price, tax_class=product.tax_class, tax_rate=rate,
                quantity=line.quantity, line_total=line_total,
            ))

        if address is not None and subtotal < address.zone.min_order_amount:
            raise BusinessRuleError(
                f"The minimum order for {address.zone.name} is KES {address.zone.min_order_amount}"
            )

        # totals. total = subtotal + delivery_fee - discount_total + rounding_adjustment (also a DB CHECK)
        # NOTE: VAT on the delivery fee is not split out yet (needs the accountant's ruling, see TaxClass TODO)
        raw_total = subtotal + delivery_fee
        rounding = whole_shillings(raw_total) - raw_total if data.payment_method is PaymentMethod.MPESA else ZERO
        total = raw_total + rounding

        # reserve stock (all-or-nothing, locks rows)
        await self.inventory.reserve(wanted, names)

        initial = (
            OrderStatus.PENDING_PAYMENT if data.payment_method is PaymentMethod.MPESA else OrderStatus.CONFIRMED
        )
        now = utc_now()
        order = Order(
            order_number=await self._unique_number(),
            customer_id=customer.id,
            address_id=address.id if address else None,
            status=initial,
            payment_status=OrderPaymentStatus.UNPAID,
            payment_method=data.payment_method,
            fulfilment_type=data.fulfilment_type,
            idempotency_key=data.idempotency_key,
            subtotal=subtotal, delivery_fee=delivery_fee, discount_total=ZERO,
            rounding_adjustment=rounding, total=total, tax_total=tax_total,
            customer_note=data.customer_note, scheduled_for=data.scheduled_for,
            confirmed_at=now if initial is OrderStatus.CONFIRMED else None,
        )
        if address is not None:
            # the snapshot: later edits to the address must never rewrite this order
            order.delivery_recipient_name = address.recipient_name
            order.delivery_recipient_phone = address.recipient_phone
            order.delivery_address_text = ", ".join(
                p for p in (address.street_address, address.area, address.landmark, address.directions) if p
            )[:400]
            order.delivery_latitude = address.latitude
            order.delivery_longitude = address.longitude

        order.items = items
        order.status_history = [OrderStatusHistory(from_status=None, to_status=initial, changed_by=user.id)]
        self.db.add(order)

        try:
            await self.db.flush()
            if initial is OrderStatus.CONFIRMED:
                await self._open_delivery(order)
            await self.db.commit()
        except IntegrityError:
            # two identical requests raced past the idempotency pre-check: the UNIQUE key picked a winner
            await self.db.rollback()
            winner = await self.orders.get_by_idempotency(customer.id, data.idempotency_key)
            if winner is not None:
                return winner
            raise ConflictError(["order"])

        return await self.orders.get_full(order.id)


    @staticmethod
    def _check_quantity(product, quantity: Decimal) -> None:
        if quantity < product.min_order_quantity:
            raise BusinessRuleError(f"{product.name}: the minimum order is {product.min_order_quantity}")
        if product.max_order_quantity is not None and quantity > product.max_order_quantity:
            raise BusinessRuleError(f"{product.name}: the maximum order is {product.max_order_quantity}")
        if quantity % product.quantity_step != 0:
            raise BusinessRuleError(f"{product.name}: quantity must be a multiple of {product.quantity_step}")


    async def _unique_number(self) -> str:
        for _ in range(8):
            candidate = "BG" + "".join(secrets.choice(_NUMBER_ALPHABET) for _ in range(10))
            if not await self.orders.number_exists(candidate):
                return candidate
        raise AppError("Could not allocate an order number; please try again")


    # state machine
    async def _move(self, order: Order, to: OrderStatus, *, actor_id: int | None, note: str | None = None) -> None:
        """validates one transition, stamps its timestamp and appends the timeline line"""
        if to not in _TRANSITIONS[order.status]:
            raise BusinessRuleError(f"An order cannot go from {order.status.value} to {to.value}")

        if to is OrderStatus.OUT_FOR_DELIVERY and order.fulfilment_type is not FulfilmentType.DELIVERY:
            raise BusinessRuleError("Pickup orders are not delivered")
        if to is OrderStatus.COMPLETED and order.status is OrderStatus.READY \
                and order.fulfilment_type is not FulfilmentType.PICKUP:
            raise BusinessRuleError("A delivery order is completed by the rider's handover")

        previous = order.status
        order.status = to
        now = utc_now()
        if to is OrderStatus.CONFIRMED:
            order.confirmed_at = now
        elif to is OrderStatus.COMPLETED:
            order.completed_at = now
        elif to is OrderStatus.CANCELLED:
            order.cancelled_at = now

        self.db.add(OrderStatusHistory(order_id=order.id, from_status=previous, to_status=to,
                                       changed_by=actor_id, note=note))


    async def advance(self, order: Order, to: OrderStatus, *, actor_id: int | None, note: str | None = None) -> None:
        """
        forward moves driven by staff or the delivery flow. CONFIRMED and CANCELLED have side effects and
        their own entry points (confirm_paid / cancel_*), so they are refused here. Stages only; caller commits.
        """
        if to in (OrderStatus.CONFIRMED, OrderStatus.CANCELLED):
            raise AppError("Use the dedicated payment/cancel operation for that status")
        await self._move(order, to, actor_id=actor_id, note=note)


    async def staff_advance(self, order_id: int, to: OrderStatus, actor: User, note: str | None) -> Order:
        """
        the staff endpoint for the moves that are not picking: PREPARING/READY go through the picking methods,
        so only a pickup handover (READY -> COMPLETED) is accepted here
        """
        order = await self.get_locked(order_id)
        if to is not OrderStatus.COMPLETED:
            raise AppError("Use the picking operations to prepare an order, or the delivery flow to send it out")
        if order.payment_status is not OrderPaymentStatus.PAID:
            raise BusinessRuleError("Record the payment before handing the order over")

        await self.advance(order, to, actor_id=actor.id, note=note)
        await self.db.commit()
        return await self.orders.get_full(order_id)


    async def confirm_paid(self, order: Order, *, actor_id: int | None = None) -> None:
        """
        a payment succeeded: PENDING_PAYMENT -> CONFIRMED and open the delivery job.
        Called by PaymentService inside its transaction (stages only)
        """
        order.payment_status = OrderPaymentStatus.PAID
        if order.status is OrderStatus.PENDING_PAYMENT:
            await self._move(order, OrderStatus.CONFIRMED, actor_id=actor_id, note="payment received")
            await self._open_delivery(order)


    async def _open_delivery(self, order: Order) -> None:
        """creates the (unassigned) delivery job for a confirmed delivery order"""
        if order.fulfilment_type is not FulfilmentType.DELIVERY:
            return

        delivery = Delivery(
            order_id=order.id,
            status=DeliveryStatus.UNASSIGNED,
            requires_id_check=await self.orders.has_age_restricted_items(order.id),
            rider_fee=money(order.delivery_fee * self.settings.rider_fee_share),
        )
        self.db.add(delivery)
        await self.db.flush()

        code = make_handover_code(
            self.settings.secret_key.get_secret_value(), delivery.id, self.settings.handover_code_length
        )
        delivery.handover_code_hash = hashlib.sha256(code.encode()).hexdigest()


    # cancellation
    async def cancel_by_customer(self, customer: Customer, user: User, order_id: int, reason: str) -> Order:
        order = await self.get_locked(order_id)
        if order.customer_id != customer.id:
            raise NotFoundError("Order not found")
        if order.status not in _CUSTOMER_CANCELLABLE:
            raise BusinessRuleError("This order is already being prepared. Please contact support to cancel it")

        await self._cancel(order, actor_id=user.id, reason=reason)
        await self.db.commit()
        return await self.orders.get_full(order_id)


    async def cancel_by_staff(self, order_id: int, actor: User, reason: str) -> Order:
        order = await self.get_locked(order_id)
        await self._cancel(order, actor_id=actor.id, reason=reason)
        self.audit.record(actor_id=actor.id, action="order.cancelled", entity_type="order", entity_id=order_id,
                          after={"reason": reason})
        await self.db.commit()
        return await self.orders.get_full(order_id)


    async def _cancel(self, order: Order, *, actor_id: int | None, reason: str) -> None:
        # status check first so a terminal order raises a clean error before anything is touched
        if OrderStatus.CANCELLED not in _TRANSITIONS[order.status]:
            raise BusinessRuleError(f"A {order.status.value} order cannot be cancelled")

        # stock: lines nobody picked yet give their reservation back; picked lines go back on the shelf
        release: dict[int, Decimal] = {}
        for item in order.items:
            if item.pick_status is PickStatus.PENDING:
                release[item.product_id] = release.get(item.product_id, ZERO) + item.quantity
            elif item.quantity_picked:
                target = item.substitute_product_id or item.product_id
                await self.inventory.return_to_shelf(
                    target, item.quantity_picked, order_number=order.order_number, actor_id=actor_id
                )
        if release:
            await self.inventory.release(release)

        # the delivery job (and the rider, if one was already assigned)
        delivery = order.delivery
        if delivery is not None and delivery.status not in (
            DeliveryStatus.DELIVERED, DeliveryStatus.FAILED, DeliveryStatus.CANCELLED
        ):
            if delivery.rider_id is not None:
                rider = await self.riders.get_for_update(delivery.rider_id)
                if rider is not None and rider.status is RiderStatus.BUSY:
                    rider.status = RiderStatus.AVAILABLE
            delivery.status = DeliveryStatus.CANCELLED

        order.cancelled_by = actor_id
        order.cancel_reason = reason[:255]
        await self._move(order, OrderStatus.CANCELLED, actor_id=actor_id, note=reason[:255])

        # money back (maker-checker applies; see RefundService)
        if order.payment_status is OrderPaymentStatus.PAID:
            await self.refunds.request_for_order(order, actor_id=actor_id, reason=f"Order cancelled: {reason}")


    async def expire_unpaid(self) -> int:
        """
        SWEEPER: cancels M-Pesa orders nobody paid for, so their stock reservation does not stay locked forever.
        An order with a payment prompt still open is skipped (its callback may yet arrive).
        :return: int  how many orders were expired
        """
        cutoff = utc_now() - timedelta(minutes=self.settings.unpaid_order_ttl_minutes)
        count = 0
        for stale in await self.orders.list_stale_unpaid(cutoff):
            order = await self.get_locked(stale.id)
            if order.status is not OrderStatus.PENDING_PAYMENT:
                continue

            now = utc_now()
            if any(p.status.value in ("initiated", "pending") and p.expires_at and p.expires_at > now
                   for p in order.payments):
                continue

            await self._cancel(order, actor_id=None, reason="Payment not received in time")
            count += 1
            await self.db.commit()
        return count


    # picking (staff)
    async def start_picking(self, order_id: int, actor: User) -> Order:
        order = await self.get_locked(order_id)
        picker = await self.staff.get_by_user_id(actor.id)
        if picker is None:
            raise ForbiddenError("Only staff can pick orders")

        order.assigned_picker_id = picker.id
        await self._move(order, OrderStatus.PREPARING, actor_id=actor.id, note="picking started")
        await self.db.commit()
        return await self.orders.get_full(order_id)


    async def record_pick(self, order_id: int, item_id: int, data: PickItemIn, actor: User) -> Order:
        """
        what the picker found for one line. Moves stock, and fixes the line's final price
        """
        order = await self.get_locked(order_id)
        if order.status is not OrderStatus.PREPARING:
            raise BusinessRuleError("This order is not being prepared")

        item = next((i for i in order.items if i.id == item_id), None)
        if item is None:
            raise NotFoundError("Order line not found")
        if item.pick_status is not PickStatus.PENDING:
            raise BusinessRuleError("This line has already been picked")

        status, qty = data.pick_status, data.quantity_picked
        if status is PickStatus.PICKED:
            if qty != item.quantity:
                raise AppError("Use 'short' when fewer than ordered were picked")
        elif status is PickStatus.SHORT and not (0 < qty < item.quantity):
            raise AppError("A short pick must be more than 0 and less than the ordered quantity")
        elif qty > item.quantity:
            raise AppError("You cannot pick more than was ordered")

        if status is PickStatus.SUBSTITUTED:
            sub = await self.products.get_by_id(data.substitute_product_id)
            if sub is None or not sub.is_active:
                raise NotFoundError("Substitute product not found")
            await self.inventory.consume_reserved(
                item.product_id, item.quantity, ZERO, order_number=order.order_number, actor_id=actor.id
            )
            await self.inventory.consume_unreserved(
                sub.id, qty, order_number=order.order_number, actor_id=actor.id, name=sub.name
            )
            item.substitute_product_id = sub.id
            # the customer pays the SUBSTITUTE's price for what was actually supplied
            item.final_line_total = money(sub.price * qty)
        else:
            await self.inventory.consume_reserved(
                item.product_id, item.quantity, qty, order_number=order.order_number, actor_id=actor.id
            )
            item.final_line_total = money(item.unit_price * qty)

        item.pick_status = status
        item.quantity_picked = qty
        await self.db.commit()
        return await self.orders.get_full(order_id)


    async def finish_picking(self, order_id: int, actor: User) -> Order:
        """
        every line is resolved: fix the final amount, refund any difference, and mark the order READY
        """
        order = await self.get_locked(order_id)
        if order.status is not OrderStatus.PREPARING:
            raise BusinessRuleError("This order is not being prepared")
        if any(i.pick_status is PickStatus.PENDING for i in order.items):
            raise BusinessRuleError("Every line must be picked (or marked out of stock) first")

        goods = sum((i.final_line_total or ZERO for i in order.items), ZERO)
        # business rule: a customer never pays MORE than the checkout total (a pricier substitute is on the shop)
        adjusted = min(whole_shillings(goods + order.delivery_fee - order.discount_total), order.total)
        difference = order.total - adjusted

        if difference > 0 and order.payment_status is OrderPaymentStatus.PAID:
            await self.refunds.request_for_order(
                order, actor_id=actor.id, amount=difference, reason="Picked items differ from the order"
            )
        order.adjusted_total = adjusted

        await self._move(order, OrderStatus.READY, actor_id=actor.id, note="packed")
        await self.db.commit()
        return await self.orders.get_full(order_id)
