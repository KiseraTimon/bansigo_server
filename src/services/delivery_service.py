# src/services/delivery_service.py

r"""
a delivery job from dispatch to the customer's door.

    UNASSIGNED --assign--> ASSIGNED --accept--> ACCEPTED --pick up--> PICKED_UP --arrive--> ARRIVED --handover--> DELIVERED
        ^                      |                                           \--------- fail ----------> FAILED
        +------ decline ------+

  * all deliveries start at Bansi Mega Supermarket (Migori road network graph).
  * when deliveries are dispatched, route estimation runs with random selection between Dijkstra and A*.
  * the dispatcher assigns an APPROVED + AVAILABLE rider; the rider becomes BUSY at once (one job at a time),
    and is freed again when the job ends (declined / delivered / failed / cancelled)
  * pick up requires the order to be READY, and moves the order to OUT_FOR_DELIVERY
  * handover needs the customer's code (they read it from their app), at most N wrong tries, plus an ID check
    for alcohol/tobacco. Cash orders are paid HERE: the rider enters the cash collected
"""

from decimal import Decimal
import hmac
import json
from typing import Optional

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
from utilities import get_logger, utc_now

from .audit_service import AuditService
from .order_service import OrderService, payable_amount
from .payment_service import PaymentService

log = get_logger(__name__)

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

    async def assign(
        self, delivery_id: int, rider_id: int, dispatcher: User, algorithm: Optional[str] = None
    ) -> Delivery:
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

        # Routing calculation from Bansi Mega Supermarket to customer address
        try:
            order = await self.orders.get_locked(delivery.order_id)
            if order.delivery_latitude is not None and order.delivery_longitude is not None:
                from src.algorithms.route_engines import RoutingAlgorithm, get_router
                router = get_router()
                chosen_algo = RoutingAlgorithm(algorithm) if algorithm else None
                route = router.route_from_supermarket(
                    float(order.delivery_latitude),
                    float(order.delivery_longitude),
                    algorithm=chosen_algo,
                )
                delivery.estimated_distance_m = int(round(route.total_distance_m))
                delivery.estimated_duration_s = int(round(route.total_duration_s))
                delivery.routing_algorithm = route.algorithm.value
                delivery.route_waypoints = route.to_waypoints_json()
                delivery.pickup_latitude = Decimal(str(router.supermarket_coords[0]))
                delivery.pickup_longitude = Decimal(str(router.supermarket_coords[1]))
        except Exception as e:
            log.warning("Route calculation skipped during manual assign: %s", e)

        delivery.rider_id = rider.id
        delivery.status = DeliveryStatus.ASSIGNED
        delivery.assigned_at = utc_now()
        rider.status = RiderStatus.BUSY            # reserved the moment the offer is made

        self.audit.record(
            actor_id=dispatcher.id,
            action="delivery.assigned",
            entity_type="delivery",
            entity_id=delivery_id,
            after={"rider_id": rider.id, "algorithm": delivery.routing_algorithm},
        )
        await self.db.commit()
        return delivery

    async def auto_dispatch(
        self, delivery_id: int, dispatcher: User, algorithm: Optional[str] = None
    ) -> tuple[Delivery, Rider]:
        """
        Auto-assigns the optimal rider using road graph routing and ETA minimization to Bansi Mega Supermarket.
        """
        delivery = await self._locked_delivery(delivery_id)
        if delivery.status is not DeliveryStatus.UNASSIGNED:
            raise BusinessRuleError("This delivery already has a rider")

        order = await self.orders.get_locked(delivery.order_id)
        if order.delivery_latitude is None or order.delivery_longitude is None:
            raise BusinessRuleError("Order has no delivery coordinates for dispatch routing")

        available_riders = await self.riders.list_dispatchable()
        if not available_riders:
            raise BusinessRuleError("No available riders online to assign")

        from src.algorithms.route_engines import RoutingAlgorithm, get_router
        router = get_router()

        selection = router.select_best_rider(
            available_riders,
            float(order.delivery_latitude),
            float(order.delivery_longitude),
        )

        if selection:
            best_rider, _, store_to_dest = selection
            chosen_rider = await self.riders.get_for_update(best_rider.id)
            route = store_to_dest
        else:
            chosen_rider = await self.riders.get_for_update(available_riders[0].id)
            chosen_algo = RoutingAlgorithm(algorithm) if algorithm else None
            route = router.route_from_supermarket(
                float(order.delivery_latitude),
                float(order.delivery_longitude),
                algorithm=chosen_algo,
            )

        delivery.rider_id = chosen_rider.id
        delivery.status = DeliveryStatus.ASSIGNED
        delivery.assigned_at = utc_now()
        chosen_rider.status = RiderStatus.BUSY

        delivery.estimated_distance_m = int(round(route.total_distance_m))
        delivery.estimated_duration_s = int(round(route.total_duration_s))
        delivery.routing_algorithm = route.algorithm.value
        delivery.route_waypoints = route.to_waypoints_json()
        delivery.pickup_latitude = Decimal(str(router.supermarket_coords[0]))
        delivery.pickup_longitude = Decimal(str(router.supermarket_coords[1]))

        self.audit.record(
            actor_id=dispatcher.id,
            action="delivery.auto_assigned",
            entity_type="delivery",
            entity_id=delivery_id,
            after={"rider_id": chosen_rider.id, "algorithm": delivery.routing_algorithm},
        )
        await self.db.commit()
        return delivery, chosen_rider

    # estimates and quotes
    def estimate_delivery(self, latitude: Decimal, longitude: Decimal) -> dict:
        """
        Calculates delivery route from Bansi Mega Supermarket, ETA, and dynamic fee quote.
        """
        from src.algorithms.route_engines import get_router
        router = get_router()

        lat_f = float(latitude)
        lon_f = float(longitude)
        within, dist_to_store_m = router.is_within_coverage(lat_f, lon_f)
        if not within:
            raise BusinessRuleError(
                f"Location is outside our {router.max_delivery_radius_km}km delivery coverage zone from Bansi Mega Supermarket ({dist_to_store_m/1000.0:.1f}km away)"
            )

        route = router.route_from_supermarket(lat_f, lon_f)
        fee = router.calculate_delivery_fee(route.total_distance_m)

        return {
            "is_deliverable": True,
            "distance_m": int(round(route.total_distance_m)),
            "duration_s": int(round(route.total_duration_s)),
            "estimated_minutes": route.estimated_minutes,
            "delivery_fee": fee,
            "routing_algorithm": route.algorithm.value,
            "supermarket_name": self.settings.supermarket_name,
            "supermarket_coords": {
                "latitude": float(self.settings.supermarket_latitude),
                "longitude": float(self.settings.supermarket_longitude),
            },
            "destination_coords": {
                "latitude": lat_f,
                "longitude": lon_f,
            },
            "waypoints": route.to_waypoints_list(),
        }

    # the rider
    async def my_active(self, rider_user: User) -> list[Delivery]:
        rider = await self.riders.get_by_user_id(rider_user.id)
        if rider is None:
            raise ForbiddenError("Only riders can do this")
        return await self.deliveries.list_for_rider(rider.id, active_only=True)

    async def get_rider_delivery_detail(self, delivery_id: int, rider_user: User) -> dict:
        """
        Detailed delivery view for rider app.
        """
        delivery, rider = await self._my_delivery(delivery_id, rider_user)
        order = await self.orders.get_locked(delivery.order_id)

        waypoints = []
        if delivery.route_waypoints:
            try:
                waypoints = json.loads(delivery.route_waypoints)
            except Exception:
                waypoints = []

        cash_to_collect = None
        if order.payment_method is PaymentMethod.CASH and order.payment_status is not OrderPaymentStatus.PAID:
            cash_to_collect = payable_amount(order)

        return {
            "delivery_id": delivery.id,
            "order_id": order.id,
            "order_number": order.order_number,
            "status": delivery.status,
            "requires_id_check": delivery.requires_id_check,
            "rider_fee": delivery.rider_fee,
            "pickup_location": {
                "name": self.settings.supermarket_name,
                "latitude": float(delivery.pickup_latitude or self.settings.supermarket_latitude),
                "longitude": float(delivery.pickup_longitude or self.settings.supermarket_longitude),
            },
            "dropoff_location": {
                "latitude": float(order.delivery_latitude) if order.delivery_latitude else None,
                "longitude": float(order.delivery_longitude) if order.delivery_longitude else None,
                "address_text": order.delivery_address_text,
                "recipient_name": order.delivery_recipient_name,
                "recipient_phone": order.delivery_recipient_phone,
            },
            "customer_note": order.customer_note,
            "payment_method": order.payment_method.value,
            "cash_to_collect": cash_to_collect,
            "estimated_distance_m": delivery.estimated_distance_m,
            "estimated_duration_s": delivery.estimated_duration_s,
            "routing_algorithm": delivery.routing_algorithm,
            "route_waypoints": waypoints,
        }

    async def get_rider_navigation(
        self,
        delivery_id: int,
        rider_user: User,
        current_lat: Optional[Decimal] = None,
        current_lon: Optional[Decimal] = None,
    ) -> dict:
        """
        Provides active navigation instructions and waypoints for the current route leg.
        """
        delivery, rider = await self._my_delivery(delivery_id, rider_user)
        order = await self.orders.get_locked(delivery.order_id)

        orig_lat = float(current_lat or rider.last_latitude or self.settings.supermarket_latitude)
        orig_lon = float(current_lon or rider.last_longitude or self.settings.supermarket_longitude)

        from src.algorithms.route_engines import get_router
        router = get_router()

        if delivery.status in (DeliveryStatus.ASSIGNED, DeliveryStatus.ACCEPTED):
            leg = "to_supermarket"
            dest_name = self.settings.supermarket_name
            target_lat = float(self.settings.supermarket_latitude)
            target_lon = float(self.settings.supermarket_longitude)
        else:
            leg = "to_customer"
            dest_name = order.delivery_address_text or "Customer Drop-off"
            if order.delivery_latitude is None or order.delivery_longitude is None:
                raise BusinessRuleError("Order delivery coordinates missing")
            target_lat = float(order.delivery_latitude)
            target_lon = float(order.delivery_longitude)

        route = router.find_route(orig_lat, orig_lon, target_lat, target_lon)

        return {
            "delivery_id": delivery.id,
            "leg": leg,
            "destination_name": dest_name,
            "distance_m": int(round(route.total_distance_m)),
            "duration_s": int(round(route.total_duration_s)),
            "estimated_minutes": route.estimated_minutes,
            "routing_algorithm": route.algorithm.value,
            "steps": [step.to_dict() for step in route.steps],
            "waypoints": route.to_waypoints_list(),
        }

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

    # the customer (their own order's tracking + code)
    async def handover_code_for(self, customer: Customer, order_id: int) -> tuple[int, str]:
        order = await self.orders.get_for_customer(customer, order_id)
        delivery = order.delivery
        if delivery is None or delivery.status not in _OPEN:
            raise BusinessRuleError("There is no active delivery for this order")

        return order.id, make_handover_code(
            self.settings.secret_key.get_secret_value(), delivery.id, self.settings.handover_code_length
        )

    async def get_tracking_for_customer(self, customer: Customer, order_id: int) -> dict:
        """
        Live tracking state of a customer's delivery.
        """
        order = await self.orders.get_for_customer(customer, order_id)
        delivery = order.delivery
        if delivery is None:
            raise NotFoundError("No delivery registered for this order")

        rider_pub = None
        rider_loc = None
        if delivery.rider_id:
            rider = await self.riders.get_by_id(delivery.rider_id)
            if rider:
                rider_pub = {
                    "id": rider.id,
                    "vehicle_type": rider.vehicle_type,
                    "vehicle_plate": rider.vehicle_plate,
                    "rating_average": rider.rating_average,
                }
                if rider.last_latitude is not None and rider.last_longitude is not None:
                    rider_loc = {
                        "latitude": float(rider.last_latitude),
                        "longitude": float(rider.last_longitude),
                        "last_seen_at": rider.last_seen_at.isoformat() if rider.last_seen_at else None,
                    }

        handover_code = None
        if delivery.status in _OPEN:
            handover_code = make_handover_code(
                self.settings.secret_key.get_secret_value(), delivery.id, self.settings.handover_code_length
            )

        waypoints = []
        if delivery.route_waypoints:
            try:
                waypoints = json.loads(delivery.route_waypoints)
            except Exception:
                waypoints = []

        return {
            "order_id": order.id,
            "order_number": order.order_number,
            "delivery_id": delivery.id,
            "status": delivery.status.value,
            "is_delivered": delivery.status == DeliveryStatus.DELIVERED,
            "routing_algorithm": delivery.routing_algorithm,
            "estimated_distance_m": delivery.estimated_distance_m,
            "estimated_duration_s": delivery.estimated_duration_s,
            "estimated_minutes": max(1, round(delivery.estimated_duration_s / 60)) if delivery.estimated_duration_s else None,
            "supermarket_location": {
                "name": self.settings.supermarket_name,
                "latitude": float(delivery.pickup_latitude or self.settings.supermarket_latitude),
                "longitude": float(delivery.pickup_longitude or self.settings.supermarket_longitude),
            },
            "delivery_location": {
                "latitude": float(order.delivery_latitude) if order.delivery_latitude else None,
                "longitude": float(order.delivery_longitude) if order.delivery_longitude else None,
                "address_text": order.delivery_address_text,
                "recipient_name": order.delivery_recipient_name,
            },
            "rider": rider_pub,
            "rider_location": rider_loc,
            "route_waypoints": waypoints,
            "handover_code": handover_code,
        }
