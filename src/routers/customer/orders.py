# src/routers/customer/orders.py

from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query, status

from src.dependencies import CurrentCustomer, get_order_service, get_payment_service
from src.exceptions import ForbiddenError
from src.models import OrderStatus
from src.schemas import (
    CancelRequest,
    CheckoutRequest,
    ManualPaymentIn,
    OrderDetail,
    OrderSummary,
    Page,
    PaymentOut,
    StkPushRequest,
)
from src.services import OrderService, PaymentService
from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["customer-orders"])
OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]

ONGOING_STATUSES = [
    OrderStatus.PENDING_PAYMENT,
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
    OrderStatus.READY,
    OrderStatus.OUT_FOR_DELIVERY,
]

HISTORY_STATUSES = [
    OrderStatus.COMPLETED,
    OrderStatus.CANCELLED,
]


@router.get(
    "/orders",
    response_model=Page[OrderSummary],
    status_code=status.HTTP_200_OK,
    summary="List customer orders",
)
async def list_orders(
    customer: CurrentCustomer,
    service: OrderServiceDep,
    tab: Literal["ongoing", "history", "all"] = Query("ongoing"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
) -> Page[OrderSummary]:
    """
    Returns orders for the authenticated customer filtered by tab (ongoing vs history).
    """
    filter_statuses = None
    if tab == "ongoing":
        filter_statuses = ONGOING_STATUSES
    elif tab == "history":
        filter_statuses = HISTORY_STATUSES

    orders, total = await service.list_for_customer(
        customer=customer,
        page=page,
        per_page=per_page,
        statuses=filter_statuses,
    )
    items = [OrderSummary.model_validate(o) for o in orders]
    return Page.of(items=items, total=total, page=page, per_page=per_page)


@router.get(
    "/orders/{order_id}",
    response_model=OrderDetail,
    status_code=status.HTTP_200_OK,
    summary="Get customer order detail",
)
async def get_order_detail(
    order_id: int,
    customer: CurrentCustomer,
    service: OrderServiceDep,
) -> OrderDetail:
    """
    Returns detailed snapshot of an order including line items and status history.
    """
    order = await service.get_for_customer(customer=customer, order_id=order_id)
    return OrderDetail.model_validate(order)


@router.post(
    "/orders/checkout",
    response_model=OrderDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Place a new order",
)
async def checkout(
    data: CheckoutRequest,
    customer: CurrentCustomer,
    service: OrderServiceDep,
) -> OrderDetail:
    """
    Validates inventory, locks prices, and creates a new customer order.
    """
    if not customer.user.is_verified:
        raise ForbiddenError("Email verification is required before placing an order. Please verify your email address.")
    order = await service.checkout(customer=customer, user=customer.user, data=data)
    return OrderDetail.model_validate(order)


@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderDetail,
    status_code=status.HTTP_200_OK,
    summary="Cancel customer order",
)
async def cancel_order(
    order_id: int,
    data: CancelRequest,
    customer: CurrentCustomer,
    service: OrderServiceDep,
) -> OrderDetail:
    """
    Cancels an order before preparation and releases reserved stock.
    """
    order = await service.cancel_by_customer(
        customer=customer, user=customer.user, order_id=order_id, reason=data.reason
    )
    return OrderDetail.model_validate(order)


@router.post(
    "/orders/{order_id}/pay/mpesa",
    response_model=PaymentOut,
    status_code=status.HTTP_200_OK,
    summary="Initiate M-Pesa STK push for order",
)
async def pay_mpesa(
    order_id: int,
    data: StkPushRequest,
    customer: CurrentCustomer,
    payments: PaymentServiceDep,
) -> PaymentOut:
    if not customer.user.is_verified:
        raise ForbiddenError("Email verification is required before paying for an order. Please verify your email address.")
    payment = await payments.initiate_stk(
        customer=customer, user=customer.user, order_id=order_id, data=data
    )
    return PaymentOut.model_validate(payment)


@router.post(
    "/orders/{order_id}/pay/manual",
    response_model=OrderDetail,
    status_code=status.HTTP_200_OK,
    summary="Manually confirm M-Pesa transaction code",
)
async def pay_manual(
    order_id: int,
    data: ManualPaymentIn,
    customer: CurrentCustomer,
    payments: PaymentServiceDep,
    orders: OrderServiceDep,
) -> OrderDetail:
    if not customer.user.is_verified:
        raise ForbiddenError("Email verification is required before paying for an order. Please verify your email address.")
    await payments.confirm_manual_mpesa(
        customer=customer,
        user=customer.user,
        order_id=order_id,
        transaction_code=data.transaction_code,
    )
    order = await orders.get_for_customer(customer=customer, order_id=order_id)
    return OrderDetail.model_validate(order)


@router.get(
    "/orders/{order_id}/payment-status",
    response_model=PaymentOut | None,
    status_code=status.HTTP_200_OK,
    summary="Get latest payment status for order",
)
async def get_payment_status(
    order_id: int,
    customer: CurrentCustomer,
    payments: PaymentServiceDep,
) -> PaymentOut | None:
    payment = await payments.get_latest_payment(customer=customer, order_id=order_id)
    return PaymentOut.model_validate(payment) if payment else None
