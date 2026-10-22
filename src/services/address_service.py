# src/services/address_service.py

"""
a customer's address book + the shop's delivery zones.

A zone sets the delivery fee and the minimum basket, so every saved address belongs to an ACTIVE zone
(the customer picks it; the app shows the fee before checkout).
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import BusinessRuleError, ConflictError, NotFoundError
from src.models import Address, Customer, DeliveryZone
from src.repositories import AddressRepository, DeliveryZoneRepository
from src.schemas import AddressCreate, AddressUpdate, DeliveryZoneCreate, DeliveryZoneUpdate

from dump.services.audit_service import AuditService

MAX_ADDRESSES_PER_CUSTOMER = 10


class AddressService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.addresses = AddressRepository(db)
        self.zones = DeliveryZoneRepository(db)
        self.audit = AuditService(db)


    # zones (admin writes, everyone reads active ones)
    async def list_zones(self, *, active_only: bool = True) -> list[DeliveryZone]:
        return await self.zones.list_all(active_only)


    async def create_zone(self, data: DeliveryZoneCreate, actor_id: int) -> DeliveryZone:
        if await self.zones.name_taken(data.name):
            raise ConflictError(["name"])

        zone = DeliveryZone(**data.model_dump(), created_by=actor_id, updated_by=actor_id)
        self.db.add(zone)
        await self._commit_zone()
        return zone


    async def update_zone(self, zone_id: int, data: DeliveryZoneUpdate, actor_id: int) -> DeliveryZone:
        zone = await self.zones.get_by_id(zone_id)
        if zone is None:
            raise NotFoundError("Delivery zone not found")

        changes = data.model_dump(exclude_unset=True)
        if "name" in changes and await self.zones.name_taken(changes["name"], exclude_id=zone_id):
            raise ConflictError(["name"])

        before = {f: getattr(zone, f) for f in ("delivery_fee", "min_order_amount", "is_active")
                  if f in changes and changes[f] != getattr(zone, f)}

        for field, value in changes.items():
            setattr(zone, field, value)
        zone.updated_by = actor_id

        if before:
            self.audit.record(actor_id=actor_id, action="zone.updated", entity_type="delivery_zone", entity_id=zone_id,
                              before=before, after={f: changes[f] for f in before})

        await self._commit_zone()
        return zone


    async def _commit_zone(self) -> None:
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ConflictError(["name"])


    # a customer's addresses
    async def list_for(self, customer: Customer) -> list[Address]:
        return await self.addresses.list_for_customer(customer.id)


    async def get_for(self, customer: Customer, address_id: int) -> Address:
        address = await self.addresses.get_for_customer(address_id, customer.id)
        if address is None:
            raise NotFoundError("Address not found")
        return address


    async def _active_zone(self, zone_id: int) -> DeliveryZone:
        zone = await self.zones.get_by_id(zone_id)
        if zone is None or not zone.is_active:
            raise BusinessRuleError("We do not deliver to that zone yet")
        return zone


    async def create(self, customer: Customer, data: AddressCreate) -> Address:
        if await self.addresses.count_for_customer(customer.id) >= MAX_ADDRESSES_PER_CUSTOMER:
            raise BusinessRuleError(f"You can save at most {MAX_ADDRESSES_PER_CUSTOMER} addresses")

        await self._active_zone(data.zone_id)

        # the first address is the default; otherwise only if asked
        make_default = data.is_default or await self.addresses.count_for_customer(customer.id) == 0

        address = Address(customer_id=customer.id, **data.model_dump(exclude={"is_default"}), is_default=make_default)
        if make_default:
            await self.addresses.clear_default(customer.id)

        self.db.add(address)
        await self.db.commit()
        return await self.get_for(customer, address.id)


    async def update(self, customer: Customer, address_id: int, data: AddressUpdate) -> Address:
        address = await self.get_for(customer, address_id)
        changes = data.model_dump(exclude_unset=True)

        if "zone_id" in changes:
            await self._active_zone(changes["zone_id"])

        if changes.get("is_default") is True:
            await self.addresses.clear_default(customer.id, except_id=address.id)
        elif changes.get("is_default") is False and address.is_default:
            raise BusinessRuleError("Choose another address as the default instead")

        for field, value in changes.items():
            setattr(address, field, value)

        await self.db.commit()
        return await self.get_for(customer, address_id)


    async def delete(self, customer: Customer, address_id: int) -> None:
        """
        safe for order history: orders SNAPSHOT the address text and pin, and their FK is ON DELETE SET NULL
        """
        address = await self.get_for(customer, address_id)
        was_default = address.is_default
        await self.addresses.delete(address)

        # never leave a customer with addresses but no default
        if was_default:
            remaining = await self.addresses.list_for_customer(customer.id)
            if remaining:
                remaining[0].is_default = True

        await self.db.commit()
