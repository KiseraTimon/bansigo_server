# src/services/delivery_service.py

r"""
a delivery job from dispatch to the customer's door.

    UNASSIGNED --assign--> ASSIGNED --accept--> ACCEPTED --pick up (code)--> PICKED_UP --arrive--> ARRIVED --handover (PIN)--> DELIVERED
        ^                      |                                                             \--------- fail ----------> FAILED
        +--- decline / expire -+ (auto re-dispatches to next best rider, else flags manual assignment)

  * all deliveries start at Bansi Mega Supermarket (Migori road network graph).
  * when deliveries are dispatched, route estimation runs with random selection between Dijkstra and A*.
  * multi-order batching allows riders to carry up to `settings.rider_max_active_deliveries` orders along coherent routes.
  * unjustified rejections & overdue SLAs incur rider penalty points, warnings, and temporary dispatch cooldowns.
"""

from datetime import timedelta
from decimal import Decimal
import hashlib
import hmac
import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from src.exceptions import AppError, BusinessRuleError, ForbiddenError, NotFoundError
from src.models import (
    ApprovalStatus, Customer, Delivery, DeliveryOfferAction, DeliveryOfferEvent, DeliveryStatus,
    OrderPaymentStatus, OrderStatus, PaymentMethod, Rider, RiderStatus, User,
)
from src.repositories import DeliveryRepository, RiderRepository
from src.schemas import DeliveryComplete
from src.security import make_handover_code, make_pickup_code
from utilities import get_logger, utc_now

from .audit_service import AuditService
from .notification_service import NotificationService
from .order_service import OrderService, payable_amount
from .payment_service import PaymentService

log = get_logger(__name__)

_OPEN = (DeliveryStatus.ASSIGNED, DeliveryStatus.ACCEPTED, DeliveryStatus.PICKED_UP, DeliveryStatus.ARRIVED)

_VALID_JUSTIFICATION_CODES = {
    "vehicle_breakdown",
    "medical_emergency",
    "unsafe_area",
    "over_capacity",
    "shift_ending",
}


