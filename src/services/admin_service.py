# src/services/admin_service.py

"""
service coordinating administrative operations, dashboard aggregations,
actor regulation (staff, riders, admins), catalogue management, and security configuration.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import Settings
from src.exceptions import ForbiddenError, NotFoundError
from src.models import (
    Admin, AdminLevel, ApprovalStatus, AuditLog, Brand, Category, Customer, Delivery,
    Inventory, Order, OrderStatus, Product, Rider, Staff, User, UserRole,
)
from src.repositories import (
    AdminRepository, BrandRepository, CategoryRepository, ProductRepository,
    ReviewRepository, RiderRepository, StaffRepository, UserRepository,
)
from src.services.audit_service import AuditService
from utilities import get_logger

log = get_logger(__name__)


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

    # dashboard metrics
    async def get_dashboard_summary(self) -> dict[str, Any]:
        """
        aggregates real-time KPIs and system actor totals
        """
        # Product counts
        total_products = (await self.db.execute(select(func.count(Product.id)))).scalar_one() or 0
        active_products = (
            await self.db.execute(select(func.count(Product.id)).where(Product.is_active.is_(True)))
        ).scalar_one() or 0

        # Low stock count
        low_stock_stmt = (
            select(func.count(Inventory.product_id))
            .where(Inventory.quantity_on_hand <= Inventory.reorder_level)
        )
        low_stock_count = (await self.db.execute(low_stock_stmt)).scalar_one() or 0

        # Actor counts
        total_customers = (
            await self.db.execute(select(func.count(User.id)).where(User.role == UserRole.CUSTOMER))
        ).scalar_one() or 0

        total_staff = (
            await self.db.execute(select(func.count(Staff.id)))
        ).scalar_one() or 0

        staff_on_duty = (
            await self.db.execute(select(func.count(Staff.id)).where(Staff.is_on_duty.is_(True)))
        ).scalar_one() or 0

        total_riders = (
            await self.db.execute(select(func.count(Rider.id)))
        ).scalar_one() or 0

        pending_riders = (
            await self.db.execute(
                select(func.count(Rider.id)).where(Rider.approval_status == ApprovalStatus.PENDING)
            )
        ).scalar_one() or 0

        # Order & revenue stats
        total_orders = (await self.db.execute(select(func.count(Order.id)))).scalar_one() or 0
        total_revenue_val = (
            await self.db.execute(
                select(func.coalesce(func.sum(Order.total), Decimal("0")))
                .where(Order.status.in_([OrderStatus.CONFIRMED, OrderStatus.COMPLETED, OrderStatus.READY]))
            )
        ).scalar_one() or Decimal("0")

        # Recent audit logs
        recent_audits_stmt = (
            select(AuditLog)
            .order_by(AuditLog.id.desc())
            .limit(10)
        )
        recent_audits = (await self.db.execute(recent_audits_stmt)).scalars().all()

        return {
            "total_products": total_products,
            "active_products": active_products,
            "low_stock_count": low_stock_count,
            "total_customers": total_customers,
            "total_staff": total_staff,
            "staff_on_duty": staff_on_duty,
            "total_riders": total_riders,
            "pending_riders": pending_riders,
            "total_orders": total_orders,
            "total_revenue": f"{total_revenue_val:.2f}",
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

    # catalog products view
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
                "quantity_on_hand": str(p.inventory.quantity_on_hand) if p.inventory else "0",
                "quantity_reserved": str(p.inventory.quantity_reserved) if p.inventory else "0",
                "available": str(p.inventory.available) if p.inventory else "0",
                "reorder_level": str(p.inventory.reorder_level) if p.inventory else "0",
            }
            for p in products
        ]

    # form options for catalogue management
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

    # system actors overview
    async def get_actors_data(self, current_admin_user_id: Optional[int] = None) -> dict[str, Any]:
        """
        fetches lists of customers, staff, riders, and administrators.
        filters out the current logged-in superadmin so they cannot alter their own privileges.
        """
        # 1. Staff
        staff_stmt = (
            select(Staff)
            .options(selectinload(Staff.user))
            .order_by(Staff.id)
        )
        staff_members = (await self.db.execute(staff_stmt)).scalars().all()

        # 2. Riders
        rider_stmt = (
            select(Rider)
            .options(selectinload(Rider.user))
            .order_by(Rider.id)
        )
        riders = (await self.db.execute(rider_stmt)).scalars().all()

        # 3. Admins
        admins = await self.admins.list_all_with_users()
        if current_admin_user_id is not None:
            admins = [a for a in admins if a.user_id != current_admin_user_id]

        # 4. Customers - strictly query only users who explicitly have role CUSTOMER
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
                    "vehicle_type": r.vehicle_type.value if hasattr(r.vehicle_type, "value") else str(r.vehicle_type),
                    "vehicle_plate": r.vehicle_plate or "-",
                    "approval_status": r.approval_status.value if hasattr(r.approval_status, "value") else str(r.approval_status),
                    "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                    "rating_average": str(r.rating_average or "5.00"),
                    "deliveries_completed": r.deliveries_completed,
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
                    "loyalty_points": c.loyalty_points,
                    "is_premium": c.is_premium,
                    "is_active": c.user.is_active if c.user else False,
                }
                for c in customers
                if c.user and c.user.role == UserRole.CUSTOMER and (current_admin_user_id is None or c.user_id != current_admin_user_id)
            ],
        }

    # rider vetting
    async def vet_rider(self, rider_id: int, new_status: ApprovalStatus, actor_id: int) -> Rider:
        """
        updates rider vetting approval status
        """
        rider = await self.riders.get_by_id(rider_id)
        if not rider:
            raise NotFoundError("Rider not found")

        old_status = rider.approval_status
        rider.approval_status = new_status
        if new_status == ApprovalStatus.APPROVED:
            rider.approved_at = datetime.now(timezone.utc)
            rider.approved_by = actor_id

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

    # staff shift toggle
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

    # superadmin admin regulation
    async def set_admin_level(self, target_admin_id: int, new_level: AdminLevel, actor_admin: Admin) -> Admin:
        """
        only a SUPER admin can regulate other admins
        """
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

    # toggle user active status
    async def toggle_user_active(self, user_id: int, actor_admin: Admin) -> User:
        target = await self.users.get_by_id(user_id)
        if not target:
            raise NotFoundError("User not found")

        if target.id == actor_admin.user_id:
            raise ForbiddenError("Administrators cannot deactivate their own account.")

        # Prevent non-superadmin from deactivating another admin
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

    # security settings overview
    def get_security_posture(self) -> dict[str, Any]:
        """
        returns live authentication and security configuration parameters
        """
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

    # reviews & ratings overview
    async def get_reviews_summary(self) -> dict[str, Any]:
        """
        retrieves feedback, ratings summary, and recent customer reviews from database
        """
        stats = await self.reviews.get_summary_stats()
        reviews = await self.reviews.list_recent(limit=50)

        formatted_reviews = [
            {
                "id": r.id,
                "order_number": f"ORD-{r.order.order_number}" if r.order else f"REV-{r.id:04d}",
                "customer_name": f"{r.customer.user.first_name} {r.customer.user.last_name}" if r.customer and r.customer.user else "Verified Customer",
                "target_type": r.target_type.value.capitalize() if hasattr(r.target_type, "value") else str(r.target_type).capitalize(),
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

    # audit log retrieval
    async def get_audit_trail(self, limit: int = 50) -> list[dict[str, Any]]:
        stmt = (
            select(AuditLog)
            .order_by(AuditLog.id.desc())
            .limit(limit)
        )
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
    # Administrator Personal Account Management (Protected Self-Settings)
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
        """
        updates administrator personal profile details.
        self-deactivation, role change, and deletion are strictly prevented.
        """
        user = await self.users.get_by_id(user_id)
        if not user:
            raise NotFoundError("User account not found")

        # Conflict check for email and phone
        changed_fields = {}
        if email.strip().lower() != user.email.lower():
            changed_fields["email"] = email.strip()
        if phone.strip() != user.phone:
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
        """
        changes administrator password after verifying current credentials
        """
        from src.security import hash_password_async, verify_password_async

        if new_password != new_password_confirm:
            raise AppError("New passwords do not match")

        if len(new_password) < 8:
            raise AppError("Password must be at least 8 characters long")

        if not await verify_password_async(current_password, user.password_hash):
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
