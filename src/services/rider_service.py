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

from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import AppError, BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from src.models import ApprovalStatus, Rider, RiderStatus, User, UserRole, VehicleType
from src.repositories import RiderRepository
from src.schemas import RiderApply, RiderGoStatus, RiderLocation
from utilities import utc_now

from services.audit_service import AuditService


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
        a RIDER-role user submits their documents. Starts PENDING; an admin vets it
        """
        if user.role is not UserRole.RIDER:
            raise ForbiddenError("Only rider accounts can apply")
        if await self.riders.get_by_user_id(user.id) is not None:
            raise ConflictError(["rider profile"])

        if data.licence_expiry is not None and data.licence_expiry <= date.today():
            raise AppError("Your driving licence has expired")

        taken = await self.riders.conflicting_fields(
            national_id_number=data.national_id_number, vehicle_plate=data.vehicle_plate
        )
        if taken:
            raise ConflictError(taken)

        rider = Rider(user_id=user.id, **data.model_dump())
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
