# src/services/admin_service.py

"""
service coordinating administrative operations, role-aware dashboard aggregations,
orders & fulfilment, financial reconciliation & refunds, inventory & supplier ledgers,
actor regulation (staff, riders, admins, customers), dispatch operations, and security governance.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import Settings
from src.exceptions import AppError, BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from src.models import (
    Admin, AdminLevel, ApprovalStatus, AuditLog, Brand, Category, Customer, Delivery,
    DeliveryStatus, DeliveryZone, Inventory, Order, OrderItem, OrderPaymentStatus, OrderStatus,
    Payment, PaymentChannel, PaymentEvent, PaymentMethod, PaymentStatus, Product,
    RecommendationEvent, Refund, RefundStatus, Review, ReviewTargetType, Rider, RiderPayout,
    RiderStatus, Staff, StaffPosition, StockMovement, Supplier, User, UserRole,
)
from src.repositories import (
    AdminRepository, BrandRepository, CategoryRepository, ProductRepository,
    ReviewRepository, RiderRepository, StaffRepository, UserRepository,
)
from src.security import hash_password_async, verify_password_async
from src.services.audit_service import AuditService
from src.services.refund_service import RefundService
from utilities import get_logger, utc_now

log = get_logger(__name__)

_ROLE_CONFIGS: dict[str, dict[str, Any]] = {
    AdminLevel.SUPER.value: {
        "level": "super",
        "title": "Executive Command Center",
        "subtitle": "Full-Spectrum Retail, Logistics, Treasury & Security Governance",
        "badge_label": "Superadmin (Owner)",
        "theme_key": "super",
        "accent_color": "#D32F2F",
        "accent_secondary": "#1A367E",
        "allowed_tabs": [
            "overview", "orders", "dispatch", "products", "inventory",
            "finance", "actors", "reviews", "audit", "security", "account",
        ],
    },
    AdminLevel.OPERATIONS.value: {
        "level": "operations",
        "title": "Store Operations Hub",
        "subtitle": "Order Picking, Fleet Dispatch, Delivery Zones & Workforce Shifts",
        "badge_label": "Operations Manager",
        "theme_key": "operations",
        "accent_color": "#1A367E",
        "accent_secondary": "#0284C7",
        "allowed_tabs": [
            "overview", "orders", "dispatch", "products", "inventory",
            "actors", "reviews", "security", "account",
        ],
    },
    AdminLevel.FINANCE.value: {
        "level": "finance",
        "title": "Finance & Treasury Desk",
        "subtitle": "M-Pesa Reconciliation, Refunds Maker-Checker, VAT & Rider Payouts",
        "badge_label": "Finance Controller",
        "theme_key": "finance",
        "accent_color": "#0F766E",
        "accent_secondary": "#059669",
        "allowed_tabs": [
            "overview", "finance", "orders", "products", "audit", "security", "account",
        ],
    },
    AdminLevel.INVENTORY.value: {
        "level": "inventory",
        "title": "Inventory & Merchandising",
        "subtitle": "Catalogue Variants, Stock Movements, Reorder Alerts & Suppliers",
        "badge_label": "Inventory Manager",
        "theme_key": "inventory",
        "accent_color": "#D97706",
        "accent_secondary": "#B45309",
        "allowed_tabs": [
            "overview", "products", "inventory", "reviews", "security", "account",
        ],
    },
    AdminLevel.SUPPORT.value: {
        "level": "support",
        "title": "Customer Experience & Support",
        "subtitle": "Live Order Care, SLA Escalations, Review Moderation & Account Help",
        "badge_label": "Support Lead",
        "theme_key": "support",
        "accent_color": "#4F46E5",
        "accent_secondary": "#7C3AED",
        "allowed_tabs": [
            "overview", "orders", "dispatch", "reviews", "actors", "security", "account",
        ],
    },
}


class AdminService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self.users = UserRepository(db)
        self.admins = AdminRepository(db)
        self.staff_repo = StaffRepository(db)
        self.riders = RiderRepository(db)
        self.products = ProductRepository(db)
        self.categories = CategoryRepository(db)
        self.brands = BrandRepository(db)
        self.reviews = ReviewRepository(db)
        self.audit = AuditService(db)

    @staticmethod
    def get_role_workspace_config(admin_level: AdminLevel | str) -> dict[str, Any]:
        key = admin_level.value if isinstance(admin_level, AdminLevel) else str(admin_level).lower()
        return dict(_ROLE_CONFIGS.get(key, _ROLE_CONFIGS[AdminLevel.OPERATIONS.value]))

    # -----------------------------------------------------------------------
    # Role-Aware Executive, Ops, Finance, Inventory & Support Aggregations
    # -----------------------------------------------------------------------
    async def get_dashboard_summary(self, admin_level: AdminLevel | str | None = None) -> dict[str, Any]:
        """
        aggregates real-time KPIs across catalogue, orders, finance, inventory, fleet, and CX
        """
        now = utc_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Products & inventory
        total_products = (await self.db.execute(select(func.count(Product.id)))).scalar_one() or 0
        active_products = (
            await self.db.execute(select(func.count(Product.id)).where(Product.is_active.is_(True)))
        ).scalar_one() or 0
        low_stock_count = (
            await self.db.execute(
                select(func.count(Inventory.product_id)).where(Inventory.quantity_on_hand <= Inventory.reorder_level)
            )
        ).scalar_one() or 0
        out_of_stock_count = (
            await self.db.execute(
                select(func.count(Inventory.product_id)).where(Inventory.quantity_on_hand <= 0)
            )
        ).scalar_one() or 0

        val_stmt = select(
            func.coalesce(func.sum(Inventory.quantity_on_hand * Product.price), Decimal("0")),
            func.coalesce(func.sum(Inventory.quantity_on_hand * func.coalesce(Product.cost_price, Decimal("0"))), Decimal("0")),
        ).join(Product, Product.id == Inventory.product_id)
        stock_retail_val, stock_cost_val = (await self.db.execute(val_stmt)).one()

        active_suppliers = (
            await self.db.execute(select(func.count(Supplier.id)).where(Supplier.is_active.is_(True)))
        ).scalar_one() or 0
        today_movements = (
            await self.db.execute(select(func.count(StockMovement.id)).where(StockMovement.created_at >= today_start))
        ).scalar_one() or 0

        # Actors
        total_customers = (
            await self.db.execute(select(func.count(User.id)).where(User.role == UserRole.CUSTOMER))
        ).scalar_one() or 0
        unverified_customers = (
            await self.db.execute(
                select(func.count(User.id)).where(User.role == UserRole.CUSTOMER, User.is_verified.is_(False))
            )
        ).scalar_one() or 0
        total_staff = (await self.db.execute(select(func.count(Staff.id)))).scalar_one() or 0
        staff_on_duty = (
            await self.db.execute(select(func.count(Staff.id)).where(Staff.is_on_duty.is_(True)))
        ).scalar_one() or 0
        total_riders = (await self.db.execute(select(func.count(Rider.id)))).scalar_one() or 0
        online_riders = (
            await self.db.execute(
                select(func.count(Rider.id)).where(
                    Rider.approval_status == ApprovalStatus.APPROVED,
                    Rider.status.in_((RiderStatus.AVAILABLE, RiderStatus.BUSY)),
                )
            )
        ).scalar_one() or 0
        pending_riders = (
            await self.db.execute(
                select(func.count(Rider.id)).where(Rider.approval_status == ApprovalStatus.PENDING)
            )
        ).scalar_one() or 0

        # Orders breakdown
        order_rows = (
            await self.db.execute(
                select(Order.status, func.count(Order.id), func.coalesce(func.sum(Order.total), Decimal("0")))
                .group_by(Order.status)
            )
        ).all()
        order_status_counts: dict[str, int] = {s.value: 0 for s in OrderStatus}
        total_orders = 0
        for st, cnt, _ in order_rows:
            key = st.value if hasattr(st, "value") else str(st)
            order_status_counts[key] = int(cnt or 0)
            total_orders += int(cnt or 0)

        active_orders_count = (
            order_status_counts.get(OrderStatus.CONFIRMED.value, 0)
            + order_status_counts.get(OrderStatus.PREPARING.value, 0)
            + order_status_counts.get(OrderStatus.READY.value, 0)
            + order_status_counts.get(OrderStatus.OUT_FOR_DELIVERY.value, 0)
        )

        settled_statuses = [
            OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY,
            OrderStatus.OUT_FOR_DELIVERY, OrderStatus.COMPLETED,
        ]
        total_revenue_val = (
            await self.db.execute(
                select(func.coalesce(func.sum(Order.total), Decimal("0"))).where(Order.status.in_(settled_statuses))
            )
        ).scalar_one() or Decimal("0")
        today_orders_count = (
            await self.db.execute(select(func.count(Order.id)).where(Order.created_at >= today_start))
        ).scalar_one() or 0
        today_revenue_val = (
            await self.db.execute(
                select(func.coalesce(func.sum(Order.total), Decimal("0")))
                .where(Order.status.in_(settled_statuses), Order.created_at >= today_start)
            )
        ).scalar_one() or Decimal("0")
        total_vat_val = (
            await self.db.execute(
                select(func.coalesce(func.sum(Order.tax_total), Decimal("0"))).where(Order.status.in_(settled_statuses))
            )
        ).scalar_one() or Decimal("0")
        pending_payment_val = (
            await self.db.execute(
                select(func.coalesce(func.sum(Order.total), Decimal("0")))
                .where(Order.status == OrderStatus.PENDING_PAYMENT)
            )
        ).scalar_one() or Decimal("0")

        # Payments, refunds & rider payouts
        paid_by_channel_rows = (
            await self.db.execute(
                select(Payment.channel, func.coalesce(func.sum(Payment.amount), Decimal("0")), func.count(Payment.id))
                .where(Payment.status == PaymentStatus.SUCCEEDED)
                .group_by(Payment.channel)
            )
        ).all()
        channel_totals: dict[str, str] = {"mpesa_stk": "0.00", "mpesa_c2b": "0.00", "cash": "0.00"}
        channel_counts: dict[str, int] = {"mpesa_stk": 0, "mpesa_c2b": 0, "cash": 0}
        for ch, amt, cnt in paid_by_channel_rows:
            k = ch.value if hasattr(ch, "value") else str(ch)
            channel_totals[k] = f"{Decimal(amt):.2f}"
            channel_counts[k] = int(cnt or 0)

        pending_refunds_count = (
            await self.db.execute(
                select(func.count(Refund.id)).where(Refund.status.in_((RefundStatus.REQUESTED, RefundStatus.APPROVED)))
            )
        ).scalar_one() or 0
        pending_refunds_value = (
            await self.db.execute(
                select(func.coalesce(func.sum(Refund.amount), Decimal("0")))
                .where(Refund.status.in_((RefundStatus.REQUESTED, RefundStatus.APPROVED)))
            )
        ).scalar_one() or Decimal("0")
        unprocessed_events_count = (
            await self.db.execute(select(func.count(PaymentEvent.id)).where(PaymentEvent.processed_at.is_(None)))
        ).scalar_one() or 0

        rider_fees_earned = (
            await self.db.execute(
                select(func.coalesce(func.sum(Delivery.rider_fee), Decimal("0")))
                .where(Delivery.status == DeliveryStatus.DELIVERED)
            )
        ).scalar_one() or Decimal("0")
        rider_payouts_settled = (
            await self.db.execute(select(func.coalesce(func.sum(RiderPayout.amount), Decimal("0"))))
        ).scalar_one() or Decimal("0")
        cod_in_hand_today = (
            await self.db.execute(
                select(func.coalesce(func.sum(Order.total), Decimal("0")))
                .join(Delivery, Delivery.order_id == Order.id)
                .where(
                    Order.payment_method == PaymentMethod.CASH,
                    Delivery.status == DeliveryStatus.DELIVERED,
                    Delivery.delivered_at >= today_start,
                )
            )
        ).scalar_one() or Decimal("0")

        # Deliveries & SLAs
        manual_dispatch_count = (
            await self.db.execute(
                select(func.count(Delivery.id)).where(
                    Delivery.needs_manual_assignment.is_(True),
                    Delivery.status == DeliveryStatus.UNASSIGNED,
                )
            )
        ).scalar_one() or 0
        overdue_delivery_count = (
            await self.db.execute(
                select(func.count(Delivery.id)).where(
                    Delivery.is_overdue.is_(True),
                    Delivery.status.notin_((DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED)),
                )
            )
        ).scalar_one() or 0
        active_deliveries_count = (
            await self.db.execute(
                select(func.count(Delivery.id)).where(
                    Delivery.status.in_((
                        DeliveryStatus.UNASSIGNED, DeliveryStatus.ASSIGNED,
                        DeliveryStatus.ACCEPTED, DeliveryStatus.PICKED_UP, DeliveryStatus.ARRIVED,
                    ))
                )
            )
        ).scalar_one() or 0

        # Reviews & recommendations
        critical_reviews_count = (
            await self.db.execute(select(func.count(Review.id)).where(Review.rating <= 3))
        ).scalar_one() or 0
        rec_rows = (
            await self.db.execute(
                select(RecommendationEvent.algorithm, RecommendationEvent.event_type, func.count(RecommendationEvent.id))
                .group_by(RecommendationEvent.algorithm, RecommendationEvent.event_type)
            )
        ).all()
        rec_stats = {"apriori_impressions": 0, "apriori_clicks": 0, "fpgrowth_impressions": 0, "fpgrowth_clicks": 0}
        for algo, evt, cnt in rec_rows:
            if algo in ("apriori", "fpgrowth") and evt in ("impression", "click"):
                key = f"{algo}_{evt}s"
                rec_stats[key] = int(cnt or 0)

        # Role-aware recent audits
        level_key = admin_level.value if isinstance(admin_level, AdminLevel) else (str(admin_level).lower() if admin_level else "super")
        recent_stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(15)
        if level_key == AdminLevel.FINANCE.value:
            recent_stmt = (
                select(AuditLog)
                .where(AuditLog.entity_type.in_(("payment", "refund", "order", "system_settings")))
                .order_by(AuditLog.id.desc())
                .limit(10)
            )
        elif level_key == AdminLevel.INVENTORY.value:
            recent_stmt = (
                select(AuditLog)
                .where(AuditLog.entity_type.in_(("product", "inventory", "supplier")))
                .order_by(AuditLog.id.desc())
                .limit(10)
            )
        recent_audits = (await self.db.execute(recent_stmt)).scalars().all()

        return {
            "total_products": total_products,
            "active_products": active_products,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "stock_retail_value": f"{Decimal(stock_retail_val):.2f}",
            "stock_cost_value": f"{Decimal(stock_cost_val):.2f}",
            "active_suppliers": active_suppliers,
            "today_movements": today_movements,
            "total_customers": total_customers,
            "unverified_customers": unverified_customers,
            "total_staff": total_staff,
            "staff_on_duty": staff_on_duty,
            "total_riders": total_riders,
            "online_riders": online_riders,
            "pending_riders": pending_riders,
            "total_orders": total_orders,
            "today_orders_count": today_orders_count,
            "active_orders_count": active_orders_count,
            "order_status_counts": order_status_counts,
            "total_revenue": f"{total_revenue_val:.2f}",
            "today_revenue": f"{today_revenue_val:.2f}",
            "total_vat": f"{total_vat_val:.2f}",
            "pending_payment_value": f"{pending_payment_val:.2f}",
            "channel_totals": channel_totals,
            "channel_counts": channel_counts,
            "pending_refunds_count": pending_refunds_count,
            "pending_refunds_value": f"{pending_refunds_value:.2f}",
            "unprocessed_events_count": unprocessed_events_count,
            "rider_fees_earned": f"{rider_fees_earned:.2f}",
            "rider_payouts_settled": f"{rider_payouts_settled:.2f}",
            "cod_in_hand_today": f"{cod_in_hand_today:.2f}",
            "active_deliveries_count": active_deliveries_count,
            "manual_dispatch_count": manual_dispatch_count,
            "overdue_delivery_count": overdue_delivery_count,
            "critical_reviews_count": critical_reviews_count,
            "rec_stats": rec_stats,
            "recent_audits": [
                {
                    "id": a.id,
                    "action": a.action,
                    "entity_type": a.entity_type,
                    "entity_id": a.entity_id,
                    "actor_id": a.actor_user_id,
                    "created_at": a.created_at.strftime("%Y-%m-%d %H:%M:%S") if a.created_at else "",
                }
                for a in recent_audits
            ],
        }

    # -----------------------------------------------------------------------
    # Orders & Fulfilment Management
    # -----------------------------------------------------------------------
    async def get_orders_data(self, limit: int = 80) -> dict[str, Any]:
        stmt = (
            select(Order)
            .options(
                selectinload(Order.customer).selectinload(Customer.user),
                selectinload(Order.items),
                selectinload(Order.delivery).selectinload(Delivery.rider).selectinload(Rider.user),
                selectinload(Order.payments),
            )
            .order_by(Order.id.desc())
            .limit(limit)
        )
        orders = list((await self.db.execute(stmt)).scalars().all())
        rows = []
        for o in orders:
            cust_name = "Customer"
            cust_phone = "-"
            if o.customer and o.customer.user:
                cust_name = f"{o.customer.user.first_name} {o.customer.user.last_name}".strip()
                cust_phone = o.customer.user.phone or "-"
            rider_name = None
            if o.delivery and o.delivery.rider and o.delivery.rider.user:
                rider_name = f"{o.delivery.rider.user.first_name} {o.delivery.rider.user.last_name}".strip()
            latest_pay = sorted(o.payments, key=lambda p: p.id, reverse=True)[0] if o.payments else None
            rows.append({
                "id": o.id,
                "order_number": o.order_number,
                "customer_name": o.delivery_recipient_name or cust_name,
                "customer_phone": o.delivery_recipient_phone or cust_phone,
                "status": o.status.value,
                "payment_status": o.payment_status.value,
                "payment_method": o.payment_method.value,
                "payment_receipt": latest_pay.provider_receipt if latest_pay else None,
                "fulfilment_type": o.fulfilment_type.value,
                "item_count": len(o.items),
                "subtotal": f"{o.subtotal:.2f}",
                "delivery_fee": f"{o.delivery_fee:.2f}",
                "tax_total": f"{o.tax_total:.2f}",
                "total": f"{o.total:.2f}",
                "address_text": o.delivery_address_text or ("Click & Collect" if o.fulfilment_type.value == "pickup" else "-"),
                "delivery_status": o.delivery.status.value if o.delivery else None,
                "rider_name": rider_name,
                "created_at": o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "-",
            })
        return {"orders": rows}

    async def get_order_detail(self, order_id: int) -> dict[str, Any]:
        stmt = (
            select(Order)
            .where(Order.id == order_id)
            .options(
                selectinload(Order.customer).selectinload(Customer.user),
                selectinload(Order.items),
                selectinload(Order.status_history),
                selectinload(Order.delivery).selectinload(Delivery.rider).selectinload(Rider.user),
                selectinload(Order.payments),
            )
        )
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if order is None:
            raise NotFoundError("Order not found")

        cust_name = "Customer"
        cust_email = "-"
        if order.customer and order.customer.user:
            cust_name = f"{order.customer.user.first_name} {order.customer.user.last_name}".strip()
            cust_email = order.customer.user.email

        return {
            "id": order.id,
            "order_number": order.order_number,
            "status": order.status.value,
            "payment_status": order.payment_status.value,
            "payment_method": order.payment_method.value,
            "fulfilment_type": order.fulfilment_type.value,
            "subtotal": f"{order.subtotal:.2f}",
            "delivery_fee": f"{order.delivery_fee:.2f}",
            "discount_total": f"{order.discount_total:.2f}",
            "tax_total": f"{order.tax_total:.2f}",
            "total": f"{order.total:.2f}",
            "adjusted_total": f"{order.adjusted_total:.2f}" if order.adjusted_total is not None else None,
            "customer_name": cust_name,
            "customer_email": cust_email,
            "recipient_name": order.delivery_recipient_name or cust_name,
            "recipient_phone": order.delivery_recipient_phone or "-",
            "address_text": order.delivery_address_text or "Click & Collect",
            "customer_note": order.customer_note,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "-",
            "items": [
                {
                    "id": it.id,
                    "product_id": it.product_id,
                    "product_name": it.product_name,
                    "sku": it.sku,
                    "unit": it.unit.value if hasattr(it.unit, "value") else str(it.unit),
                    "unit_price": f"{it.unit_price:.2f}",
                    "quantity": str(it.quantity),
                    "quantity_picked": str(it.quantity_picked) if it.quantity_picked is not None else None,
                    "pick_status": it.pick_status.value,
                    "line_total": f"{it.line_total:.2f}",
                }
                for it in order.items
            ],
            "history": [
                {
                    "from_status": h.from_status.value if h.from_status else None,
                    "to_status": h.to_status.value,
                    "note": h.note,
                    "created_at": h.created_at.strftime("%Y-%m-%d %H:%M") if h.created_at else "-",
                }
                for h in order.status_history
            ],
            "payments": [
                {
                    "id": p.id,
                    "channel": p.channel.value,
                    "status": p.status.value,
                    "amount": f"{p.amount:.2f}",
                    "payer_phone": p.payer_phone or "-",
                    "receipt": p.provider_receipt or "-",
                    "created_at": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "-",
                }
                for p in order.payments
            ],
        }

    # -----------------------------------------------------------------------
    # Finance, Payments, Refunds & Rider Payouts
    # -----------------------------------------------------------------------
    async def get_finance_data(self, limit: int = 60) -> dict[str, Any]:
        pay_stmt = (
            select(Payment)
            .options(selectinload(Payment.order))
            .order_by(Payment.id.desc())
            .limit(limit)
        )
        payments = list((await self.db.execute(pay_stmt)).scalars().all())

        event_stmt = (
            select(PaymentEvent)
            .order_by(PaymentEvent.processed_at.is_(None).desc(), PaymentEvent.id.desc())
            .limit(40)
        )
        events = list((await self.db.execute(event_stmt)).scalars().all())

        refund_stmt = (
            select(Refund)
            .options(selectinload(Refund.payment).selectinload(Payment.order))
            .order_by(Refund.id.desc())
            .limit(50)
        )
        refunds = list((await self.db.execute(refund_stmt)).scalars().all())

        payout_stmt = (
            select(RiderPayout)
            .order_by(RiderPayout.id.desc())
            .limit(40)
        )
        payouts = list((await self.db.execute(payout_stmt)).scalars().all())
        rider_ids = {p.rider_id for p in payouts}
        rider_map: dict[int, str] = {}
        if rider_ids:
            r_rows = (
                await self.db.execute(
                    select(Rider).options(selectinload(Rider.user)).where(Rider.id.in_(rider_ids))
                )
            ).scalars().all()
            for r in r_rows:
                rider_map[r.id] = f"{r.user.first_name} {r.user.last_name}".strip() if r.user else f"Rider #{r.id}"

        return {
            "payments": [
                {
                    "id": p.id,
                    "order_id": p.order_id,
                    "order_number": p.order.order_number if p.order else f"ORD-{p.order_id}",
                    "channel": p.channel.value,
                    "status": p.status.value,
                    "amount": f"{p.amount:.2f}",
                    "payer_phone": p.payer_phone or "-",
                    "provider_receipt": p.provider_receipt or "-",
                    "result_description": p.result_description or "-",
                    "paid_at": p.paid_at.strftime("%Y-%m-%d %H:%M") if p.paid_at else "-",
                    "created_at": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "-",
                }
                for p in payments
            ],
            "payment_events": [
                {
                    "id": ev.id,
                    "source": ev.source.value,
                    "external_id": ev.external_id,
                    "is_authentic": ev.is_authentic,
                    "processed_at": ev.processed_at.strftime("%Y-%m-%d %H:%M") if ev.processed_at else None,
                    "processing_error": ev.processing_error,
                    "received_at": ev.received_at.strftime("%Y-%m-%d %H:%M") if ev.received_at else "-",
                }
                for ev in events
            ],
            "refunds": [
                {
                    "id": rf.id,
                    "payment_id": rf.payment_id,
                    "order_number": rf.payment.order.order_number if rf.payment and rf.payment.order else "-",
                    "amount": f"{rf.amount:.2f}",
                    "reason": rf.reason,
                    "status": rf.status.value,
                    "requested_by": rf.requested_by,
                    "approved_by": rf.approved_by,
                    "provider_receipt": rf.provider_receipt or "-",
                    "created_at": rf.created_at.strftime("%Y-%m-%d %H:%M") if rf.created_at else "-",
                }
                for rf in refunds
            ],
            "rider_payouts": [
                {
                    "id": po.id,
                    "rider_id": po.rider_id,
                    "rider_name": rider_map.get(po.rider_id, f"Rider #{po.rider_id}"),
                    "amount": f"{po.amount:.2f}",
                    "phone": po.phone,
                    "reference_code": po.reference_code,
                    "status": po.status,
                    "created_at": po.created_at.strftime("%Y-%m-%d %H:%M") if po.created_at else "-",
                }
                for po in payouts
            ],
        }

    async def settle_approved_refund(self, refund_id: int, actor: User, receipt: str) -> Refund:
        """
        Records completion of an approved M-Pesa B2C refund disbursement.
        """
        refund_svc = RefundService(self.db)
        refund = await refund_svc.refunds.get_for_update(refund_id)
        if refund is None:
            raise NotFoundError("Refund not found")
        if refund.status is not RefundStatus.APPROVED:
            raise BusinessRuleError(f"Only APPROVED refunds can be settled (currently {refund.status.value})")
        clean_receipt = receipt.strip().upper()
        if len(clean_receipt) < 4:
            raise AppError("Valid M-Pesa B2C receipt code is required")

        await refund_svc.apply_result(
            refund,
            success=True,
            receipt=clean_receipt,
            code=0,
            description=f"Settled via Finance Console by Admin #{actor.id}",
        )
        self.audit.record(
            actor_id=actor.id,
            action="refund.settled",
            entity_type="refund",
            entity_id=refund.id,
            before={"status": RefundStatus.APPROVED.value},
            after={"status": RefundStatus.COMPLETED.value, "provider_receipt": clean_receipt},
        )
        await self.db.commit()
        return refund

    # -----------------------------------------------------------------------
    # Inventory, Stock Movements & Suppliers
    # -----------------------------------------------------------------------
    async def get_inventory_data(self, limit: int = 80) -> dict[str, Any]:
        mv_stmt = (
            select(StockMovement)
            .options(selectinload(StockMovement.product), selectinload(StockMovement.supplier))
            .order_by(StockMovement.id.desc())
            .limit(limit)
        )
        movements = list((await self.db.execute(mv_stmt)).scalars().all())

        sup_stmt = select(Supplier).order_by(Supplier.name)
        suppliers = list((await self.db.execute(sup_stmt)).scalars().all())

        return {
            "movements": [
                {
                    "id": m.id,
                    "product_id": m.product_id,
                    "product_name": m.product.name if m.product else f"SKU #{m.product_id}",
                    "sku": m.product.sku if m.product else "-",
                    "movement_type": m.movement_type.value,
                    "quantity_change": str(m.quantity_change),
                    "quantity_after": str(m.quantity_after),
                    "unit_cost": f"{m.unit_cost:.2f}" if m.unit_cost is not None else "-",
                    "supplier_name": m.supplier.name if m.supplier else "-",
                    "reference": f"{m.reference_type or ''} {m.reference_id or ''}".strip() or "-",
                    "note": m.note or "-",
                    "created_at": m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else "-",
                }
                for m in movements
            ],
            "suppliers": [
                {
                    "id": s.id,
                    "name": s.name,
                    "contact_name": s.contact_name or "-",
                    "phone": s.phone or "-",
                    "email": s.email or "-",
                    "kra_pin": s.kra_pin or "-",
                    "payment_terms_days": s.payment_terms_days,
                    "is_active": s.is_active,
                }
                for s in suppliers
            ],
        }

    async def create_supplier(
        self,
        *,
        name: str,
        contact_name: Optional[str],
        phone: Optional[str],
        email: Optional[str],
        kra_pin: Optional[str],
        payment_terms_days: int,
        actor_id: int,
    ) -> Supplier:
        existing = (
            await self.db.execute(select(Supplier).where(func.lower(Supplier.name) == name.strip().lower()))
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(["name"])

        sup = Supplier(
            name=name.strip(),
            contact_name=(contact_name or "").strip() or None,
            phone=(phone or "").strip() or None,
            email=(email or "").strip() or None,
            kra_pin=(kra_pin or "").strip().upper() or None,
            payment_terms_days=max(0, payment_terms_days),
            created_by=actor_id,
            updated_by=actor_id,
        )
        self.db.add(sup)
        await self.db.flush()
        self.audit.record(
            actor_id=actor_id,
            action="supplier.created",
            entity_type="supplier",
            entity_id=sup.id,
            after={"name": sup.name, "phone": sup.phone},
        )
        await self.db.commit()
        return sup

    async def toggle_supplier_active(self, supplier_id: int, actor_id: int) -> Supplier:
        sup = await self.db.get(Supplier, supplier_id)
        if sup is None:
            raise NotFoundError("Supplier not found")
        before = sup.is_active
        sup.is_active = not sup.is_active
        sup.updated_by = actor_id
        self.audit.record(
            actor_id=actor_id,
            action="supplier.status_toggle",
            entity_type="supplier",
            entity_id=sup.id,
            before={"is_active": before},
            after={"is_active": sup.is_active},
        )
        await self.db.commit()
        return sup

    # -----------------------------------------------------------------------
    # Catalogue Products & Options
    # -----------------------------------------------------------------------
    async def get_products_data(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        fetches products with inventory, category, and brand details for the admin table
        """
        stmt = (
            select(Product)
            .options(
                selectinload(Product.category),
                selectinload(Product.brand),
                selectinload(Product.inventory),
            )
            .order_by(Product.name)
            .limit(limit)
        )
        products = (await self.db.execute(stmt)).scalars().all()

        return [
            {
                "id": p.id,
                "sku": p.sku,
                "barcode": p.barcode or "-",
                "name": p.name,
                "category_id": p.category_id,
                "category_name": p.category.name if p.category else "Uncategorized",
                "brand_id": p.brand_id,
                "brand_name": p.brand.name if p.brand else "-",
                "unit": p.unit.value if hasattr(p.unit, "value") else str(p.unit),
                "pack_size_label": p.pack_size_label or "-",
                "price": str(p.price),
                "compare_at_price": str(p.compare_at_price) if p.compare_at_price else "",
                "cost_price": str(p.cost_price) if p.cost_price else "",
                "tax_class": p.tax_class.value if hasattr(p.tax_class, "value") else str(p.tax_class),
                "is_active": p.is_active,
                "is_age_restricted": p.is_age_restricted,
                "image_url": p.image_url or "",
                "gallery_images": p.gallery_images or [],
                "description": p.description or "",
                "quantity_on_hand": str(p.inventory.quantity_on_hand) if p.inventory else "0",
                "quantity_reserved": str(p.inventory.quantity_reserved) if p.inventory else "0",
                "available": str(p.inventory.available) if p.inventory else "0",
                "reorder_level": str(p.inventory.reorder_level) if p.inventory else "0",
            }
            for p in products
        ]

    async def get_catalogue_form_options(self) -> dict[str, Any]:
        """
        returns live active categories and brands for product creation/editing dropdowns
        """
        categories = await self.categories.list_all(active_only=True)
        brands = await self.brands.list_all(active_only=True)
        return {
            "categories": [{"id": c.id, "name": c.name, "slug": c.slug} for c in categories],
            "brands": [{"id": b.id, "name": b.name, "slug": b.slug} for b in brands],
        }

    # -----------------------------------------------------------------------
    # System Actors & Workforce Onboarding / Regulation
    # -----------------------------------------------------------------------
    async def get_actors_data(self, current_admin_user_id: Optional[int] = None) -> dict[str, Any]:
        """
        fetches lists of customers, staff, riders, and administrators.
        filters out the current logged-in admin so they cannot alter their own privileges.
        """
        staff_stmt = select(Staff).options(selectinload(Staff.user)).order_by(Staff.id)
        staff_members = (await self.db.execute(staff_stmt)).scalars().all()

        rider_stmt = select(Rider).options(selectinload(Rider.user)).order_by(Rider.id)
        riders = (await self.db.execute(rider_stmt)).scalars().all()

        admins = await self.admins.list_all_with_users()
        if current_admin_user_id is not None:
            admins = [a for a in admins if a.user_id != current_admin_user_id]

        cust_stmt = (
            select(Customer)
            .join(User, Customer.user_id == User.id)
            .options(selectinload(Customer.user))
            .where(User.role == UserRole.CUSTOMER)
            .order_by(Customer.id.desc())
            .limit(100)
        )
        customers = (await self.db.execute(cust_stmt)).scalars().all()

        return {
            "staff": [
                {
                    "id": s.id,
                    "user_id": s.user_id,
                    "employee_number": s.employee_number,
                    "name": f"{s.user.first_name} {s.user.last_name}" if s.user else "Unknown",
                    "email": s.user.email if s.user else "-",
                    "phone": s.user.phone if s.user else "-",
                    "position": s.position.value if hasattr(s.position, "value") else str(s.position),
                    "is_on_duty": s.is_on_duty,
                    "hired_on": s.hired_on.isoformat() if s.hired_on else "-",
                    "is_active": s.user.is_active if s.user else False,
                }
                for s in staff_members
            ],
            "riders": [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "name": f"{r.user.first_name} {r.user.last_name}" if r.user else "Unknown",
                    "phone": r.user.phone if r.user else "-",
                    "email": r.user.email if r.user else "-",
                    "national_id_number": r.national_id_number,
                    "id_card_front_url": r.id_card_front_url,
                    "id_card_back_url": r.id_card_back_url,
                    "vehicle_type": r.vehicle_type.value if hasattr(r.vehicle_type, "value") else str(r.vehicle_type),
                    "vehicle_plate": r.vehicle_plate or "-",
                    "vehicle_description": r.vehicle_description,
                    "vehicle_proof_url": r.vehicle_proof_url,
                    "licence_number": r.licence_number,
                    "licence_expiry": r.licence_expiry.isoformat() if r.licence_expiry else None,
                    "driving_licence_url": r.driving_licence_url,
                    "approval_status": r.approval_status.value if hasattr(r.approval_status, "value") else str(r.approval_status),
                    "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                    "rating_average": str(r.rating_average) if r.rating_average is not None else "New",
                    "rating_count": r.rating_count,
                    "deliveries_completed": r.deliveries_completed,
                    "penalty_points": r.penalty_points,
                }
                for r in riders
            ],
            "admins": [
                {
                    "id": a.id,
                    "user_id": a.user_id,
                    "name": f"{a.user.first_name} {a.user.last_name}" if a.user else "Unknown",
                    "username": a.user.username if a.user else "-",
                    "email": a.user.email if a.user else "-",
                    "level": a.level.value if hasattr(a.level, "value") else str(a.level),
                    "is_active": a.user.is_active if a.user else False,
                    "created_at": a.created_at.strftime("%Y-%m-%d") if a.created_at else "-",
                }
                for a in admins
            ],
            "customers": [
                {
                    "id": c.id,
                    "user_id": c.user_id,
                    "name": f"{c.user.first_name} {c.user.last_name}" if c.user else "Unknown",
                    "email": c.user.email if c.user else "-",
                    "phone": c.user.phone if c.user else "-",
                    "is_verified": c.user.is_verified if c.user else False,
                    "loyalty_points": c.loyalty_points,
                    "is_premium": c.is_premium,
                    "is_active": c.user.is_active if c.user else False,
                }
                for c in customers
                if c.user and c.user.role == UserRole.CUSTOMER and (current_admin_user_id is None or c.user_id != current_admin_user_id)
            ],
        }

    async def create_admin_account(
        self,
        *,
        first_name: str,
        last_name: str,
        username: str,
        email: str,
        phone: str,
        password: str,
        level: AdminLevel,
        actor_admin: Admin,
    ) -> Admin:
        if actor_admin.level != AdminLevel.SUPER:
            raise ForbiddenError("Only Superadministrators can provision new administrator accounts")
        if len(password) < 8:
            raise AppError("Password must be at least 8 characters long")

        taken = await self.users.conflicting_fields(
            username=username.strip().lower(),
            email=email.strip().lower(),
            phone=phone.strip(),
        )
        if taken:
            raise ConflictError(taken)

        pw_hash = await hash_password_async(password)
        user = User(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            username=username.strip().lower(),
            email=email.strip().lower(),
            phone=phone.strip(),
            password_hash=pw_hash,
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
        )
        self.db.add(user)
        await self.db.flush()

        admin = Admin(user_id=user.id, level=level)
        self.db.add(admin)
        await self.db.flush()

        self.audit.record(
            actor_id=actor_admin.user_id,
            action="admin.created",
            entity_type="admin",
            entity_id=admin.id,
            after={"username": user.username, "email": user.email, "level": level.value},
        )
        await self.db.commit()
        return admin

    async def create_staff_account(
        self,
        *,
        first_name: str,
        last_name: str,
        username: str,
        email: str,
        phone: str,
        password: str,
        employee_number: str,
        position: StaffPosition,
        actor_user_id: int,
    ) -> Staff:
        if len(password) < 8:
            raise AppError("Password must be at least 8 characters long")

        taken = await self.users.conflicting_fields(
            username=username.strip().lower(),
            email=email.strip().lower(),
            phone=phone.strip(),
        )
        if taken:
            raise ConflictError(taken)

        emp_exists = (
            await self.db.execute(
                select(Staff.id).where(Staff.employee_number == employee_number.strip().upper())
            )
        ).scalar_one_or_none()
        if emp_exists is not None:
            raise ConflictError(["employee_number"])

        pw_hash = await hash_password_async(password)
        user = User(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            username=username.strip().lower(),
            email=email.strip().lower(),
            phone=phone.strip(),
            password_hash=pw_hash,
            role=UserRole.STAFF,
            is_active=True,
            is_verified=True,
        )
        self.db.add(user)
        await self.db.flush()

        staff = Staff(
            user_id=user.id,
            employee_number=employee_number.strip().upper(),
            position=position,
            hired_on=utc_now().date(),
            is_on_duty=False,
        )
        self.db.add(staff)
        await self.db.flush()

        self.audit.record(
            actor_id=actor_user_id,
            action="staff.created",
            entity_type="staff",
            entity_id=staff.id,
            after={"employee_number": staff.employee_number, "position": position.value},
        )
        await self.db.commit()
        return staff

    async def get_rider_detail(self, rider_id: int) -> dict[str, Any]:
        stmt = select(Rider).options(selectinload(Rider.user)).where(Rider.id == rider_id)
        rider = (await self.db.execute(stmt)).scalar_one_or_none()
        if not rider:
            raise NotFoundError("Rider not found")
        return {
            "id": rider.id,
            "user_id": rider.user_id,
            "name": f"{rider.user.first_name} {rider.user.last_name}" if rider.user else "Unknown",
            "phone": rider.user.phone if rider.user else "-",
            "email": rider.user.email if rider.user else "-",
            "national_id_number": rider.national_id_number,
            "id_card_front_url": rider.id_card_front_url,
            "id_card_back_url": rider.id_card_back_url,
            "vehicle_type": rider.vehicle_type.value if hasattr(rider.vehicle_type, "value") else str(rider.vehicle_type),
            "vehicle_plate": rider.vehicle_plate,
            "vehicle_description": rider.vehicle_description,
            "vehicle_proof_url": rider.vehicle_proof_url,
            "licence_number": rider.licence_number,
            "licence_expiry": rider.licence_expiry.isoformat() if rider.licence_expiry else None,
            "driving_licence_url": rider.driving_licence_url,
            "approval_status": rider.approval_status.value if hasattr(rider.approval_status, "value") else str(rider.approval_status),
            "status": rider.status.value if hasattr(rider.status, "value") else str(rider.status),
            "rating_average": str(rider.rating_average) if rider.rating_average is not None else "New",
            "rating_count": rider.rating_count,
            "deliveries_completed": rider.deliveries_completed,
            "penalty_points": rider.penalty_points,
            "approved_at": rider.approved_at.isoformat() if rider.approved_at else None,
        }

    async def vet_rider(self, rider_id: int, new_status: ApprovalStatus, actor_id: int) -> Rider:
        rider = await self.riders.get_by_id(rider_id)
        if not rider:
            raise NotFoundError("Rider not found")

        if rider.approval_status == ApprovalStatus.NEW and new_status == ApprovalStatus.APPROVED:
            raise BusinessRuleError("Cannot approve a rider who has not submitted documents")

        old_status = rider.approval_status
        rider.approval_status = new_status
        if new_status == ApprovalStatus.APPROVED:
            rider.approved_at = datetime.now(timezone.utc)
            rider.approved_by = actor_id
        elif rider.status == RiderStatus.AVAILABLE:
            rider.status = RiderStatus.OFFLINE

        self.audit.record(
            actor_id=actor_id,
            action="rider.vetted",
            entity_type="rider",
            entity_id=rider.id,
            before={"approval_status": old_status.value if hasattr(old_status, "value") else str(old_status)},
            after={"approval_status": new_status.value if hasattr(new_status, "value") else str(new_status)},
        )
        await self.db.commit()
        return rider

    async def toggle_staff_duty(self, staff_id: int, actor_id: int) -> Staff:
        staff = await self.staff_repo.get_by_id(staff_id)
        if not staff:
            raise NotFoundError("Staff member not found")

        before_val = staff.is_on_duty
        staff.is_on_duty = not staff.is_on_duty
        self.audit.record(
            actor_id=actor_id,
            action="staff.duty_toggle",
            entity_type="staff",
            entity_id=staff.id,
            before={"is_on_duty": before_val},
            after={"is_on_duty": staff.is_on_duty},
        )
        await self.db.commit()
        return staff

    async def set_admin_level(self, target_admin_id: int, new_level: AdminLevel, actor_admin: Admin) -> Admin:
        if actor_admin.level != AdminLevel.SUPER:
            raise ForbiddenError("Only Superadministrators can modify administrator privileges")

        target = await self.admins.get_by_id(target_admin_id)
        if not target:
            raise NotFoundError("Administrator record not found")

        if target.user_id == actor_admin.user_id:
            raise ForbiddenError("Administrators cannot alter their own privilege level. Another Superadministrator must perform this action.")

        before_val = target.level
        target.level = new_level
        self.audit.record(
            actor_id=actor_admin.user_id,
            action="admin.level_change",
            entity_type="admin",
            entity_id=target.id,
            before={"level": before_val.value if hasattr(before_val, "value") else str(before_val)},
            after={"level": new_level.value if hasattr(new_level, "value") else str(new_level)},
        )
        await self.db.commit()
        return target

    async def toggle_user_active(self, user_id: int, actor_admin: Admin) -> User:
        target = await self.users.get_by_id(user_id)
        if not target:
            raise NotFoundError("User not found")

        if target.id == actor_admin.user_id:
            raise ForbiddenError("Administrators cannot deactivate their own account.")

        if target.role == UserRole.ADMIN and actor_admin.level != AdminLevel.SUPER:
            raise ForbiddenError("Only Superadministrators can alter administrator accounts")

        before_val = target.is_active
        target.is_active = not target.is_active
        self.audit.record(
            actor_id=actor_admin.user_id,
            action="user.status_toggle",
            entity_type="user",
            entity_id=target.id,
            before={"is_active": before_val},
            after={"is_active": target.is_active},
        )
        await self.db.commit()
        return target

    # -----------------------------------------------------------------------
    # Security Settings & Reviews Moderation
    # -----------------------------------------------------------------------
    def get_security_posture(self) -> dict[str, Any]:
        return {
            "app_name": self.settings.app_name,
            "app_env": self.settings.app_env,
            "debug": self.settings.debug,
            "access_tokens_expire_minutes": self.settings.access_tokens_expire_minutes,
            "require_verified_email": self.settings.require_verified_email,
            "verification_code_ttl_minutes": self.settings.verification_code_ttl_minutes,
            "verification_code_length": self.settings.verification_code_length,
            "verification_max_attempts": self.settings.verification_max_attempts,
            "verification_resend_cooldown_seconds": self.settings.verification_resend_cooldown_seconds,
            "vat_standard_rate": str(self.settings.vat_standard_rate),
            "unpaid_order_ttl_minutes": self.settings.unpaid_order_ttl_minutes,
            "rider_fee_share": str(self.settings.rider_fee_share),
            "mpesa_env": self.settings.mpesa_env,
            "mpesa_shortcode": self.settings.mpesa_shortcode or "174379",
            "mpesa_stk_window_seconds": self.settings.mpesa_stk_window_seconds,
            "log_level": self.settings.log_level,
            "admin_portal_path": getattr(self.settings, "admin_portal_path", "console-hq"),
        }

    async def get_reviews_summary(self) -> dict[str, Any]:
        stats = await self.reviews.get_summary_stats()
        reviews = await self.reviews.list_recent(limit=60)

        formatted_reviews = [
            {
                "id": r.id,
                "order_number": f"ORD-{r.order.order_number}" if r.order else f"REV-{r.id:04d}",
                "customer_name": f"{r.customer.user.first_name} {r.customer.user.last_name}" if r.customer and r.customer.user else "Verified Customer",
                "target_type": r.target_type.value.capitalize() if hasattr(r.target_type, "value") else str(r.target_type).capitalize(),
                "target_type_raw": r.target_type.value if hasattr(r.target_type, "value") else str(r.target_type),
                "product_name": r.product.name if r.product else None,
                "rider_name": f"{r.rider.user.first_name} {r.rider.user.last_name}" if r.rider and r.rider.user else None,
                "rating": r.rating,
                "comment": r.comment or "No additional remarks.",
                "date": r.created_at.strftime("%Y-%m-%d") if r.created_at else "-",
                "sentiment": r.sentiment or "positive",
                "is_published": r.is_published,
            }
            for r in reviews
        ]

        stats["reviews"] = formatted_reviews
        return stats

    async def toggle_review_publish(self, review_id: int, actor_id: int) -> Review:
        review = await self.reviews.get_by_id(review_id)
        if review is None:
            raise NotFoundError("Review not found")
        before = review.is_published
        review.is_published = not review.is_published

        if review.rider_id is not None and review.target_type in (ReviewTargetType.RIDER, ReviewTargetType.DELIVERY):
            await self.db.flush()
            avg_val, cnt = await self.reviews.get_rider_rating_stats(review.rider_id)
            rider = await self.riders.get_for_update(review.rider_id)
            if rider is not None:
                rider.rating_average = avg_val
                rider.rating_count = cnt

        self.audit.record(
            actor_id=actor_id,
            action="review.visibility_toggle",
            entity_type="review",
            entity_id=review.id,
            before={"is_published": before},
            after={"is_published": review.is_published},
        )
        await self.db.commit()
        return review

    async def get_audit_trail(self, limit: int = 50) -> list[dict[str, Any]]:
        stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        logs = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "id": l.id,
                "action": l.action,
                "entity_type": l.entity_type,
                "entity_id": l.entity_id,
                "actor_id": l.actor_user_id or "-",
                "before": l.before,
                "after": l.after,
                "ip_address": l.ip_address or "-",
                "request_id": l.request_id or "-",
                "created_at": l.created_at.strftime("%Y-%m-%d %H:%M:%S") if l.created_at else "-",
            }
            for l in logs
        ]

    # -----------------------------------------------------------------------
    # Administrator Personal Account Management
    # -----------------------------------------------------------------------
    async def update_admin_profile(
        self,
        user_id: int,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        picture: Optional[str] = None,
    ) -> User:
        user = await self.users.get_by_id(user_id)
        if not user:
            raise NotFoundError("User account not found")

        changed_fields = {}
        if email.strip().lower() != user.email.lower():
            changed_fields["email"] = email.strip()
        if phone.strip() != (user.phone or ""):
            changed_fields["phone"] = phone.strip()

        if changed_fields:
            taken = await self.users.conflicting_fields(**changed_fields, exclude_id=user.id)
            if taken:
                raise AppError(f"The following details are already taken by another account: {', '.join(taken)}")

        before = {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone": user.phone,
            "picture": user.picture,
        }

        user.first_name = first_name.strip()
        user.last_name = last_name.strip()
        user.email = email.strip()
        user.phone = phone.strip()
        if picture is not None:
            user.picture = picture.strip() or None

        after = {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone": user.phone,
            "picture": user.picture,
        }

        self.audit.record(
            actor_id=user.id,
            action="admin.profile_updated",
            entity_type="user",
            entity_id=user.id,
            before=before,
            after=after,
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def change_admin_password(
        self,
        user: User,
        current_password: str,
        new_password: str,
        new_password_confirm: str,
    ) -> None:
        if new_password != new_password_confirm:
            raise AppError("New passwords do not match")

        if len(new_password) < 8:
            raise AppError("Password must be at least 8 characters long")

        if not user.password_hash or not await verify_password_async(current_password, user.password_hash):
            raise AppError("Current password entered is incorrect")

        if await verify_password_async(new_password, user.password_hash):
            raise AppError("New password must be different from your current password")

        user.password_hash = await hash_password_async(new_password)

        self.audit.record(
            actor_id=user.id,
            action="admin.password_changed",
            entity_type="user",
            entity_id=user.id,
            before={"password_hash": "[REDACTED]"},
            after={"password_hash": "[REDACTED]"},
        )
        await self.db.commit()

    # -----------------------------------------------------------------------
    # Dispatch, Delivery Zones & SLA Queue
    # -----------------------------------------------------------------------
    async def get_dispatch_queue_data(self, limit: int = 80) -> dict[str, Any]:
        from src.security import make_pickup_code

        stmt = (
            select(Delivery)
            .options(
                selectinload(Delivery.order),
                selectinload(Delivery.rider).selectinload(Rider.user),
            )
            .where(Delivery.status != DeliveryStatus.CANCELLED)
            .order_by(Delivery.needs_manual_assignment.desc(), Delivery.is_overdue.desc(), Delivery.id.desc())
            .limit(limit)
        )
        rows = list((await self.db.execute(stmt)).scalars().all())
        secret = self.settings.secret_key.get_secret_value()

        deliveries_list = []
        for d in rows:
            order = d.order
            rider_name = (
                f"{d.rider.user.first_name} {d.rider.user.last_name}"
                if d.rider and d.rider.user else None
            )
            deliveries_list.append({
                "id": d.id,
                "order_id": d.order_id,
                "order_number": order.order_number if order else f"ORD-{d.order_id}",
                "order_status": order.status.value if order else "-",
                "status": d.status.value,
                "rider_id": d.rider_id,
                "rider_name": rider_name,
                "rider_fee": f"{d.rider_fee:.2f}",
                "address_text": order.delivery_address_text if order else "",
                "recipient_name": order.delivery_recipient_name if order else "",
                "routing_algorithm": d.routing_algorithm or "dijkstra",
                "distance_km": round((d.estimated_distance_m or 0) / 1000.0, 2),
                "needs_manual_assignment": d.needs_manual_assignment,
                "manual_assignment_reason": d.manual_assignment_reason,
                "rejection_count": d.rejection_count,
                "is_overdue": d.is_overdue,
                "pickup_code": make_pickup_code(secret, d.id, self.settings.pickup_code_length),
                "created_at": d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else "",
            })

        rider_stmt = (
            select(Rider)
            .options(selectinload(Rider.user))
            .where(
                Rider.approval_status == ApprovalStatus.APPROVED,
                Rider.status != RiderStatus.OFFLINE,
            )
            .order_by(Rider.status, Rider.penalty_points)
        )
        riders = list((await self.db.execute(rider_stmt)).scalars().all())
        eligible_riders = [
            {
                "id": r.id,
                "name": f"{r.user.first_name} {r.user.last_name}" if r.user else f"Rider #{r.id}",
                "status": r.status.value,
                "vehicle_type": r.vehicle_type.value,
                "penalty_points": r.penalty_points,
                "unjustified_rejections": r.unjustified_rejections_count,
            }
            for r in riders
        ]

        zones = (await self.db.execute(select(DeliveryZone).order_by(DeliveryZone.id))).scalars().all()
        zones_list = [
            {
                "id": z.id,
                "name": z.name,
                "delivery_fee": f"{z.delivery_fee:.2f}",
                "min_order_amount": f"{z.min_order_amount:.2f}",
                "estimated_minutes": z.estimated_minutes,
                "is_active": z.is_active,
            }
            for z in zones
        ]

        return {"deliveries": deliveries_list, "eligible_riders": eligible_riders, "zones": zones_list}

    async def create_delivery_zone(
        self,
        *,
        name: str,
        delivery_fee: Decimal,
        min_order_amount: Decimal,
        estimated_minutes: int,
        actor_id: int,
    ) -> DeliveryZone:
        zone = DeliveryZone(
            name=name.strip(),
            delivery_fee=delivery_fee,
            min_order_amount=min_order_amount,
            estimated_minutes=max(5, estimated_minutes),
            is_active=True,
        )
        self.db.add(zone)
        await self.db.flush()
        self.audit.record(
            actor_id=actor_id,
            action="delivery_zone.created",
            entity_type="delivery_zone",
            entity_id=zone.id,
            after={"name": zone.name, "delivery_fee": str(zone.delivery_fee)},
        )
        await self.db.commit()
        return zone

    async def toggle_delivery_zone(self, zone_id: int, actor_id: int) -> DeliveryZone:
        zone = await self.db.get(DeliveryZone, zone_id)
        if zone is None:
            raise NotFoundError("Delivery zone not found")
        before = zone.is_active
        zone.is_active = not zone.is_active
        self.audit.record(
            actor_id=actor_id,
            action="delivery_zone.status_toggle",
            entity_type="delivery_zone",
            entity_id=zone.id,
            before={"is_active": before},
            after={"is_active": zone.is_active},
        )
        await self.db.commit()
        return zone
