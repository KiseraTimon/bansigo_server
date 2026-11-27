# src/routers/server/admin.py

"""
administrative console router for Superadmin (Owner), Operations, Finance, Inventory, and Support roles.
serves server-rendered Jinja2 views and operational AJAX endpoints with strict RBAC enforcement.
all endpoints are excluded from openapi documentation schemas to prevent attacker discovery.
"""

from decimal import Decimal
import json
import re
from typing import Annotated, Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Request, Response,
    UploadFile, status,
)
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import select

from config import Settings
from src.dependencies import (
    CurrentAdmin, DbSession, SettingsDep, get_admin_service, get_auth_service,
    get_catalogue_service, get_delivery_service, get_inventory_service,
    get_order_service, get_payment_service, get_refund_service, require_admin_level,
)
from src.exceptions import AppError, ForbiddenError, InvalidCredentialsError, NotFoundError, UnauthorizedError
from src.helpers import (
    export_products_to_csv, generate_sample_csv_template, import_products_from_csv, import_products_from_excel,
)
from src.models import (
    Admin, AdminLevel, ApprovalStatus, Customer, Inventory, PickStatus,
    StaffPosition, TaxClass, UnitType, UserRole,
)
from src.repositories import AdminRepository, ProductRepository, UserRepository
from src.schemas import PickItemIn, ProductCreate, ProductUpdate
from src.services import (
    AdminService, AuthService, AuditService, CatalogueService, DeliveryService,
    InventoryService, OrderService, PaymentService, RefundService,
)
from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(include_in_schema=False)

CatalogueAdminDep = Annotated[tuple, Depends(require_admin_level(AdminLevel.SUPER, AdminLevel.OPERATIONS, AdminLevel.INVENTORY))]
OpsAdminDep = Annotated[tuple, Depends(require_admin_level(AdminLevel.SUPER, AdminLevel.OPERATIONS))]
DispatchAdminDep = Annotated[tuple, Depends(require_admin_level(AdminLevel.SUPER, AdminLevel.OPERATIONS, AdminLevel.SUPPORT))]
FinanceAdminDep = Annotated[tuple, Depends(require_admin_level(AdminLevel.SUPER, AdminLevel.FINANCE))]
SupportAdminDep = Annotated[tuple, Depends(require_admin_level(AdminLevel.SUPER, AdminLevel.OPERATIONS, AdminLevel.SUPPORT))]
SuperAdminDep = Annotated[tuple, Depends(require_admin_level(AdminLevel.SUPER))]


def _admin_base_url(settings: Settings) -> str:
    path = getattr(settings, "admin_portal_path", "console-hq").strip("/")
    return f"/{path}/admin"


def _parse_gallery_images(gallery_images: Optional[str]) -> list[str]:
    if not gallery_images:
        return []
    try:
        data = json.loads(gallery_images)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    return [img.strip() for img in gallery_images.split(",") if img.strip()]


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard_view(
    request: Request,
    settings: SettingsDep,
    db: DbSession,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
):
    """
    role-aware administrative dashboard view
    """
    base_url = _admin_base_url(settings)

    token = None
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    elif "access_token" in request.cookies:
        token = request.cookies.get("access_token")

    if not token:
        return RedirectResponse(url=f"{base_url}/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        from src.security import decode_access_token
        payload = decode_access_token(token, settings.secret_key.get_secret_value())
        user_id = int(payload["sub"])
        user = await UserRepository(db).get_by_id(user_id)
        if not user or not user.is_active or user.role != UserRole.ADMIN:
            return RedirectResponse(url=f"{base_url}/login", status_code=status.HTTP_303_SEE_OTHER)

        admin = await AdminRepository(db).get_by_user_id(user.id)
        if not admin:
            admin = Admin(user_id=user.id, level=AdminLevel.SUPER)
            db.add(admin)
            await db.commit()
            await db.refresh(admin)

    except Exception:
        return RedirectResponse(url=f"{base_url}/login", status_code=status.HTTP_303_SEE_OTHER)

    admin_level_str = admin.level.value if hasattr(admin.level, "value") else str(admin.level)
    is_superadmin = (admin.level == AdminLevel.SUPER)
    role_config = admin_service.get_role_workspace_config(admin.level)
    allowed_tabs = set(role_config["allowed_tabs"])

    summary = await admin_service.get_dashboard_summary(admin_level=admin.level)
    security = admin_service.get_security_posture()
    reviews = await admin_service.get_reviews_summary()

    products_list = await admin_service.get_products_data(limit=150) if ({"products", "inventory"} & allowed_tabs) else []
    catalogue_options = await admin_service.get_catalogue_form_options() if ({"products", "inventory"} & allowed_tabs) else {"categories": [], "brands": []}
    actors = await admin_service.get_actors_data(current_admin_user_id=user.id) if "actors" in allowed_tabs else {"staff": [], "riders": [], "admins": [], "customers": []}
    dispatch_data = await admin_service.get_dispatch_queue_data() if "dispatch" in allowed_tabs else {"deliveries": [], "eligible_riders": [], "zones": []}
    orders_data = await admin_service.get_orders_data(limit=80) if "orders" in allowed_tabs else {"orders": []}
    finance_data = await admin_service.get_finance_data(limit=60) if "finance" in allowed_tabs else {"payments": [], "payment_events": [], "refunds": [], "rider_payouts": []}
    inventory_data = await admin_service.get_inventory_data(limit=80) if "inventory" in allowed_tabs else {"movements": [], "suppliers": []}
    audits = await admin_service.get_audit_trail(limit=50) if "audit" in allowed_tabs else []

    return request.app.state.templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "admin_user": user,
            "admin_profile": admin,
            "admin_level": admin_level_str,
            "is_superadmin": is_superadmin,
            "role_config": role_config,
            "allowed_tabs": allowed_tabs,
            "base_url": base_url,
            "summary": summary,
            "orders_data": orders_data,
            "finance_data": finance_data,
            "inventory_data": inventory_data,
            "dispatch_data": dispatch_data,
            "products": products_list,
            "categories": catalogue_options.get("categories", []),
            "brands": catalogue_options.get("brands", []),
            "actors": actors,
            "security": security,
            "reviews": reviews,
            "audits": audits,
            "staff_positions": [p.value for p in StaffPosition],
            "admin_levels": [lvl.value for lvl in AdminLevel],
            "current_admin_user_id": user.id,
        },
    )


