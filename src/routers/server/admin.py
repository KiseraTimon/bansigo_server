# src/routers/server/admin.py

"""
administrative console router for store managers (admin) and business owners (superadmin).
serves server-rendered Jinja2 views and operational AJAX endpoints.
all endpoints are excluded from openapi documentation schemas to prevent attacker discovery.
"""

from decimal import Decimal
from typing import Annotated, Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Request, Response,
    UploadFile, status,
)
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings, get_settings
from src.database import get_db
from src.dependencies import (
    CurrentAdmin, DbSession, SettingsDep, get_admin_service, get_auth_service,
    get_catalogue_service, get_current_admin, require_admin_level,
)
from src.exceptions import AppError, ForbiddenError, InvalidCredentialsError, NotFoundError, UnauthorizedError
from src.helpers import (
    export_products_to_csv, generate_sample_csv_template, import_products_from_csv,
)
from src.models import (
    Admin, AdminLevel, ApprovalStatus, Inventory, Product, TaxClass, UnitType, User, UserRole,
)
from src.repositories import AdminRepository, ProductRepository, UserRepository
from src.schemas import ProductCreate, ProductUpdate
from src.services import AdminService, AuthService, AuditService, CatalogueService
from utilities import get_logger

log = get_logger(__name__)

router = APIRouter(include_in_schema=False)


def _admin_base_url(settings: Settings) -> str:
    path = getattr(settings, "admin_portal_path", "console-hq").strip("/")
    return f"/{path}/admin"



@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard_view(
    request: Request,
    settings: SettingsDep,
    db: DbSession,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
):
    """
    main admin dashboard
    :param request: Request
    :param settings: Settings
    :param db: AsyncSession
    :param admin_service: AdminService
    :return:
    """

    base_url = _admin_base_url(settings)

    # authentication via session cookie or bearer token
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
            # first admin is a superadmin by default
            admin = Admin(user_id=user.id, level=AdminLevel.SUPER)
            db.add(admin)
            await db.commit()
            await db.refresh(admin)

    except Exception:
        return RedirectResponse(url=f"{base_url}/login", status_code=status.HTTP_303_SEE_OTHER)

    # assembling data for dashboard
    summary = await admin_service.get_dashboard_summary()
    products_list = await admin_service.get_products_data(limit=100)
    actors = await admin_service.get_actors_data(current_admin_user_id=user.id)
    security = admin_service.get_security_posture()
    reviews = await admin_service.get_reviews_summary()
    audits = await admin_service.get_audit_trail(limit=30)
    catalogue_options = await admin_service.get_catalogue_form_options()

    admin_level_str = admin.level.value if hasattr(admin.level, "value") else str(admin.level)
    is_superadmin = (admin.level == AdminLevel.SUPER)

    return request.app.state.templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "admin_user": user,
            "admin_profile": admin,
            "admin_level": admin_level_str,
            "is_superadmin": is_superadmin,
            "base_url": base_url,
            "summary": summary,
            "products": products_list,
            "categories": catalogue_options.get("categories", []),
            "brands": catalogue_options.get("brands", []),
            "actors": actors,
            "security": security,
            "reviews": reviews,
            "audits": audits,
            "current_admin_user_id": user.id,
        },
    )


