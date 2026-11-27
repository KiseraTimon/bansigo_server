# src/routers/server/staff.py

"""
Internal store staff operational router (Pickers, Cashiers, Stock Clerks, Dispatchers, Store Managers).
Excluded from public OpenAPI schemas and mounted without /api prefix per architectural security policy.
"""

from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query

from src.dependencies import (
    get_delivery_service,
    get_inventory_service,
    get_order_service,
    require_roles,
)
from src.models import FulfilmentType, OrderStatus, PickStatus, User, UserRole
from src.schemas import PickItemIn
from src.services import DeliveryService, InventoryService, OrderService
from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(include_in_schema=False)

StaffActorDep = Annotated[User, Depends(require_roles(UserRole.STAFF, UserRole.ADMIN))]
OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
DeliveryServiceDep = Annotated[DeliveryService, Depends(get_delivery_service)]
InventoryServiceDep = Annotated[InventoryService, Depends(get_inventory_service)]


@router.get("/orders")
async def staff_list_orders(
    _: StaffActorDep,
    order_service: OrderServiceDep,
    status_filter: Optional[str] = Query(None, alias="status"),
    fulfilment_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
):
    st = OrderStatus(status_filter) if status_filter else None
    ft = FulfilmentType(fulfilment_type) if fulfilment_type else None
    orders, total = await order_service.list_for_staff(st, ft, page=page, per_page=per_page)
    return {
        "total": total,
        "page": page,
        "items": [
            {
                "id": o.id,
                "order_number": o.order_number,
                "status": o.status.value,
                "fulfilment_type": o.fulfilment_type.value,
                "payment_status": o.payment_status.value,
                "total": str(o.total),
            }
            for o in orders
        ],
    }


@router.post("/orders/{order_id}/start-picking")
async def staff_start_picking(
    order_id: int,
    actor: StaffActorDep,
    order_service: OrderServiceDep,
):
    order = await order_service.start_picking(order_id, actor=actor)
    return {
        "detail": f"Order #{order.order_number} moved to PREPARING",
        "status": order.status.value,
        "assigned_picker_id": order.assigned_picker_id,
    }


@router.post("/orders/{order_id}/items/{item_id}/pick")
async def staff_pick_order_item(
    order_id: int,
    item_id: int,
    actor: StaffActorDep,
    order_service: OrderServiceDep,
    pick_status: str = Form(...),
    quantity_picked: Decimal = Form(...),
    substitute_product_id: Optional[int] = Form(None),
):
    try:
        ps = PickStatus(pick_status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pick status")

    order = await order_service.record_pick(
        order_id,
        item_id,
        PickItemIn(
            pick_status=ps,
            quantity_picked=quantity_picked,
            substitute_product_id=substitute_product_id,
        ),
        actor=actor,
    )
    return {"detail": f"Line item {item_id} picked ({ps.value}) on Order #{order.order_number}"}


@router.post("/orders/{order_id}/finish-picking")
async def staff_finish_picking(
    order_id: int,
    actor: StaffActorDep,
    order_service: OrderServiceDep,
    delivery_service: DeliveryServiceDep,
):
    order = await order_service.finish_picking(order_id, actor=actor)
    if order.delivery is not None and order.delivery.rider_id is None:
        await delivery_service.try_auto_dispatch(order.delivery.id, dispatcher=actor)
    return {
        "detail": f"Order #{order.order_number} packed & READY",
        "status": order.status.value,
        "adjusted_total": str(order.adjusted_total) if order.adjusted_total is not None else str(order.total),
    }


@router.post("/orders/{order_id}/complete-pickup")
async def staff_complete_pickup(
    order_id: int,
    actor: StaffActorDep,
    order_service: OrderServiceDep,
):
    order = await order_service.mark_completed_pickup(order_id, actor=actor)
    return {
        "detail": f"Click & Collect Order #{order.order_number} handed over",
        "status": order.status.value,
    }


@router.post("/deliveries/{delivery_id}/verify-pickup")
async def staff_verify_store_pickup(
    delivery_id: int,
    actor: StaffActorDep,
    delivery_service: DeliveryServiceDep,
    pickup_code: str = Form(...),
):
    delivery = await delivery_service.verify_store_pickup(delivery_id, pickup_code, actor)
    return {
        "detail": f"Pickup code verified for Delivery #{delivery.id}",
        "status": delivery.status.value,
    }


@router.post("/deliveries/{delivery_id}/reopen")
async def staff_reopen_failed_delivery(
    delivery_id: int,
    actor: StaffActorDep,
    delivery_service: DeliveryServiceDep,
    order_id: int = Form(...),
):
    delivery = await delivery_service.reopen(order_id, dispatcher=actor)
    dispatched = await delivery_service.try_auto_dispatch(delivery.id, dispatcher=actor)
    return {
        "detail": f"Delivery #{delivery.id} reopened",
        "status": delivery.status.value,
        "reassigned_rider_id": dispatched[1].id if dispatched else None,
    }


@router.post("/inventory/{product_id}/receive")
async def staff_receive_stock(
    product_id: int,
    actor: StaffActorDep,
    inventory_service: InventoryServiceDep,
    quantity: Decimal = Form(...),
    supplier_id: Optional[int] = Form(None),
    unit_cost: Optional[Decimal] = Form(None),
    note: Optional[str] = Form(None),
):
    inv = await inventory_service.receive(
        product_id, quantity, actor_id=actor.id, supplier_id=supplier_id, unit_cost=unit_cost, note=note
    )
    return {"detail": f"Received {quantity} units", "quantity_on_hand": str(inv.quantity_on_hand)}


@router.post("/inventory/{product_id}/stock-take")
async def staff_stock_take(
    product_id: int,
    actor: StaffActorDep,
    inventory_service: InventoryServiceDep,
    counted: Decimal = Form(...),
    note: Optional[str] = Form(None),
):
    inv = await inventory_service.stock_take(product_id, counted, actor_id=actor.id, note=note)
    return {"detail": "Stock take recorded", "quantity_on_hand": str(inv.quantity_on_hand)}