@router.get("/login", response_class=HTMLResponse)
async def admin_login_view(request: Request, settings: SettingsDep):
    base_url = _admin_base_url(settings)
    return request.app.state.templates.TemplateResponse(
        request,
        "admin/login.html",
        {"base_url": base_url, "app_name": settings.app_name},
    )


@router.post("/login")
async def admin_login_action(
    request: Request,
    settings: SettingsDep,
    db: DbSession,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    username: str = Form(...),
    password: str = Form(...),
):
    base_url = _admin_base_url(settings)
    try:
        user = await auth_service.authenticate(username, password)
        if user.role != UserRole.ADMIN:
            raise ForbiddenError("Access denied: Administrative privileges required")

        admin = await AdminRepository(db).get_by_user_id(user.id)
        if not admin:
            admin = Admin(user_id=user.id, level=AdminLevel.SUPER)
            db.add(admin)
            await db.commit()

        token = auth_service.issue_token(user)

        is_ajax = "application/json" in request.headers.get("accept", "")
        if is_ajax:
            response = Response(
                content=f'{{"access_token":"{token}","token_type":"bearer","redirect_url":"{base_url}"}}',
                media_type="application/json",
            )
        else:
            response = RedirectResponse(url=base_url, status_code=status.HTTP_303_SEE_OTHER)

        response.set_cookie(
            key="access_token",
            value=token,
            max_age=settings.access_tokens_expire_minutes * 60,
            httponly=True,
            samesite="lax",
            secure=settings.is_production,
        )
        return response

    except (UnauthorizedError, ForbiddenError, InvalidCredentialsError, AppError) as err:
        log.warning("Admin login failed for user %s: %s", username, err)
        return request.app.state.templates.TemplateResponse(
            request,
            "admin/login.html",
            {
                "base_url": base_url,
                "app_name": settings.app_name,
                "error": "Invalid administrative username or password",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


@router.get("/logout")
@router.post("/logout")
async def admin_logout_action(settings: SettingsDep):
    base_url = _admin_base_url(settings)
    response = RedirectResponse(url=f"{base_url}/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response


# ---------------------------------------------------------------------------
# PRODUCTS & CATALOGUE MANAGEMENT
# ---------------------------------------------------------------------------
@router.post("/products")
async def add_product(
    admin_ctx: CatalogueAdminDep,
    catalogue_service: Annotated[CatalogueService, Depends(get_catalogue_service)],
    db: DbSession,
    category_id: int = Form(...),
    brand_id: Optional[int] = Form(None),
    sku: str = Form(...),
    barcode: Optional[str] = Form(None),
    name: str = Form(...),
    description: Optional[str] = Form(None),
    image_url: Optional[str] = Form(None),
    gallery_images: Optional[str] = Form(None),
    unit: str = Form("piece"),
    pack_size_label: Optional[str] = Form(None),
    price: Decimal = Form(...),
    compare_at_price: Optional[Decimal] = Form(None),
    cost_price: Optional[Decimal] = Form(None),
    tax_class: str = Form("standard"),
    is_age_restricted: bool = Form(False),
    initial_stock: Decimal = Form(Decimal("0")),
    reorder_level: Decimal = Form(Decimal("0")),
):
    user, _ = admin_ctx
    unit_enum = UnitType(unit) if unit in [u.value for u in UnitType] else UnitType.PIECE
    tax_enum = TaxClass(tax_class) if tax_class in [t.value for t in TaxClass] else TaxClass.STANDARD
    parsed_gallery = _parse_gallery_images(gallery_images)
    primary_image = image_url.strip() if image_url else (parsed_gallery[0] if parsed_gallery else None)

    prod_in = ProductCreate(
        category_id=category_id,
        brand_id=brand_id,
        sku=sku.strip().upper(),
        barcode=barcode.strip() if barcode else None,
        name=name.strip(),
        description=description.strip() if description else None,
        image_url=primary_image,
        gallery_images=parsed_gallery or None,
        unit=unit_enum,
        pack_size_label=pack_size_label.strip() if pack_size_label else None,
        price=price,
        compare_at_price=compare_at_price,
        cost_price=cost_price,
        tax_class=tax_enum,
        is_age_restricted=is_age_restricted,
    )

    created_prod = await catalogue_service.create_product(prod_in, actor_id=user.id)

    if initial_stock > 0 or reorder_level > 0:
        inv = (
            await db.execute(select(Inventory).where(Inventory.product_id == created_prod.id))
        ).scalar_one_or_none()
        if inv:
            inv.quantity_on_hand = initial_stock
            inv.reorder_level = reorder_level
            await db.commit()

    return {"detail": "Product created successfully", "product_id": created_prod.id}


@router.patch("/products/{product_id}")
async def update_product(
    product_id: int,
    admin_ctx: CatalogueAdminDep,
    catalogue_service: Annotated[CatalogueService, Depends(get_catalogue_service)],
    db: DbSession,
    name: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    brand_id: Optional[int] = Form(None),
    sku: Optional[str] = Form(None),
    barcode: Optional[str] = Form(None),
    unit: Optional[str] = Form(None),
    pack_size_label: Optional[str] = Form(None),
    price: Optional[Decimal] = Form(None),
    compare_at_price: Optional[Decimal] = Form(None),
    cost_price: Optional[Decimal] = Form(None),
    tax_class: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    is_age_restricted: Optional[bool] = Form(None),
    image_url: Optional[str] = Form(None),
    gallery_images: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    quantity_on_hand: Optional[Decimal] = Form(None),
    reorder_level: Optional[Decimal] = Form(None),
):
    user, _ = admin_ctx
    update_data: dict = {}

    if gallery_images is not None:
        parsed_gallery = _parse_gallery_images(gallery_images)
        update_data["gallery_images"] = parsed_gallery
        if parsed_gallery and not image_url:
            update_data["image_url"] = parsed_gallery[0]

    if name is not None:
        update_data["name"] = name.strip()
    if category_id is not None:
        update_data["category_id"] = category_id
    if brand_id is not None:
        update_data["brand_id"] = brand_id
    if sku is not None:
        update_data["sku"] = sku.strip().upper()
    if barcode is not None:
        update_data["barcode"] = barcode.strip() or None
    if unit is not None:
        update_data["unit"] = UnitType(unit)
    if pack_size_label is not None:
        update_data["pack_size_label"] = pack_size_label.strip() or None
    if price is not None:
        update_data["price"] = price
    if compare_at_price is not None:
        update_data["compare_at_price"] = compare_at_price
    if cost_price is not None:
        update_data["cost_price"] = cost_price
    if tax_class is not None:
        update_data["tax_class"] = TaxClass(tax_class)
    if is_active is not None:
        update_data["is_active"] = is_active
    if is_age_restricted is not None:
        update_data["is_age_restricted"] = is_age_restricted
    if image_url is not None:
        update_data["image_url"] = image_url.strip() or None
    if description is not None:
        update_data["description"] = description.strip() or None

    if update_data:
        patch_in = ProductUpdate(**update_data)
        await catalogue_service.update_product(product_id, patch_in, actor_id=user.id)

    if quantity_on_hand is not None or reorder_level is not None:
        inv = (
            await db.execute(select(Inventory).where(Inventory.product_id == product_id))
        ).scalar_one_or_none()
        if inv:
            if quantity_on_hand is not None:
                inv.quantity_on_hand = quantity_on_hand
            if reorder_level is not None:
                inv.reorder_level = reorder_level
            await db.commit()

    return {"detail": "Product updated successfully"}


@router.post("/products/{product_id}/toggle-status")
async def toggle_product_status(
    product_id: int,
    admin_ctx: CatalogueAdminDep,
    catalogue_service: Annotated[CatalogueService, Depends(get_catalogue_service)],
    db: DbSession,
):
    user, _ = admin_ctx
    product = await ProductRepository(db).get_by_id(product_id)
    if not product:
        raise NotFoundError("Product not found")

    new_status = not product.is_active
    patch_in = ProductUpdate(is_active=new_status)
    await catalogue_service.update_product(product_id, patch_in, actor_id=user.id)
    return {"detail": f"Product is now {'active' if new_status else 'deactivated'}", "is_active": new_status}


@router.delete("/products/{product_id}")
@router.post("/products/{product_id}/delete")
async def delete_product(
    product_id: int,
    admin_ctx: CatalogueAdminDep,
    catalogue_service: Annotated[CatalogueService, Depends(get_catalogue_service)],
):
    user, _ = admin_ctx
    return await catalogue_service.delete_product(product_id, actor_id=user.id)


@router.get("/products/export")
async def export_products_csv(_: CurrentAdmin, db: DbSession):
    csv_content = await export_products_to_csv(db)
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bansigo_catalogue_products.csv"},
    )


@router.get("/products/template")
async def download_csv_template(_: CurrentAdmin):
    template_content = generate_sample_csv_template()
    return PlainTextResponse(
        content=template_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bansigo_products_template.csv"},
    )


@router.post("/products/bulk-upload")
async def bulk_upload_products_csv(
    admin_ctx: CatalogueAdminDep,
    db: DbSession,
    file: UploadFile = File(...),
):
    user, _ = admin_ctx
    content_bytes = await file.read()
    filename = (file.filename or "").lower()
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        report = await import_products_from_excel(content_bytes, actor_id=user.id, db=db)
    else:
        try:
            csv_text = content_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            csv_text = content_bytes.decode("latin-1")
        report = await import_products_from_csv(csv_text, actor_id=user.id, db=db)
    return report


# ---------------------------------------------------------------------------
# INVENTORY, STOCK MOVEMENTS & SUPPLIERS
# ---------------------------------------------------------------------------
@router.post("/inventory/{product_id}/receive")
async def admin_receive_stock(
    product_id: int,
    admin_ctx: CatalogueAdminDep,
    inventory_service: Annotated[InventoryService, Depends(get_inventory_service)],
    quantity: Decimal = Form(...),
    supplier_id: Optional[int] = Form(None),
    unit_cost: Optional[Decimal] = Form(None),
    note: Optional[str] = Form(None),
):
    user, _ = admin_ctx
    inv = await inventory_service.receive(
        product_id, quantity, actor_id=user.id, supplier_id=supplier_id, unit_cost=unit_cost, note=note
    )
    return {"detail": f"Received {quantity} units into stock (On Hand: {inv.quantity_on_hand})"}


@router.post("/inventory/{product_id}/stock-take")
async def admin_stock_take(
    product_id: int,
    admin_ctx: CatalogueAdminDep,
    inventory_service: Annotated[InventoryService, Depends(get_inventory_service)],
    counted: Decimal = Form(...),
    note: Optional[str] = Form(None),
):
    user, _ = admin_ctx
    inv = await inventory_service.stock_take(product_id, counted, actor_id=user.id, note=note)
    return {"detail": f"Stock count reconciled to {inv.quantity_on_hand}"}


@router.post("/inventory/{product_id}/write-off")
async def admin_write_off_stock(
    product_id: int,
    admin_ctx: CatalogueAdminDep,
    inventory_service: Annotated[InventoryService, Depends(get_inventory_service)],
    quantity: Decimal = Form(...),
    note: str = Form(...),
):
    user, _ = admin_ctx
    inv = await inventory_service.write_off(product_id, quantity, actor_id=user.id, note=note)
    return {"detail": f"Wrote off {quantity} units (Remaining: {inv.quantity_on_hand})"}


@router.post("/inventory/{product_id}/reorder")
async def admin_set_reorder_level(
    product_id: int,
    admin_ctx: CatalogueAdminDep,
    inventory_service: Annotated[InventoryService, Depends(get_inventory_service)],
    reorder_level: Decimal = Form(...),
    reorder_quantity: Optional[Decimal] = Form(None),
):
    inv = await inventory_service.set_reorder(product_id, reorder_level, reorder_quantity)
    return {"detail": f"Reorder threshold updated to {inv.reorder_level}"}


@router.post("/suppliers")
async def admin_create_supplier(
    admin_ctx: CatalogueAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
    name: str = Form(...),
    contact_name: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    kra_pin: Optional[str] = Form(None),
    payment_terms_days: int = Form(0),
):
    user, _ = admin_ctx
    sup = await admin_service.create_supplier(
        name=name,
        contact_name=contact_name,
        phone=phone,
        email=email,
        kra_pin=kra_pin,
        payment_terms_days=payment_terms_days,
        actor_id=user.id,
    )
    return {"detail": f"Supplier '{sup.name}' added", "supplier_id": sup.id}


@router.post("/suppliers/{supplier_id}/toggle-status")
async def admin_toggle_supplier(
    supplier_id: int,
    admin_ctx: CatalogueAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
):
    user, _ = admin_ctx
    sup = await admin_service.toggle_supplier_active(supplier_id, actor_id=user.id)
    return {"detail": f"Supplier '{sup.name}' is now {'active' if sup.is_active else 'inactive'}"}


# ---------------------------------------------------------------------------
# ORDERS & FULFILMENT WORKFLOW
# ---------------------------------------------------------------------------
@router.get("/orders/{order_id}")
async def admin_get_order_detail(
    order_id: int,
    _: CurrentAdmin,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
):
    return await admin_service.get_order_detail(order_id)


@router.post("/orders/{order_id}/start-picking")
async def admin_start_order_picking(
    order_id: int,
    admin_ctx: OpsAdminDep,
    order_service: Annotated[OrderService, Depends(get_order_service)],
):
    user, _ = admin_ctx
    order = await order_service.start_picking(order_id, actor=user)
    return {"detail": f"Order #{order.order_number} moved to PREPARING", "status": order.status.value}


@router.post("/orders/{order_id}/items/{item_id}/pick")
async def admin_pick_order_item(
    order_id: int,
    item_id: int,
    admin_ctx: OpsAdminDep,
    order_service: Annotated[OrderService, Depends(get_order_service)],
    pick_status: str = Form(...),
    quantity_picked: Decimal = Form(...),
    substitute_product_id: Optional[int] = Form(None),
):
    user, _ = admin_ctx
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
        actor=user,
    )
    return {"detail": f"Line item updated on Order #{order.order_number}"}


@router.post("/orders/{order_id}/finish-picking")
async def admin_finish_order_picking(
    order_id: int,
    admin_ctx: OpsAdminDep,
    order_service: Annotated[OrderService, Depends(get_order_service)],
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
):
    user, _ = admin_ctx
    order = await order_service.finish_picking(order_id, actor=user)
    if order.delivery is not None and order.delivery.rider_id is None:
        await delivery_service.try_auto_dispatch(order.delivery.id, dispatcher=user)
    return {"detail": f"Order #{order.order_number} packed & READY", "status": order.status.value}


@router.post("/orders/{order_id}/complete-pickup")
async def admin_complete_pickup_order(
    order_id: int,
    admin_ctx: OpsAdminDep,
    order_service: Annotated[OrderService, Depends(get_order_service)],
):
    user, _ = admin_ctx
    order = await order_service.mark_completed_pickup(order_id, actor=user)
    return {"detail": f"Click & Collect Order #{order.order_number} completed", "status": order.status.value}


@router.post("/orders/{order_id}/cancel")
async def admin_cancel_order(
    order_id: int,
    admin_ctx: SupportAdminDep,
    order_service: Annotated[OrderService, Depends(get_order_service)],
    reason: str = Form(...),
):
    user, _ = admin_ctx
    order = await order_service.cancel_by_staff(order_id, actor=user, reason=reason.strip())
    return {"detail": f"Order #{order.order_number} cancelled and reserved stock released", "status": order.status.value}


# ---------------------------------------------------------------------------
# FINANCE, PAYMENTS & REFUNDS (MAKER-CHECKER)
# ---------------------------------------------------------------------------
@router.post("/finance/orders/{order_id}/confirm-manual")
async def admin_confirm_manual_payment(
    order_id: int,
    admin_ctx: FinanceAdminDep,
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
    order_service: Annotated[OrderService, Depends(get_order_service)],
    db: DbSession,
    transaction_code: str = Form(...),
):
    user, _ = admin_ctx
    order = await order_service.get_for_staff(order_id)
    customer = await db.get(Customer, order.customer_id)
    if customer is None:
        raise NotFoundError("Order customer not found")
    await payment_service.confirm_manual_mpesa(
        customer=customer,
        user=user,
        order_id=order_id,
        transaction_code=transaction_code.strip().upper(),
    )
    return {"detail": f"Order #{order.order_number} reconciled with M-Pesa receipt {transaction_code.strip().upper()}"}


@router.post("/finance/refunds")
async def admin_request_refund(
    admin_ctx: FinanceAdminDep,
    refund_service: Annotated[RefundService, Depends(get_refund_service)],
    payment_id: int = Form(...),
    reason: str = Form(...),
    amount: Optional[Decimal] = Form(None),
):
    user, _ = admin_ctx
    refund = await refund_service.request_manual(payment_id, amount, reason.strip(), actor=user)
    return {"detail": f"Refund #{refund.id} staged for maker-checker approval", "refund_id": refund.id}


@router.post("/finance/refunds/{refund_id}/approve")
async def admin_approve_refund(
    refund_id: int,
    admin_ctx: FinanceAdminDep,
    refund_service: Annotated[RefundService, Depends(get_refund_service)],
):
    user, _ = admin_ctx
    refund = await refund_service.approve(refund_id, approver=user)
    return {"detail": f"Refund #{refund.id} approved for disbursement"}


@router.post("/finance/refunds/{refund_id}/reject")
async def admin_reject_refund(
    refund_id: int,
    admin_ctx: FinanceAdminDep,
    refund_service: Annotated[RefundService, Depends(get_refund_service)],
    reason: str = Form(...),
):
    user, _ = admin_ctx
    refund = await refund_service.reject(refund_id, approver=user, reason=reason.strip())
    return {"detail": f"Refund #{refund.id} rejected"}


@router.post("/finance/refunds/{refund_id}/settle")
async def admin_settle_refund(
    refund_id: int,
    admin_ctx: FinanceAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
    receipt: str = Form(...),
):
    user, _ = admin_ctx
    refund = await admin_service.settle_approved_refund(refund_id, actor=user, receipt=receipt)
    return {"detail": f"Refund #{refund.id} settled with receipt {refund.provider_receipt}"}


# ---------------------------------------------------------------------------
# SYSTEM ACTORS REGULATION & ONBOARDING (Staff, Riders, Admins, Customers)
# ---------------------------------------------------------------------------
@router.get("/actors/riders/{rider_id}")
async def get_rider_submission_detail(
    rider_id: int,
    admin_ctx: CurrentAdmin,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
):
    return await admin_service.get_rider_detail(rider_id)


@router.post("/actors/riders/{rider_id}/vet")
async def vet_rider(
    rider_id: int,
    admin_ctx: OpsAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
    action: str = Form(...),
):
    user, _ = admin_ctx
    status_map = {
        "approve": ApprovalStatus.APPROVED,
        "reject": ApprovalStatus.REJECTED,
        "suspend": ApprovalStatus.SUSPENDED,
        "pending": ApprovalStatus.PENDING,
    }
    new_status = status_map.get(action.lower())
    if not new_status:
        raise HTTPException(status_code=400, detail="Invalid vetting action")

    rider = await admin_service.vet_rider(rider_id, new_status, actor_id=user.id)
    return {"detail": f"Rider vetting updated to {new_status.value}", "rider_id": rider.id}


@router.post("/actors/staff")
async def create_staff_member(
    admin_ctx: OpsAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
    first_name: str = Form(...),
    last_name: str = Form(...),
    username: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    password: str = Form(...),
    employee_number: str = Form(...),
    position: str = Form(...),
):
    user, _ = admin_ctx
    try:
        pos_enum = StaffPosition(position.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid staff position")
    staff = await admin_service.create_staff_account(
        first_name=first_name,
        last_name=last_name,
        username=username,
        email=email,
        phone=phone,
        password=password,
        employee_number=employee_number,
        position=pos_enum,
        actor_user_id=user.id,
    )
    return {"detail": f"Staff member {staff.employee_number} created", "staff_id": staff.id}


@router.post("/actors/staff/{staff_id}/toggle-duty")
async def toggle_staff_duty(
    staff_id: int,
    admin_ctx: OpsAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
):
    user, _ = admin_ctx
    staff = await admin_service.toggle_staff_duty(staff_id, actor_id=user.id)
    return {"detail": f"Staff member on-duty status: {staff.is_on_duty}", "is_on_duty": staff.is_on_duty}


@router.post("/actors/admins")
async def create_admin_account(
    admin_ctx: SuperAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
    first_name: str = Form(...),
    last_name: str = Form(...),
    username: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    password: str = Form(...),
    level: str = Form(...),
):
    _, actor_admin = admin_ctx
    try:
        level_enum = AdminLevel(level.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid admin level")

    admin = await admin_service.create_admin_account(
        first_name=first_name,
        last_name=last_name,
        username=username,
        email=email,
        phone=phone,
        password=password,
        level=level_enum,
        actor_admin=actor_admin,
    )
    return {"detail": f"Administrator created with {admin.level.value.upper()} privileges", "admin_id": admin.id}


@router.patch("/actors/admins/{target_admin_id}/level")
async def update_admin_level(
    target_admin_id: int,
    admin_ctx: SuperAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
    new_level: str = Form(...),
):
    _, actor_admin = admin_ctx
    try:
        level_enum = AdminLevel(new_level.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid admin level")

    admin = await admin_service.set_admin_level(target_admin_id, level_enum, actor_admin=actor_admin)
    return {"detail": f"Admin level updated to {admin.level.value}", "admin_id": admin.id}


@router.post("/actors/users/{user_id}/toggle-status")
async def toggle_user_active(
    user_id: int,
    admin_ctx: SupportAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
):
    _, actor_admin = admin_ctx
    user = await admin_service.toggle_user_active(user_id, actor_admin=actor_admin)
    return {"detail": f"User account active status: {user.is_active}", "is_active": user.is_active}


# ---------------------------------------------------------------------------
# REVIEWS MODERATION
# ---------------------------------------------------------------------------
@router.post("/reviews/{review_id}/toggle-publish")
async def toggle_review_visibility(
    review_id: int,
    admin_ctx: SupportAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
):
    user, _ = admin_ctx
    review = await admin_service.toggle_review_publish(review_id, actor_id=user.id)
    return {
        "detail": f"Review #{review.id} is now {'published' if review.is_published else 'hidden'}",
        "is_published": review.is_published,
    }


# ---------------------------------------------------------------------------
# SECURITY & AUTHENTICATION CONFIGURATION & 2FA
# ---------------------------------------------------------------------------
@router.post("/security/2fa/request")
async def request_two_factor(
    admin_ctx: CurrentAdmin,
    settings: SettingsDep,
    db: DbSession,
):
    user, _ = admin_ctx
    from src.services.verification_service import VerificationService
    from utilities.mail import Mailer

    verif_svc = VerificationService(db, settings)
    mailer = Mailer(settings)

    mail = await verif_svc.start_two_factor_setup(user)
    sent = await mailer.send(mail)

    audit = AuditService(db)
    audit.record(
        actor_id=user.id,
        action="security.2fa_requested",
        entity_type="user",
        entity_id=user.id,
        before={"two_factor_enabled": user.two_factor_enabled},
        after={"email_dispatched": sent, "recipient": user.email},
    )
    await db.commit()

    match = re.search(r"\b(\d{4,8})\b", mail.body)
    issued_code = match.group(1) if match else None

    resp_data = {
        "detail": f"Two-factor authentication code sent to {user.email}",
        "email": user.email,
        "sent": sent,
    }
    if settings.app_env != "production" or settings.debug:
        resp_data["dev_code"] = issued_code
    return resp_data


@router.post("/security/2fa/confirm")
async def confirm_two_factor(
    admin_ctx: CurrentAdmin,
    settings: SettingsDep,
    db: DbSession,
    code: str = Form(...),
):
    user, _ = admin_ctx
    from src.services.verification_service import VerificationService

    verif_svc = VerificationService(db, settings)
    await verif_svc.confirm_two_factor(user, code.strip())

    audit = AuditService(db)
    audit.record(
        actor_id=user.id,
        action="security.2fa_enabled",
        entity_type="user",
        entity_id=user.id,
        before={"two_factor_enabled": False},
        after={"two_factor_enabled": True},
    )
    await db.commit()
    return {"detail": "Two-factor authentication successfully enabled", "two_factor_enabled": True}


@router.post("/security/2fa/disable")
async def disable_two_factor(
    admin_ctx: CurrentAdmin,
    settings: SettingsDep,
    db: DbSession,
):
    user, _ = admin_ctx
    from src.services.verification_service import VerificationService

    verif_svc = VerificationService(db, settings)
    await verif_svc.disable_two_factor(user)

    audit = AuditService(db)
    audit.record(
        actor_id=user.id,
        action="security.2fa_disabled",
        entity_type="user",
        entity_id=user.id,
        before={"two_factor_enabled": True},
        after={"two_factor_enabled": False},
    )
    await db.commit()
    return {"detail": "Two-factor authentication has been disabled", "two_factor_enabled": False}


@router.post("/security/settings")
async def update_security_settings(
    admin_ctx: SuperAdminDep,
    settings: SettingsDep,
    db: DbSession,
    access_tokens_expire_minutes: Optional[int] = Form(None),
    require_verified_email: Optional[bool] = Form(None),
    verification_code_ttl_minutes: Optional[int] = Form(None),
    verification_max_attempts: Optional[int] = Form(None),
    unpaid_order_ttl_minutes: Optional[int] = Form(None),
    vat_standard_rate: Optional[Decimal] = Form(None),
    rider_fee_share: Optional[Decimal] = Form(None),
    mpesa_env: Optional[str] = Form(None),
    mpesa_shortcode: Optional[str] = Form(None),
    mpesa_stk_window_seconds: Optional[int] = Form(None),
    log_level: Optional[str] = Form(None),
):
    user, _ = admin_ctx

    before = {
        "access_tokens_expire_minutes": settings.access_tokens_expire_minutes,
        "require_verified_email": settings.require_verified_email,
        "verification_code_ttl_minutes": settings.verification_code_ttl_minutes,
        "verification_max_attempts": settings.verification_max_attempts,
        "unpaid_order_ttl_minutes": settings.unpaid_order_ttl_minutes,
        "vat_standard_rate": str(settings.vat_standard_rate),
        "rider_fee_share": str(settings.rider_fee_share),
        "mpesa_env": settings.mpesa_env,
        "mpesa_shortcode": settings.mpesa_shortcode,
        "mpesa_stk_window_seconds": settings.mpesa_stk_window_seconds,
        "log_level": settings.log_level,
    }

    if access_tokens_expire_minutes is not None and access_tokens_expire_minutes > 0:
        settings.access_tokens_expire_minutes = access_tokens_expire_minutes
    if require_verified_email is not None:
        settings.require_verified_email = require_verified_email
    if verification_code_ttl_minutes is not None and verification_code_ttl_minutes > 0:
        settings.verification_code_ttl_minutes = verification_code_ttl_minutes
    if verification_max_attempts is not None and verification_max_attempts > 0:
        settings.verification_max_attempts = verification_max_attempts
    if unpaid_order_ttl_minutes is not None and unpaid_order_ttl_minutes > 0:
        settings.unpaid_order_ttl_minutes = unpaid_order_ttl_minutes
    if vat_standard_rate is not None and vat_standard_rate >= 0:
        settings.vat_standard_rate = vat_standard_rate
    if rider_fee_share is not None and Decimal("0") <= rider_fee_share <= Decimal("1"):
        settings.rider_fee_share = rider_fee_share
    if mpesa_env in ["sandbox", "production"]:
        settings.mpesa_env = mpesa_env
    if mpesa_shortcode is not None:
        settings.mpesa_shortcode = mpesa_shortcode.strip()
    if mpesa_stk_window_seconds is not None and mpesa_stk_window_seconds > 0:
        settings.mpesa_stk_window_seconds = mpesa_stk_window_seconds
    if log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        settings.log_level = log_level

    after = {
        "access_tokens_expire_minutes": settings.access_tokens_expire_minutes,
        "require_verified_email": settings.require_verified_email,
        "verification_code_ttl_minutes": settings.verification_code_ttl_minutes,
        "verification_max_attempts": settings.verification_max_attempts,
        "unpaid_order_ttl_minutes": settings.unpaid_order_ttl_minutes,
        "vat_standard_rate": str(settings.vat_standard_rate),
        "rider_fee_share": str(settings.rider_fee_share),
        "mpesa_env": settings.mpesa_env,
        "mpesa_shortcode": settings.mpesa_shortcode,
        "mpesa_stk_window_seconds": settings.mpesa_stk_window_seconds,
        "log_level": settings.log_level,
    }

    audit = AuditService(db)
    audit.record(
        actor_id=user.id,
        action="security.settings_updated",
        entity_type="system_settings",
        entity_id="global",
        before=before,
        after=after,
    )
    await db.commit()
    log.info("Security settings updated by superadmin user %s", user.id)
    return {"detail": "Security and app configurations updated successfully", "current": after}


# ---------------------------------------------------------------------------
# ADMINISTRATOR PERSONAL ACCOUNT SETTINGS
# ---------------------------------------------------------------------------
@router.post("/account/profile")
async def update_admin_personal_profile(
    admin_ctx: CurrentAdmin,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    picture: Optional[str] = Form(None),
):
    user, _ = admin_ctx
    updated_user = await admin_service.update_admin_profile(
        user_id=user.id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        picture=picture,
    )
    return {
        "detail": "Profile details updated successfully",
        "first_name": updated_user.first_name,
        "last_name": updated_user.last_name,
        "email": updated_user.email,
        "phone": updated_user.phone,
    }


@router.post("/account/password")
async def change_admin_personal_password(
    admin_ctx: CurrentAdmin,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
):
    user, _ = admin_ctx
    await admin_service.change_admin_password(
        user=user,
        current_password=current_password,
        new_password=new_password,
        new_password_confirm=new_password_confirm,
    )
    return {"detail": "Password updated successfully"}


# ---------------------------------------------------------------------------
# STORE OPERATOR DISPATCH, DELIVERY ZONES & MANUAL RIDER ASSIGNMENT
# ---------------------------------------------------------------------------
@router.post("/deliveries/{delivery_id}/auto-dispatch")
async def admin_auto_dispatch_delivery(
    delivery_id: int,
    admin_ctx: DispatchAdminDep,
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
):
    user, _ = admin_ctx
    result = await delivery_service.try_auto_dispatch(delivery_id, dispatcher=user)
    if result is None:
        return {"detail": "No eligible rider available; flagged for manual assignment", "assigned": False}
    delivery, rider = result
    return {
        "detail": f"Delivery #{delivery.id} auto-assigned to Rider #{rider.id}",
        "assigned": True,
        "rider_id": rider.id,
    }


@router.post("/deliveries/{delivery_id}/assign")
async def admin_manual_assign_delivery(
    delivery_id: int,
    admin_ctx: DispatchAdminDep,
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
    rider_id: int = Form(...),
):
    user, _ = admin_ctx
    delivery = await delivery_service.assign(delivery_id, rider_id, user)
    return {
        "detail": f"Delivery #{delivery.id} manually assigned to Rider #{rider_id}",
        "rider_id": delivery.rider_id,
    }


@router.post("/deliveries/sweep")
async def admin_sweep_delivery_timers(
    admin_ctx: DispatchAdminDep,
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
):
    stats = await delivery_service.sweep_delivery_timers()
    return {"detail": "Delivery SLA & offer timer sweep completed", "stats": stats}


@router.post("/deliveries/{delivery_id}/verify-pickup")
async def admin_verify_store_pickup(
    delivery_id: int,
    admin_ctx: OpsAdminDep,
    delivery_service: Annotated[DeliveryService, Depends(get_delivery_service)],
    pickup_code: str = Form(...),
):
    user, _ = admin_ctx
    delivery = await delivery_service.verify_store_pickup(delivery_id, pickup_code, user)
    return {
        "detail": f"Pickup code verified for Delivery #{delivery.id}. Order handed over to rider.",
        "status": delivery.status.value,
    }


@router.post("/dispatch/zones")
async def admin_create_delivery_zone(
    admin_ctx: OpsAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
    name: str = Form(...),
    delivery_fee: Decimal = Form(...),
    min_order_amount: Decimal = Form(Decimal("0.00")),
    estimated_minutes: int = Form(25),
):
    user, _ = admin_ctx
    zone = await admin_service.create_delivery_zone(
        name=name,
        delivery_fee=delivery_fee,
        min_order_amount=min_order_amount,
        estimated_minutes=estimated_minutes,
        actor_id=user.id,
    )
    return {"detail": f"Delivery zone '{zone.name}' created", "zone_id": zone.id}


@router.post("/dispatch/zones/{zone_id}/toggle-status")
async def admin_toggle_delivery_zone(
    zone_id: int,
    admin_ctx: OpsAdminDep,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
):
    user, _ = admin_ctx
    zone = await admin_service.toggle_delivery_zone(zone_id, actor_id=user.id)
    return {"detail": f"Zone '{zone.name}' is now {'active' if zone.is_active else 'paused'}"}