@router.get("/login", response_class=HTMLResponse)
async def admin_login_view(request: Request, settings: SettingsDep):
    """
    admin login page
    :param request: Reques
    :param settings: Settings
    :return:
    """

    base_url = _admin_base_url(settings)
    return request.app.state.templates.TemplateResponse(
        request,
        "admin/login.html",
        {
            "base_url": base_url,
            "app_name": settings.app_name,
        },
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
    """
    admin login request
    :param request: Request
    :param settings: Settings
    :param db: AsyncSession
    :param auth_service: AuthService
    :param username: str
    :param password: str
    :return:
    """

    base_url = _admin_base_url(settings)
    try:
        user = await auth_service.authenticate(username, password)
        if user.role != UserRole.ADMIN:
            raise ForbiddenError("Access denied: Administrative privileges required")

        # ensuring the admin row exists
        admin = await AdminRepository(db).get_by_user_id(user.id)
        if not admin:
            admin = Admin(user_id=user.id, level=AdminLevel.SUPER)
            db.add(admin)
            await db.commit()

        token = auth_service.issue_token(user)

        # checking request source (ajax vs form)
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
    """
    admin logout
    :param settings: Settings
    :return:
    """

    base_url = _admin_base_url(settings)
    response = RedirectResponse(url=f"{base_url}/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response


@router.post("/products")
async def add_product(
    admin_ctx: CurrentAdmin,
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
    """
    admin route to add a product
    :param admin_ctx: CurrentAdmin
    :param catalogue_service: CatalogueService
    :param db: AsyncSession
    :param category_id: int
    :param brand_id: int | None
    :param sku: str
    :param barcode: str | None
    :param name: str
    :param description: str | None
    :param image_url: str | None
    :param gallery_images: str | None
    :param unit: str
    :param pack_size_label: str | None
    :param price: Decimal
    :param compare_at_price: Decimal | None
    :param cost_price: Decimal | None
    :param tax_class: str
    :param is_age_restricted: bool
    :param initial_stock: Decimal
    :param reorder_level: Decimal
    :return:
    """

    import json
    user, _ = admin_ctx
    unit_enum = UnitType(unit) if unit in [u.value for u in UnitType] else UnitType.PIECE
    tax_enum = TaxClass(tax_class) if tax_class in [t.value for t in TaxClass] else TaxClass.STANDARD

    parsed_gallery: list[str] = []
    if gallery_images:
        try:
            data = json.loads(gallery_images)
            if isinstance(data, list):
                parsed_gallery = [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            parsed_gallery = [img.strip() for img in gallery_images.split(",") if img.strip()]

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

    # setting a default initial stock if provided
    if initial_stock > 0 or reorder_level > 0:
        inv = (
            await db.execute(
                select(Inventory).where(Inventory.product_id == created_prod.id)
            )
        ).scalar_one_or_none()
        if inv:
            inv.quantity_on_hand = initial_stock
            inv.reorder_level = reorder_level
            await db.commit()

    return {"detail": "Product created successfully", "product_id": created_prod.id}


@router.patch("/products/{product_id}")
async def update_product(
    product_id: int,
    admin_ctx: CurrentAdmin,
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
    """
    admin route to update a product
    :param product_id: int
    :param admin_ctx: CurrentAdmin
    :param catalogue_service: CatalogueService
    :param db: AsyncSession
    :param name: str | None
    :param category_id: int | None
    :param brand_id: int | None
    :param sku: str | None
    :param barcode: str | None
    :param unit: str | None
    :param pack_size_label: str | None
    :param price: Decimal | None
    :param compare_at_price: Decimal | None
    :param cost_price: Decimal | None
    :param tax_class: str | None
    :param is_active: bool | None
    :param is_age_restricted: bool | None
    :param image_url: str | None
    :param gallery_images: str | None
    :param description: str | None
    :param quantity_on_hand: Decimal | None
    :param reorder_level: Decimal | None
    :return:
    """

    import json
    user, _ = admin_ctx
    update_data: dict = {}

    if gallery_images is not None:
        parsed_gallery: list[str] = []
        try:
            data = json.loads(gallery_images)
            if isinstance(data, list):
                parsed_gallery = [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            parsed_gallery = [img.strip() for img in gallery_images.split(",") if img.strip()]
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

    # updating inventory if supplied
    if quantity_on_hand is not None or reorder_level is not None:
        inv = (
            await db.execute(
                select(Inventory).where(Inventory.product_id == product_id)
            )
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
    admin_ctx: CurrentAdmin,
    catalogue_service: Annotated[CatalogueService, Depends(get_catalogue_service)],
    db: DbSession,
):
    """
    admin route to edit product status
    :param product_id: int
    :param admin_ctx: CurrentAdmin
    :param catalogue_service: CatalogueService
    :param db: AsyncSession
    :return:
    """

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
    admin_ctx: CurrentAdmin,
    catalogue_service: Annotated[CatalogueService, Depends(get_catalogue_service)],
):
    """
    admin route to delete a product
    :param product_id: int
    :param admin_ctx: CurrentAdmin
    :param catalogue_service: CatalogueService
    :return:
    """

    user, _ = admin_ctx
    return await catalogue_service.delete_product(product_id, actor_id=user.id)



@router.get("/products/export")
async def export_products_csv(
    _: CurrentAdmin,
    db: DbSession,
):
    """
    bulk export of products catalogue into a CSV
    :param _: CurrentAdmin
    :param db: AsyncSession
    :return:
    """

    csv_content = await export_products_to_csv(db)
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bansigo_catalogue_products.csv"},
    )


@router.get("/products/template")
async def download_csv_template(
    _: CurrentAdmin,
):
    """
    route to download the products upload template
    :param _: CurrentAdmin
    :return:
    """

    template_content = generate_sample_csv_template()
    return PlainTextResponse(
        content=template_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bansigo_products_template.csv"},
    )


@router.post("/products/bulk-upload")
async def bulk_upload_products_csv(
    admin_ctx: CurrentAdmin,
    db: DbSession,
    file: UploadFile = File(...),
):
    user, _ = admin_ctx
    content_bytes = await file.read()
    try:
        csv_text = content_bytes.decode("utf-8-sig")  # Handles Excel UTF-8 BOM
    except UnicodeDecodeError:
        csv_text = content_bytes.decode("latin-1")

    report = await import_products_from_csv(csv_text, actor_id=user.id, db=db)
    return report


# ---------------------------------------------------------------------------
# SYSTEM ACTORS REGULATION (Staff, Riders, Admins)
# ---------------------------------------------------------------------------
@router.post("/actors/riders/{rider_id}/vet")
async def vet_rider(
    rider_id: int,
    admin_ctx: CurrentAdmin,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
    action: str = Form(...),  # approve, reject, suspend
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


@router.post("/actors/staff/{staff_id}/toggle-duty")
async def toggle_staff_duty(
    staff_id: int,
    admin_ctx: CurrentAdmin,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
):
    user, _ = admin_ctx
    staff = await admin_service.toggle_staff_duty(staff_id, actor_id=user.id)
    return {"detail": f"Staff member on-duty status: {staff.is_on_duty}", "is_on_duty": staff.is_on_duty}


@router.patch("/actors/admins/{target_admin_id}/level")
async def update_admin_level(
    target_admin_id: int,
    admin_ctx: CurrentAdmin,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
    new_level: str = Form(...),  # super, operations, finance
):
    _, actor_admin = admin_ctx
    level_map = {
        "super": AdminLevel.SUPER,
        "operations": AdminLevel.OPERATIONS,
        "finance": AdminLevel.FINANCE,
    }
    level_enum = level_map.get(new_level.lower())
    if not level_enum:
        raise HTTPException(status_code=400, detail="Invalid admin level")

    admin = await admin_service.set_admin_level(target_admin_id, level_enum, actor_admin=actor_admin)
    return {"detail": f"Admin level updated to {admin.level.value}", "admin_id": admin.id}


@router.post("/actors/users/{user_id}/toggle-status")
async def toggle_user_active(
    user_id: int,
    admin_ctx: CurrentAdmin,
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
):
    _, actor_admin = admin_ctx
    user = await admin_service.toggle_user_active(user_id, actor_admin=actor_admin)
    return {"detail": f"User account active status: {user.is_active}", "is_active": user.is_active}


# ---------------------------------------------------------------------------
# SECURITY & AUTHENTICATION CONFIGURATION & 2FA
# ---------------------------------------------------------------------------
@router.post("/security/2fa/request")
async def request_two_factor(
    admin_ctx: CurrentAdmin,
    settings: SettingsDep,
    db: DbSession,
):
    """
    generates and sends a 2FA OTP code to the logged-in administrator via email
    """
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

    # Extract OTP code from mail body for dev/test verification
    import re
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
    """
    verifies OTP and enables 2FA for the administrator account
    """
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
    """
    disables 2FA on the administrator account
    """
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
    admin_ctx: CurrentAdmin,
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
    user, admin = admin_ctx
    if admin.level != AdminLevel.SUPER:
        raise ForbiddenError("Only Superadministrators can alter security and system policies")

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

    # Update runtime settings
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
# ADMINISTRATOR PERSONAL ACCOUNT SETTINGS (PROTECTED SELF-MANAGEMENT)
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
    """
    updates the logged-in administrator's personal profile details.
    self-deactivation, deletion, and role adjustments are strictly prevented.
    """
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
    """
    updates administrator password after verifying current credentials
    """
    user, _ = admin_ctx
    await admin_service.change_admin_password(
        user=user,
        current_password=current_password,
        new_password=new_password,
        new_password_confirm=new_password_confirm,
    )
    return {"detail": "Password updated successfully"}
