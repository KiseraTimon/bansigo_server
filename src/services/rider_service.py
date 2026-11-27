# src/services/rider_service.py

r"""
the rider's own profile + admin vetting.

    PENDING --approve--> APPROVED --suspend--> SUSPENDED --approve--> APPROVED
       \--reject--> REJECTED                     (only APPROVED riders can go online or be assigned work)

RiderStatus (OFFLINE / AVAILABLE / BUSY) is the live state. BUSY is set and cleared ONLY by DeliveryService
(assign / finish), never by the rider, so nobody can free themselves mid-delivery.

TODO (model note): last_latitude/longitude/last_seen_at change every few seconds. They are written straight to
the DB here for now; the model's TODO says to move them to Redis, and only this file needs to change when you do.
"""

from datetime import date, timedelta
from decimal import Decimal
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.exceptions import AppError, BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from src.models import ApprovalStatus, Delivery, DeliveryStatus, PaymentMethod, Rider, RiderPayout, RiderStatus, User, UserRole, VehicleType
from src.repositories import RiderRepository
from src.schemas import RiderApply, RiderGoStatus, RiderLocation
from utilities import utc_now

from .audit_service import AuditService


class RiderService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.riders = RiderRepository(db)
        self.audit = AuditService(db)


    # the rider
    async def for_user(self, user: User) -> Rider:
        rider = await self.riders.get_by_user_id(user.id)
        if rider is None:
            raise NotFoundError("Rider profile not found")
        return rider


    async def apply(self, user: User, data: RiderApply) -> Rider:
        """
        a RIDER-role user submits or updates their documents. Starts/resets to PENDING for admin vetting.
        """
        if user.role is not UserRole.RIDER:
            raise ForbiddenError("Only rider accounts can apply")

        if data.licence_expiry is not None and data.licence_expiry <= date.today():
            raise AppError("Your driving licence has expired")

        existing_rider = await self.riders.get_by_user_id(user.id)
        exclude_id = existing_rider.id if existing_rider else None

        taken = await self.riders.conflicting_fields(
            national_id_number=data.national_id_number,
            vehicle_plate=data.vehicle_plate,
            exclude_id=exclude_id
        )
        if taken:
            raise ConflictError(taken)

        if existing_rider is not None:
            # Update the existing rider record with business vetting details
            for key, val in data.model_dump().items():
                setattr(existing_rider, key, val)
            existing_rider.approval_status = ApprovalStatus.PENDING
            rider = existing_rider
        else:
            rider = Rider(user_id=user.id, approval_status=ApprovalStatus.PENDING, **data.model_dump())
            self.db.add(rider)

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ConflictError(["national_id_number or vehicle_plate"])
        await self.db.refresh(rider)
        return rider


    async def set_availability(self, user: User, data: RiderGoStatus) -> Rider:
        """
        the rider taps online/offline. BUSY can never be chosen, and a BUSY rider cannot leave
        """
        rider = await self.riders.get_for_update((await self.for_user(user)).id)

        if data.status is RiderStatus.BUSY:
            raise AppError("BUSY is set automatically when you accept a delivery")
        if rider.status is RiderStatus.BUSY:
            raise BusinessRuleError("Finish your current delivery first")

        if data.status is RiderStatus.AVAILABLE:
            if rider.approval_status is not ApprovalStatus.APPROVED:
                raise BusinessRuleError("Your account has not been approved yet")
            if (
                rider.vehicle_type is not VehicleType.BICYCLE
                and rider.licence_expiry is not None and rider.licence_expiry <= date.today()
            ):
                raise BusinessRuleError("Your driving licence has expired; update it to go online")
            rider.last_seen_at = utc_now()

        rider.status = data.status
        await self.db.commit()
        return rider


    async def update_location(self, user: User, data: RiderLocation) -> None:
        """
        a position ping (the Kotlin app sends these while online)
        """
        rider = await self.for_user(user)
        if rider.status is RiderStatus.OFFLINE:
            return                                   # offline riders are not tracked
        rider.last_latitude, rider.last_longitude = data.latitude, data.longitude
        rider.last_seen_at = utc_now()
        await self.db.commit()


    # admin vetting
    async def _decide(self, rider_id: int, admin: User, to: ApprovalStatus, reason: str | None) -> Rider:
        rider = await self.riders.get_for_update(rider_id)
        if rider is None:
            raise NotFoundError("Rider not found")
        if to in (ApprovalStatus.REJECTED, ApprovalStatus.SUSPENDED) and not reason:
            raise AppError("A reason is required")

        before = rider.approval_status
        if before is ApprovalStatus.NEW and to is ApprovalStatus.APPROVED:
            raise BusinessRuleError("Cannot approve a rider before they submit vetting documents")
        if before is to:
            raise BusinessRuleError(f"The rider is already {to.value}")

        rider.approval_status = to
        if to is ApprovalStatus.APPROVED:
            rider.approved_at, rider.approved_by = utc_now(), admin.id
        else:
            # a rider who is no longer approved must stop receiving work immediately
            if rider.status is RiderStatus.AVAILABLE:
                rider.status = RiderStatus.OFFLINE

        self.audit.record(actor_id=admin.id, action=f"rider.{to.value}", entity_type="rider", entity_id=rider_id,
                          before={"approval_status": before}, after={"approval_status": to, "reason": reason})
        await self.db.commit()
        return rider


    async def approve(self, rider_id: int, admin: User) -> Rider:
        return await self._decide(rider_id, admin, ApprovalStatus.APPROVED, None)

    async def reject(self, rider_id: int, admin: User, reason: str | None) -> Rider:
        return await self._decide(rider_id, admin, ApprovalStatus.REJECTED, reason)

    async def suspend(self, rider_id: int, admin: User, reason: str | None) -> Rider:
        return await self._decide(rider_id, admin, ApprovalStatus.SUSPENDED, reason)

    async def list_by_approval(self, status: ApprovalStatus, page: int, per_page: int):
        return await self.riders.list_by_approval(status, page, per_page)

    async def list_dispatchable(self) -> list[Rider]:
        return await self.riders.list_dispatchable()

    async def get_wallet(self, user: User) -> dict:
        rider = await self.for_user(user)
        now = utc_now()
        today = now.date()
        week_ago = now - timedelta(days=7)

        deliv_stmt = (
            select(Delivery)
            .where(Delivery.rider_id == rider.id, Delivery.status == DeliveryStatus.DELIVERED)
            .options(selectinload(Delivery.order))
            .order_by(Delivery.delivered_at.desc())
        )
        delivered = list((await self.db.execute(deliv_stmt)).scalars().all())

        payout_stmt = (
            select(RiderPayout)
            .where(RiderPayout.rider_id == rider.id)
            .order_by(RiderPayout.created_at.desc())
        )
        payouts = list((await self.db.execute(payout_stmt)).scalars().all())

        total_earnings = sum((d.rider_fee for d in delivered), Decimal("0.00"))
        today_earnings = sum(
            (d.rider_fee for d in delivered if d.delivered_at and d.delivered_at.date() == today),
            Decimal("0.00"),
        )
        weekly_earnings = sum(
            (d.rider_fee for d in delivered if d.delivered_at and d.delivered_at >= week_ago),
            Decimal("0.00"),
        )
        total_distance_km = round(sum((d.estimated_distance_m or 0) / 1000.0 for d in delivered), 2)
        completed_count = len(delivered)
        avg_fee = (total_earnings / completed_count).quantize(Decimal("0.01")) if completed_count > 0 else Decimal("0.00")

        cod_cash_in_hand = sum(
            (
                d.order.total
                for d in delivered
                if d.order and d.order.payment_method == PaymentMethod.CASH
                and d.delivered_at and d.delivered_at.date() == today
            ),
            Decimal("0.00"),
        )

        total_withdrawn = sum((p.amount for p in payouts), Decimal("0.00"))
        available_balance = max(Decimal("0.00"), total_earnings - total_withdrawn)

        tx_items: list[tuple[float, dict]] = []
        for d in delivered:
            ts = d.delivered_at or d.updated_at or d.created_at
            order_num = f"#{d.order.order_number}" if d.order else f"#{d.order_id}"
            tx_items.append((
                ts.timestamp() if ts else 0.0,
                {
                    "id": f"earn-{d.id}",
                    "order_number": order_num,
                    "amount": d.rider_fee,
                    "type": "DELIVERY_EARNING",
                    "description": f"Delivery Fee: Order {order_num}",
                    "timestamp": ts.strftime("%b %d, %I:%M %p") if ts else "-",
                    "distance_km": round((d.estimated_distance_m or 0) / 1000.0, 2),
                    "status": "Completed",
                    "reference_code": f"EARN-{d.id}",
                },
            ))

        for p in payouts:
            ts = p.created_at
            tx_items.append((
                ts.timestamp() if ts else 0.0,
                {
                    "id": f"payout-{p.id}",
                    "order_number": "MPESA-B2C",
                    "amount": p.amount,
                    "type": "PAYOUT_WITHDRAWAL",
                    "description": f"M-Pesa Payout: {p.phone}",
                    "timestamp": ts.strftime("%b %d, %I:%M %p") if ts else "-",
                    "distance_km": None,
                    "status": p.status,
                    "reference_code": p.reference_code,
                },
            ))

        tx_items.sort(key=lambda x: x[0], reverse=True)

        return {
            "total_earnings": total_earnings,
            "available_balance": available_balance,
            "cod_cash_in_hand": cod_cash_in_hand,
            "today_earnings": today_earnings,
            "weekly_earnings": weekly_earnings,
            "completed_trips_count": completed_count,
            "pending_payouts": Decimal("0.00"),
            "average_trip_fee": avg_fee,
            "total_distance_km": total_distance_km,
            "transactions": [item[1] for item in tx_items],
        }

    async def withdraw_wallet(self, user: User, amount: Decimal, phone: str) -> tuple[RiderPayout, Decimal]:
        if amount < Decimal("50.00"):
            raise AppError("Minimum withdrawal is KES 50.00")

        wallet = await self.get_wallet(user)
        available = wallet["available_balance"]
        if amount > available:
            raise BusinessRuleError(f"Insufficient balance (Available: KES {available:.2f})")

        rider = await self.for_user(user)
        ref = f"QK{uuid.uuid4().hex[:8].upper()}"
        payout = RiderPayout(
            rider_id=rider.id,
            amount=amount,
            phone=phone,
            reference_code=ref,
            status="Settled",
        )
        self.db.add(payout)
        await self.db.commit()
        await self.db.refresh(payout)
        new_balance = max(Decimal("0.00"), available - amount)
        return payout, new_balance