class DeliveryService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self.deliveries = DeliveryRepository(db)
        self.riders = RiderRepository(db)
        self.orders = OrderService(db, settings)
        self.payments = PaymentService(db, settings)      # cash only: no Daraja client needed here
        self.notifications = NotificationService(db)
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

    async def _sync_rider_status(self, rider_id: int | None) -> None:
        """Sets rider BUSY when >=1 active deliveries exist, AVAILABLE when 0 (unless OFFLINE)."""
        if rider_id is None:
            return
        await self.db.flush()
        active_count = await self.deliveries.count_active_for_rider(rider_id)
        rider = await self.riders.get_for_update(rider_id)
        if rider is None or rider.status is RiderStatus.OFFLINE:
            return
        rider.status = RiderStatus.BUSY if active_count > 0 else RiderStatus.AVAILABLE

    async def _notify_customer(self, customer_id: int, *, title: str, message: str, order_id: int, notif_type: str = "delivery") -> None:
        customer = await self.db.get(Customer, customer_id)
        if customer is not None:
            self.notifications.stage(
                user_id=customer.user_id,
                title=title,
                message=message,
                notif_type=notif_type,
                action_type="order_tracking",
                action_payload=str(order_id),
            )

    @staticmethod
    def _is_rejection_justified(reason_code: Optional[str], reason_text: Optional[str]) -> bool:
        code = (reason_code or "").strip().lower()
        text = (reason_text or "").strip()
        if code in _VALID_JUSTIFICATION_CODES:
            return True
        if code == "other" and len(text) >= 12:
            return True
        return False

    # dispatcher
    async def unassigned_queue(self) -> list[Delivery]:
        return await self.deliveries.list_unassigned()

    async def manual_queue(self) -> list[Delivery]:
        return await self.deliveries.list_manual_assignment_queue()

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
        if rider.status is RiderStatus.OFFLINE:
            raise BusinessRuleError("This rider is currently offline")

        active_count = await self.deliveries.count_active_for_rider(rider.id)
        if active_count >= self.settings.rider_max_active_deliveries:
            raise BusinessRuleError(
                f"Rider already has {active_count} active deliveries (max {self.settings.rider_max_active_deliveries})"
            )

        # Routing calculation from Bansi Mega Supermarket to customer address
        order = await self.orders.get_locked(delivery.order_id)
        try:
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

        now = utc_now()
        delivery.rider_id = rider.id
        delivery.status = DeliveryStatus.ASSIGNED
        delivery.assigned_at = now
        delivery.offer_expires_at = now + timedelta(seconds=self.settings.delivery_offer_timeout_seconds)
        delivery.needs_manual_assignment = False
        delivery.manual_assignment_reason = None
        rider.status = RiderStatus.BUSY            # reserved the moment the offer is made

        self.db.add(DeliveryOfferEvent(
            delivery_id=delivery.id,
            rider_id=rider.id,
            action=DeliveryOfferAction.OFFERED,
            is_justified=True,
        ))
        self.notifications.stage(
            user_id=rider.user_id,
            title=f"New Delivery Offer #{order.order_number}",
            message=f"Earn KES {delivery.rider_fee:.0f}. Accept within {self.settings.delivery_offer_timeout_seconds}s.",
            notif_type="delivery_offer",
            action_type="delivery",
            action_payload=str(delivery.id),
        )
        await self._notify_customer(
            order.customer_id,
            title=f"Rider Assigned • #{order.order_number}",
            message="A BansiGo rider has been offered your delivery and will confirm shortly.",
            order_id=order.id,
        )

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
        self,
        delivery_id: int,
        dispatcher: Optional[User] = None,
        algorithm: Optional[str] = None,
        exclude_rider_ids: Optional[set[int]] = None,
    ) -> tuple[Delivery, Rider]:
        """
        Auto-assigns the optimal rider using road graph routing, ETA minimization,
        and multi-order batching limits.
        """
        delivery = await self._locked_delivery(delivery_id)
        if delivery.status is not DeliveryStatus.UNASSIGNED:
            raise BusinessRuleError("This delivery already has a rider")

        order = await self.orders.get_locked(delivery.order_id)
        if order.delivery_latitude is None or order.delivery_longitude is None:
            raise BusinessRuleError("Order has no delivery coordinates for dispatch routing")

        now = utc_now()
        available_riders = await self.riders.list_dispatchable(now=now)
        prior_rejected = await self.deliveries.rejected_rider_ids_for_delivery(delivery_id)
        excluded = prior_rejected | (exclude_rider_ids or set())

        eligible_pool = [r for r in available_riders if r.id not in excluded]
        if not eligible_pool:
            raise BusinessRuleError("No available riders online to assign")

        rider_ids = [r.id for r in eligible_pool]
        load_map, dropoffs_map, departed_map = await self.deliveries.active_summary_by_rider(rider_ids)

        from src.algorithms.route_engines import RoutingAlgorithm, get_router
        router = get_router()

        selection = router.select_best_rider(
            eligible_pool,
            float(order.delivery_latitude),
            float(order.delivery_longitude),
            active_load_by_rider=load_map,
            active_dropoffs_by_rider=dropoffs_map,
            has_departed_by_rider=departed_map,
            max_active_deliveries=self.settings.rider_max_active_deliveries,
            max_batch_detour_km=self.settings.rider_batch_max_detour_km,
            exclude_rider_ids=excluded,
        )

        if selection:
            best_rider, _, store_to_dest = selection
            chosen_rider = await self.riders.get_for_update(best_rider.id)
            route = store_to_dest
        else:
            # Fallback for online riders within batch limit who have not yet sent GPS pings
            fallback_candidates = [
                r for r in eligible_pool
                if load_map.get(r.id, 0) < self.settings.rider_max_active_deliveries
                and not (departed_map.get(r.id, False) and load_map.get(r.id, 0) > 0)
            ]
            if not fallback_candidates:
                raise BusinessRuleError("No eligible riders within active batch and route limits")
            fallback_candidates.sort(key=lambda r: (load_map.get(r.id, 0), r.penalty_points))
            chosen_rider = await self.riders.get_for_update(fallback_candidates[0].id)
            chosen_algo = RoutingAlgorithm(algorithm) if algorithm else None
            route = router.route_from_supermarket(
                float(order.delivery_latitude),
                float(order.delivery_longitude),
                algorithm=chosen_algo,
            )

        delivery.rider_id = chosen_rider.id
        delivery.status = DeliveryStatus.ASSIGNED
        delivery.assigned_at = now
        delivery.offer_expires_at = now + timedelta(seconds=self.settings.delivery_offer_timeout_seconds)
        delivery.needs_manual_assignment = False
        delivery.manual_assignment_reason = None
        chosen_rider.status = RiderStatus.BUSY

        delivery.estimated_distance_m = int(round(route.total_distance_m))
        delivery.estimated_duration_s = int(round(route.total_duration_s))
        delivery.routing_algorithm = route.algorithm.value
        delivery.route_waypoints = route.to_waypoints_json()
        delivery.pickup_latitude = Decimal(str(router.supermarket_coords[0]))
        delivery.pickup_longitude = Decimal(str(router.supermarket_coords[1]))

        self.db.add(DeliveryOfferEvent(
            delivery_id=delivery.id,
            rider_id=chosen_rider.id,
            action=DeliveryOfferAction.OFFERED,
            is_justified=True,
        ))
        self.notifications.stage(
            user_id=chosen_rider.user_id,
            title=f"Incoming Dispatch #{order.order_number}",
            message=f"Pickup at {self.settings.supermarket_name} • Earn KES {delivery.rider_fee:.0f}.",
            notif_type="delivery_offer",
            action_type="delivery",
            action_payload=str(delivery.id),
        )
        await self._notify_customer(
            order.customer_id,
            title=f"Rider Matched • #{order.order_number}",
            message="We matched your order to a nearby rider. Waiting for rider confirmation.",
            order_id=order.id,
        )

        self.audit.record(
            actor_id=dispatcher.id if dispatcher else None,
            action="delivery.auto_assigned",
            entity_type="delivery",
            entity_id=delivery_id,
            after={"rider_id": chosen_rider.id, "algorithm": delivery.routing_algorithm},
        )
        await self.db.commit()
        return delivery, chosen_rider

    async def try_auto_dispatch(
        self,
        delivery_id: int,
        *,
        dispatcher: Optional[User] = None,
        exclude_rider_ids: Optional[set[int]] = None,
    ) -> Optional[tuple[Delivery, Rider]]:
        """
        Attempts automatic dispatch; if no eligible rider is available or routing fails,
        flags the delivery for manual assignment by store operators.
        """
        try:
            return await self.auto_dispatch(
                delivery_id, dispatcher=dispatcher, exclude_rider_ids=exclude_rider_ids
            )
        except BusinessRuleError as exc:
            # No database mutations were staged before BusinessRuleError; keep caller ORM state intact
            delivery = await self.deliveries.get_for_update(delivery_id)
            if delivery is not None and delivery.status is DeliveryStatus.UNASSIGNED:
                delivery.needs_manual_assignment = True
                delivery.manual_assignment_reason = str(exc)[:255]
                self.audit.record(
                    actor_id=dispatcher.id if dispatcher else None,
                    action="delivery.manual_assignment_required",
                    entity_type="delivery",
                    entity_id=delivery_id,
                    after={"reason": delivery.manual_assignment_reason},
                )
                await self.db.commit()
            log.warning("Auto-dispatch fell back to manual assignment for delivery %s: %s", delivery_id, exc)
            return None
        except Exception as exc:
            await self.db.rollback()
            delivery = await self.deliveries.get_for_update(delivery_id)
            if delivery is not None and delivery.status is DeliveryStatus.UNASSIGNED:
                delivery.needs_manual_assignment = True
                delivery.manual_assignment_reason = str(exc)[:255]
                self.audit.record(
                    actor_id=dispatcher.id if dispatcher else None,
                    action="delivery.manual_assignment_required",
                    entity_type="delivery",
                    entity_id=delivery_id,
                    after={"reason": delivery.manual_assignment_reason},
                )
                await self.db.commit()
            log.warning("Auto-dispatch fell back to manual assignment for delivery %s: %s", delivery_id, exc)
            return None

    async def auto_dispatch_for_order(self, order_id: int) -> Optional[tuple[Delivery, Rider]]:
        delivery = await self.deliveries.get_by_order(order_id)
        if delivery is None or delivery.status is not DeliveryStatus.UNASSIGNED:
            return None
        return await self.try_auto_dispatch(delivery.id)

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
        delivery, _ = await self._my_delivery(delivery_id, rider_user)
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

        items_summary = [f"{int(i.quantity) if i.quantity == i.quantity.to_integral_value() else i.quantity}x {i.product_name}" for i in order.items]

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
            "offer_expires_at": delivery.offer_expires_at,
            "pickup_due_at": delivery.pickup_due_at,
            "delivery_due_at": delivery.delivery_due_at,
            "is_overdue": delivery.is_overdue,
            "items_summary": items_summary,
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

    async def respond(
        self,
        delivery_id: int,
        rider_user: User,
        accept: bool,
        *,
        reason_code: Optional[str] = None,
        reason_text: Optional[str] = None,
    ) -> Delivery:
        delivery, rider = await self._my_delivery(delivery_id, rider_user)
        if delivery.status is not DeliveryStatus.ASSIGNED:
            raise BusinessRuleError("This offer is no longer open")

        order = await self.orders.get_locked(delivery.order_id)
        now = utc_now()

        if accept:
            delivery.status = DeliveryStatus.ACCEPTED
            delivery.accepted_at = now
            delivery.offer_expires_at = None
            delivery.pickup_due_at = now + timedelta(minutes=self.settings.delivery_pickup_sla_minutes)

            secret = self.settings.secret_key.get_secret_value()
            pickup_code = make_pickup_code(secret, delivery.id, self.settings.pickup_code_length)
            delivery.pickup_code_hash = hashlib.sha256(pickup_code.encode()).hexdigest()

            self.db.add(DeliveryOfferEvent(
                delivery_id=delivery.id,
                rider_id=rider.id,
                action=DeliveryOfferAction.ACCEPTED,
                is_justified=True,
            ))
            self.notifications.stage(
                user_id=rider.user_id,
                title=f"Pickup Code: {pickup_code} (Order #{order.order_number})",
                message=(
                    f"Use store pickup PIN {pickup_code} at {self.settings.supermarket_name} dispatch bay "
                    f"before {delivery.pickup_due_at.strftime('%H:%M UTC')}."
                ),
                notif_type="pickup_code",
                action_type="delivery",
                action_payload=str(delivery.id),
            )
            await self._notify_customer(
                order.customer_id,
                title=f"Rider Accepted • #{order.order_number}",
                message="Your rider has accepted the delivery and is heading to Bansi Mega Supermarket.",
                order_id=order.id,
            )
            await self.db.commit()
            return delivery

        # Decline / Rejection path with justification check & penalties
        justified = self._is_rejection_justified(reason_code, reason_text)
        rider.total_rejections_count += 1

        if not justified:
            rider.unjustified_rejections_count += 1
            rider.penalty_points += 10

            if rider.unjustified_rejections_count >= self.settings.rider_rejection_penalty_threshold:
                cooldown_until = now + timedelta(minutes=self.settings.rider_rejection_cooldown_minutes)
                rider.dispatch_cooldown_until = cooldown_until
                self.notifications.stage(
                    user_id=rider.user_id,
                    title="Dispatch Cooldown Applied",
                    message=(
                        f"You reached {rider.unjustified_rejections_count} unjustified rejections while online. "
                        f"Auto-dispatch paused for {self.settings.rider_rejection_cooldown_minutes} minutes."
                    ),
                    notif_type="penalty",
                )
            else:
                self.notifications.stage(
                    user_id=rider.user_id,
                    title="Unjustified Rejection Recorded",
                    message=(
                        f"Rejection without valid cause ({rider.unjustified_rejections_count}/"
                        f"{self.settings.rider_rejection_penalty_threshold}). Repeated rejections trigger a cooldown."
                    ),
                    notif_type="warning",
                )

            if rider.penalty_points >= self.settings.rider_suspension_penalty_points:
                rider.approval_status = ApprovalStatus.SUSPENDED
                rider.status = RiderStatus.OFFLINE
                self.notifications.stage(
                    user_id=rider.user_id,
                    title="Account Suspended Pending Review",
                    message="Accumulated penalty points exceeded policy threshold. Contact dispatch operations.",
                    notif_type="penalty",
                )

            self.audit.record(
                actor_id=rider_user.id,
                action="rider.unjustified_rejection",
                entity_type="rider",
                entity_id=rider.id,
                after={
                    "delivery_id": delivery.id,
                    "unjustified_rejections": rider.unjustified_rejections_count,
                    "penalty_points": rider.penalty_points,
                    "reason_code": reason_code,
                    "reason_text": reason_text,
                },
            )

        self.db.add(DeliveryOfferEvent(
            delivery_id=delivery.id,
            rider_id=rider.id,
            action=DeliveryOfferAction.REJECTED,
            reason_code=reason_code,
            reason_text=reason_text,
            is_justified=justified,
        ))

        delivery.status = DeliveryStatus.UNASSIGNED
        delivery.rider_id = None
        delivery.assigned_at = None
        delivery.offer_expires_at = None
        delivery.rejection_count += 1
        await self._sync_rider_status(rider.id)
        await self.db.commit()

        # Calculate next best rider via routing engine (or fall back to manual operator assignment)
        await self.try_auto_dispatch(delivery.id, exclude_rider_ids={rider.id})
        refreshed = await self.deliveries.get_by_id(delivery.id)
        return refreshed or delivery

    async def _complete_pickup(self, delivery: Delivery, pickup_code: str, actor_id: int) -> Delivery:
        if delivery.status is not DeliveryStatus.ACCEPTED:
            raise BusinessRuleError("Delivery must be accepted by a rider before pickup")

        if delivery.pickup_attempts >= self.settings.pickup_max_attempts:
            raise BusinessRuleError("Too many wrong pickup codes. Contact dispatch")

        expected = make_pickup_code(
            self.settings.secret_key.get_secret_value(), delivery.id, self.settings.pickup_code_length
        )
        if not hmac.compare_digest(pickup_code.strip(), expected):
            delivery.pickup_attempts += 1
            await self.db.commit()
            raise AppError("Incorrect store pickup code")

        order = await self.orders.get_locked(delivery.order_id)
        if order.status in (OrderStatus.CONFIRMED, OrderStatus.PREPARING):
            await self.orders.prepare_for_pickup(order, actor_id=actor_id)
        if order.status is not OrderStatus.READY:
            raise BusinessRuleError("The order is not ready for pickup")

        now = utc_now()
        await self.orders.advance(order, OrderStatus.OUT_FOR_DELIVERY, actor_id=actor_id, note="left the shop")
        delivery.status = DeliveryStatus.PICKED_UP
        delivery.picked_up_at = now
        delivery.pickup_due_at = None

        transit_mins = max(
            self.settings.delivery_fulfilment_sla_minutes,
            round(((delivery.estimated_duration_s or 900) / 60) * 2),
        )
        delivery.delivery_due_at = now + timedelta(minutes=transit_mins)

        await self._notify_customer(
            order.customer_id,
            title=f"Order #{order.order_number} Picked Up!",
            message="Your rider has collected your order from Bansi Mega Supermarket and is on the way.",
            order_id=order.id,
        )
        if delivery.rider_id:
            rider = await self.db.get(Rider, delivery.rider_id)
            if rider is not None:
                self.notifications.stage(
                    user_id=rider.user_id,
                    title=f"Store Handover Verified • {order.order_number}",
                    message="Pickup verified. Proceed along the route to the customer.",
                    notif_type="delivery",
                    action_type="delivery",
                    action_payload=str(delivery.id),
                )
        await self.db.commit()
        return delivery

    async def pick_up(self, delivery_id: int, rider_user: User, pickup_code: str) -> Delivery:
        delivery, _ = await self._my_delivery(delivery_id, rider_user)
        return await self._complete_pickup(delivery, pickup_code, rider_user.id)

    async def verify_store_pickup(self, delivery_id: int, pickup_code: str, operator: User) -> Delivery:
        delivery = await self.deliveries.get_locked(delivery_id)
        if delivery is None:
            raise NotFoundError("Delivery not found")
        return await self._complete_pickup(delivery, pickup_code, operator.id)

    async def arrive(self, delivery_id: int, rider_user: User) -> Delivery:
        delivery, _ = await self._my_delivery(delivery_id, rider_user)
        if delivery.status is not DeliveryStatus.PICKED_UP:
            raise BusinessRuleError("Pick up the order first")

        order = await self.orders.get_locked(delivery.order_id)
        delivery.status = DeliveryStatus.ARRIVED
        delivery.arrived_at = utc_now()

        await self._notify_customer(
            order.customer_id,
            title=f"Rider Arrived • #{order.order_number}",
            message="Your rider is outside! Share your 4-digit handover PIN in the app to complete delivery.",
            order_id=order.id,
        )
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

        now = utc_now()
        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = now
        delivery.delivery_due_at = None
        delivery.proof_photo_url = data.proof_photo_url

        rider = await self.riders.get_for_update(rider.id)
        rider.deliveries_completed += 1
        if not delivery.is_overdue and rider.unjustified_rejections_count > 0:
            rider.unjustified_rejections_count -= 1

        await self._sync_rider_status(rider.id)
        await self._notify_customer(
            order.customer_id,
            title=f"Order #{order.order_number} Delivered!",
            message="Handover verified. Thank you for shopping with BansiGo!",
            order_id=order.id,
        )
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
        delivery.needs_manual_assignment = True
        delivery.manual_assignment_reason = f"Failed by rider: {reason[:200]}"
        await self._sync_rider_status(rider.id)
        await self._notify_customer(
            order.customer_id,
            title=f"Delivery Update • #{order.order_number}",
            message="Delivery could not be completed and is being reassigned by store dispatch.",
            order_id=order.id,
        )
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
        for field in (
            "assigned_at", "accepted_at", "picked_up_at", "arrived_at", "failed_reason",
            "offer_expires_at", "pickup_due_at", "delivery_due_at", "overdue_notified_at", "overdue_escalated_at",
        ):
            setattr(delivery, field, None)
        delivery.is_overdue = False
        delivery.handover_attempts = 0
        delivery.pickup_attempts = 0
        await self.db.commit()
        return delivery

    # SLA & timer sweeper
    async def sweep_delivery_timers(self) -> dict[str, int]:
        """
        Periodically checks:
        1. Expired ASSIGNED offers -> penalizes unresponsive rider & re-dispatches to next best rider.
        2. Overdue ACCEPTED pickups -> notifies rider & escalates long delays.
        3. Overdue PICKED_UP / ARRIVED deliveries -> flags overdue, notifies rider/customer, applies SLA penalties.
        """
        now = utc_now()
        stats = {"expired_offers": 0, "overdue_pickups": 0, "overdue_deliveries": 0}

        # 1. Expired assignment offers
        for expired in await self.deliveries.list_expired_offers(now):
            delivery = await self.deliveries.get_for_update(expired.id)
            if delivery is None or delivery.status is not DeliveryStatus.ASSIGNED:
                continue
            prev_rider_id = delivery.rider_id
            if prev_rider_id is not None:
                rider = await self.riders.get_for_update(prev_rider_id)
                if rider is not None:
                    rider.penalty_points += 5
                    rider.unjustified_rejections_count += 1
                    self.notifications.stage(
                        user_id=rider.user_id,
                        title="Delivery Offer Timed Out",
                        message="You missed an incoming dispatch offer. Penalty points applied.",
                        notif_type="warning",
                    )
                    self.db.add(DeliveryOfferEvent(
                        delivery_id=delivery.id,
                        rider_id=rider.id,
                        action=DeliveryOfferAction.EXPIRED,
                        reason_code="offer_timeout",
                        reason_text="Offer expired without response",
                        is_justified=False,
                    ))
            delivery.status = DeliveryStatus.UNASSIGNED
            delivery.rider_id = None
            delivery.assigned_at = None
            delivery.offer_expires_at = None
            delivery.rejection_count += 1
            await self._sync_rider_status(prev_rider_id)
            await self.db.commit()
            await self.try_auto_dispatch(delivery.id)
            stats["expired_offers"] += 1

        # 2. Overdue pickups at supermarket
        escalation_delta = timedelta(minutes=self.settings.delivery_overdue_escalation_minutes)
        for d_ref in await self.deliveries.list_overdue_pickups(now):
            delivery = await self.deliveries.get_for_update(d_ref.id)
            if delivery is None or delivery.status is not DeliveryStatus.ACCEPTED:
                continue
            order = await self.orders.get_locked(delivery.order_id)
            rider = await self.riders.get_for_update(delivery.rider_id) if delivery.rider_id else None
            delivery.is_overdue = True

            if delivery.overdue_notified_at is None:
                delivery.overdue_notified_at = now
                if rider:
                    self.notifications.stage(
                        user_id=rider.user_id,
                        title=f"Pickup Overdue • #{order.order_number}",
                        message=f"Please pick up Order #{order.order_number} at {self.settings.supermarket_name} immediately.",
                        notif_type="warning",
                        action_type="delivery",
                        action_payload=str(delivery.id),
                    )
                await self._notify_customer(
                    order.customer_id,
                    title=f"Delay Notice • #{order.order_number}",
                    message="Your rider is slightly delayed collecting your parcel at the supermarket.",
                    order_id=order.id,
                )

            if (
                delivery.overdue_escalated_at is None
                and delivery.pickup_due_at is not None
                and now >= delivery.pickup_due_at + escalation_delta
            ):
                delivery.overdue_escalated_at = now
                if rider:
                    rider.overdue_deliveries_count += 1
                    rider.penalty_points += 15
                    self.notifications.stage(
                        user_id=rider.user_id,
                        title=f"Severe Pickup Delay Escalated • #{order.order_number}",
                        message="15 penalty points added due to unfulfilled store pickup SLA.",
                        notif_type="penalty",
                    )
                self.audit.record(
                    actor_id=None,
                    action="delivery.pickup_sla_escalated",
                    entity_type="delivery",
                    entity_id=delivery.id,
                    after={"rider_id": delivery.rider_id, "order_id": order.id},
                )
            await self.db.commit()
            stats["overdue_pickups"] += 1

        # 3. Overdue transit deliveries
        for d_ref in await self.deliveries.list_overdue_transit(now):
            delivery = await self.deliveries.get_for_update(d_ref.id)
            if delivery is None or delivery.status not in (DeliveryStatus.PICKED_UP, DeliveryStatus.ARRIVED):
                continue
            order = await self.orders.get_locked(delivery.order_id)
            rider = await self.riders.get_for_update(delivery.rider_id) if delivery.rider_id else None
            delivery.is_overdue = True

            if delivery.overdue_notified_at is None:
                delivery.overdue_notified_at = now
                if rider:
                    self.notifications.stage(
                        user_id=rider.user_id,
                        title=f"Delivery Overdue • #{order.order_number}",
                        message=f"Order #{order.order_number} has exceeded its delivery ETA. Complete handover urgently.",
                        notif_type="warning",
                        action_type="delivery",
                        action_payload=str(delivery.id),
                    )
                await self._notify_customer(
                    order.customer_id,
                    title=f"Delivery Running Late • #{order.order_number}",
                    message="Your delivery is taking longer than expected. Our dispatch team is monitoring it.",
                    order_id=order.id,
                )

            if (
                delivery.overdue_escalated_at is None
                and delivery.delivery_due_at is not None
                and now >= delivery.delivery_due_at + escalation_delta
            ):
                delivery.overdue_escalated_at = now
                if rider:
                    rider.overdue_deliveries_count += 1
                    rider.penalty_points += 15
                    self.notifications.stage(
                        user_id=rider.user_id,
                        title=f"Overdue SLA Consequence • #{order.order_number}",
                        message="15 penalty points recorded for long-overdue delivery.",
                        notif_type="penalty",
                    )
                self.audit.record(
                    actor_id=None,
                    action="delivery.transit_sla_escalated",
                    entity_type="delivery",
                    entity_id=delivery.id,
                    after={"rider_id": delivery.rider_id, "order_id": order.id},
                )
            await self.db.commit()
            stats["overdue_deliveries"] += 1

        return stats

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
            "order_status": order.status.value,
            "delivery_id": delivery.id,
            "status": delivery.status.value,
            "is_delivered": delivery.status == DeliveryStatus.DELIVERED,
            "is_overdue": delivery.is_overdue,
            "routing_algorithm": delivery.routing_algorithm,
            "estimated_distance_m": delivery.estimated_distance_m,
            "estimated_duration_s": delivery.estimated_duration_s,
            "estimated_minutes": max(1, round(delivery.estimated_duration_s / 60)) if delivery.estimated_duration_s else None,
            "offer_expires_at": delivery.offer_expires_at,
            "pickup_due_at": delivery.pickup_due_at,
            "delivery_due_at": delivery.delivery_due_at,
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
