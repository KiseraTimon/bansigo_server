# src/services/inventory_service.py

"""
the ONLY code that changes stock. Two numbers per product:

    quantity_on_hand      physically in the shop. Moves only when goods really move (receipt, pick, wastage, count)
                          and every move writes a StockMovement ledger line
    quantity_reserved     promised to open orders, not yet picked. Moves at checkout / cancel / pick; NOT a ledger event

    available = on_hand - reserved   (what a new order may still take)

Every method locks the stock rows (SELECT ... FOR UPDATE, ascending product_id) before reading them, so two
customers racing for the last tin of tomatoes cannot both win. Methods stage changes and never commit:
the caller (checkout, pick, ...) commits the whole use case at once.
"""

from decimal import Decimal
from typing import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import BusinessRuleError, InsufficientStockError, NotFoundError
from src.models import Inventory, MovementType, StockMovement
from src.repositories import InventoryRepository, ProductRepository, StockMovementRepository
from utilities import get_logger, utc_now

from .audit_service import AuditService

log = get_logger(__name__)


class InventoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.stock = InventoryRepository(db)
        self.movements = StockMovementRepository(db)
        self.products = ProductRepository(db)
        self.audit = AuditService(db)


    # internals
    async def _lock_one(self, product_id: int) -> Inventory:
        inv = (await self.stock.lock_for_products([product_id])).get(product_id)
        if inv is None:
            raise NotFoundError("Product has no stock record")
        return inv

    def _log(
        self, inv: Inventory, kind: MovementType, change: Decimal, *, actor_id: int | None,
        supplier_id: int | None = None, unit_cost: Decimal | None = None,
        reference_type: str | None = None, reference_id: str | None = None, note: str | None = None,
    ) -> None:
        """one ledger line. quantity_after is the on-hand RIGHT AFTER the change (read the history without re-adding)"""
        self.db.add(StockMovement(
            product_id=inv.product_id, supplier_id=supplier_id, performed_by=actor_id,
            movement_type=kind, quantity_change=change, quantity_after=inv.quantity_on_hand,
            unit_cost=unit_cost, reference_type=reference_type, reference_id=reference_id, note=note,
        ))


    # staff operations
    async def receive(
        self, product_id: int, quantity: Decimal, *, actor_id: int, supplier_id: int | None = None,
        unit_cost: Decimal | None = None, note: str | None = None,
    ) -> Inventory:
        """
        goods arrived from a supplier
        """
        inv = await self._lock_one(product_id)
        inv.quantity_on_hand += quantity
        self._log(inv, MovementType.RECEIPT, quantity, actor_id=actor_id, supplier_id=supplier_id,
                  unit_cost=unit_cost, note=note)

        if unit_cost is not None:
            # the product keeps the LAST purchase cost (staff/admin eyes only)
            product = await self.products.get_by_id(product_id)
            product.cost_price = unit_cost

        await self.db.commit()
        return inv


    async def write_off(self, product_id: int, quantity: Decimal, *, actor_id: int, note: str) -> Inventory:
        """
        expired / damaged / stolen. Cannot write off stock that is promised to an open order
        """
        inv = await self._lock_one(product_id)
        if quantity > inv.quantity_on_hand - inv.quantity_reserved:
            raise BusinessRuleError("Cannot write off stock that is reserved for open orders")

        inv.quantity_on_hand -= quantity
        self._log(inv, MovementType.WASTAGE, -quantity, actor_id=actor_id, note=note)
        self.audit.record(actor_id=actor_id, action="stock.written_off", entity_type="product", entity_id=product_id,
                          after={"quantity": quantity, "note": note})
        await self.db.commit()
        return inv


    async def stock_take(self, product_id: int, counted: Decimal, *, actor_id: int, note: str | None = None) -> Inventory:
        """
        a physical count: on-hand becomes the counted number and the difference is booked as an ADJUSTMENT
        """
        inv = await self._lock_one(product_id)
        if counted < inv.quantity_reserved:
            raise BusinessRuleError(
                "The count is lower than the quantity reserved for open orders; resolve those orders first"
            )

        before = inv.quantity_on_hand
        delta = counted - before
        inv.quantity_on_hand = counted
        inv.last_counted_at = utc_now()

        if delta != 0:
            self._log(inv, MovementType.ADJUSTMENT, delta, actor_id=actor_id, note=note)
            self.audit.record(actor_id=actor_id, action="stock.adjusted", entity_type="product", entity_id=product_id,
                              before={"quantity_on_hand": before}, after={"quantity_on_hand": counted, "note": note})

        await self.db.commit()
        return inv


    async def set_reorder(self, product_id: int, level: Decimal, quantity: Decimal | None) -> Inventory:
        inv = await self._lock_one(product_id)
        inv.reorder_level = level
        inv.reorder_quantity = quantity
        await self.db.commit()
        return inv


    # order lifecycle (called by OrderService inside ITS transaction; they do not commit)
    async def reserve(self, lines: Mapping[int, Decimal], names: Mapping[int, str]) -> None:
        """
        promises stock to a new order. All-or-nothing: if ANY line is short nothing is reserved
        :param lines: {product_id: quantity}
        :param names: {product_id: display name} for the error message
        """
        locked = await self.stock.lock_for_products(lines.keys())

        short = [
            names.get(pid, str(pid)) for pid, qty in lines.items()
            if pid not in locked or locked[pid].quantity_on_hand - locked[pid].quantity_reserved < qty
        ]
        if short:
            raise InsufficientStockError(short)

        for pid, qty in lines.items():
            locked[pid].quantity_reserved += qty


    async def release(self, lines: Mapping[int, Decimal]) -> None:
        """
        gives reserved stock back (order cancelled / expired)
        """
        locked = await self.stock.lock_for_products(lines.keys())
        for pid, qty in lines.items():
            inv = locked.get(pid)
            if inv is None:
                continue
            if qty > inv.quantity_reserved:
                log.warning("release of %s exceeds reserved %s for product %s; clamping", qty, inv.quantity_reserved, pid)
                qty = inv.quantity_reserved
            inv.quantity_reserved -= qty


    async def consume_reserved(
        self, product_id: int, reserved_qty: Decimal, picked_qty: Decimal, *, order_number: str, actor_id: int | None
    ) -> None:
        """
        a picker took `picked_qty` off the shelf for a line that had `reserved_qty` promised.
        The whole promise is released; only what was physically taken leaves the shop (a SALE on the ledger).
        picked < reserved is a SHORT/OUT_OF_STOCK line: the difference simply stops being promised
        """
        inv = await self._lock_one(product_id)
        inv.quantity_reserved -= min(reserved_qty, inv.quantity_reserved)

        if picked_qty > 0:
            if picked_qty > inv.quantity_on_hand:
                raise BusinessRuleError("The system shows less stock than you picked; do a stock take first")
            inv.quantity_on_hand -= picked_qty
            self._log(inv, MovementType.SALE, -picked_qty, actor_id=actor_id,
                      reference_type="order", reference_id=order_number)


    async def consume_unreserved(
        self, product_id: int, quantity: Decimal, *, order_number: str, actor_id: int | None, name: str
    ) -> None:
        """
        a SUBSTITUTE product was picked: nobody reserved it, so it must be genuinely available
        """
        inv = await self._lock_one(product_id)
        if quantity > inv.quantity_on_hand - inv.quantity_reserved:
            raise InsufficientStockError([name])

        inv.quantity_on_hand -= quantity
        self._log(inv, MovementType.SALE, -quantity, actor_id=actor_id,
                  reference_type="order", reference_id=order_number, note="substitution")


    async def return_to_shelf(self, product_id: int, quantity: Decimal, *, order_number: str, actor_id: int | None) -> None:
        """
        an already-picked line comes back (order cancelled during/after picking): resellable goods re-enter stock
        """
        inv = await self._lock_one(product_id)
        inv.quantity_on_hand += quantity
        self._log(inv, MovementType.RETURN, quantity, actor_id=actor_id,
                  reference_type="order", reference_id=order_number, note="order cancelled after picking")


    # reads
    async def get(self, product_id: int) -> Inventory:
        inv = await self.stock.get_by_id(product_id)
        if inv is None:
            raise NotFoundError("Product has no stock record")
        return inv

    async def history(self, product_id: int, page: int, per_page: int):
        return await self.movements.list_for_product(product_id, page, per_page)

    async def low_stock(self, page: int, per_page: int):
        return await self.stock.list_low_stock(page, per_page)
