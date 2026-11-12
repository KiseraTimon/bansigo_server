# tests/test_admin.py

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from src import create_app
from src.database import Base, get_db
from src.helpers import (
    export_products_to_csv,
    generate_sample_csv_template,
    import_products_from_csv,
)
from src.models import (
    Admin, AdminLevel, ApprovalStatus, Category, Product, Rider, TaxClass, UnitType,
    User, UserRole,
)
from src.security import hash_password_async, create_access_token


@pytest_asyncio.fixture
async def test_db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def app_client(test_db_session: AsyncSession):
    app = create_app()

    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_admin_routes_excluded_from_openapi_schema(app_client: AsyncClient):
    """
    verifies that administrative endpoints are hidden from public api discovery schemas
    """
    settings = get_settings()
    portal_path = settings.admin_portal_path

    response = await app_client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()

    for path in data.get("paths", {}):
        assert portal_path not in path, f"Found secret admin path in openapi schema: {path}"
        assert not path.endswith("/admin"), f"Found unshielded admin route: {path}"


@pytest.mark.asyncio
async def test_admin_login_page_renders_with_brand(app_client: AsyncClient):
    """
    verifies that admin login renders with bansi branding and desktop constraints
    """
    settings = get_settings()
    url = f"/{settings.admin_portal_path}/admin/login"

    response = await app_client.get(url)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text
    assert "Bansi" in html
    assert "ADMINISTRATIVE CONSOLE" in html
    assert "Sign In to Console" in html


@pytest.mark.asyncio
async def test_unauthenticated_dashboard_redirects(app_client: AsyncClient):
    """
    verifies that visiting the admin panel without credentials redirects to login
    """
    settings = get_settings()
    url = f"/{settings.admin_portal_path}/admin"

    response = await app_client.get(url, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith(f"/{settings.admin_portal_path}/admin/login")


@pytest.mark.asyncio
async def test_bulk_csv_template_generation():
    """
    verifies that the spreadsheet template includes image_url, pack_size_label, and variant fields
    """
    csv_text = generate_sample_csv_template()
    assert "sku,barcode,name" in csv_text
    assert "image_url" in csv_text
    assert "pack_size_label" in csv_text
    assert "cost_price" in csv_text
    assert "reorder_level" in csv_text
    assert "FLOUR-PEMBE-1KG" in csv_text
    assert "FLOUR-PEMBE-2KG" in csv_text


@pytest.mark.asyncio
async def test_bulk_csv_import_and_export(test_db_session: AsyncSession):
    """
    verifies spreadsheet bulk import creates products, variants, and stock,
    and bulk export outputs them accurately
    """
    # 1. Create an admin user to act as actor
    admin_user = User(
        first_name="Store",
        last_name="Manager",
        username="manager1",
        email="manager@bansigo.store",
        phone="+254700000001",
        password_hash=await hash_password_async("Password123!"),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    test_db_session.add(admin_user)
    await test_db_session.commit()
    await test_db_session.refresh(admin_user)

    # 2. Import sample CSV
    csv_content = generate_sample_csv_template()
    report = await import_products_from_csv(csv_content, actor_id=admin_user.id, db=test_db_session)

    assert report["created_count"] == 3
    assert len(report["errors"]) == 0

    # 3. Export to CSV and verify contents
    exported_csv = await export_products_to_csv(test_db_session)
    assert "FLOUR-PEMBE-1KG" in exported_csv
    assert "FLOUR-PEMBE-2KG" in exported_csv
    assert "MILK-BROOKSIDE-500ML" in exported_csv


@pytest.mark.asyncio
async def test_authenticated_dashboard_rendering(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies that an authenticated superadmin can access the full admin dashboard
    """
    settings = get_settings()

    # 1. Create Superadmin User & Admin record
    user = User(
        first_name="Bansi",
        last_name="Owner",
        username="superowner",
        email="owner@bansigo.store",
        phone="+254799000111",
        password_hash=await hash_password_async("SecurePass123!"),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    settings.require_verified_email = False
    test_db_session.add(user)
    await test_db_session.commit()
    await test_db_session.refresh(user)

    admin = Admin(user_id=user.id, level=AdminLevel.SUPER)
    test_db_session.add(admin)
    await test_db_session.commit()

    token = create_access_token(user.id, settings.secret_key.get_secret_value(), expires_minutes=60)

    # 2. Access dashboard with session cookie
    url = f"/{settings.admin_portal_path}/admin"
    app_client.cookies.set("access_token", token)
    response = await app_client.get(url)

    assert response.status_code == 200
    html = response.text
    assert "Desktop Workstation Required" in html
    assert "Superadmin (Owner)" in html
    assert "Catalogue & Variant Inventory" in html
    assert "System Actors & Workforce" in html
    assert "Authentication & Security Governance" in html
    assert "Recent Administrative Activity" in html


@pytest.mark.asyncio
async def test_rider_vetting_and_auditing(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies that rider vetting action succeeds and updates approval status
    """
    settings = get_settings()

    # Create admin
    admin_user = User(
        first_name="Admin",
        last_name="Tester",
        username="admintester",
        email="admintester@bansigo.store",
        phone="+254788112233",
        password_hash=await hash_password_async("Pass123!"),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    settings.require_verified_email = False
    test_db_session.add(admin_user)
    await test_db_session.commit()
    await test_db_session.refresh(admin_user)

    admin_row = Admin(user_id=admin_user.id, level=AdminLevel.SUPER)
    test_db_session.add(admin_row)

    # Create rider user & rider
    rider_user = User(
        first_name="Peter",
        last_name="Kamau",
        username="pkamau",
        email="pkamau@gmail.com",
        phone="+254733445566",
        password_hash=await hash_password_async("RiderPass1!"),
        role=UserRole.RIDER,
        is_active=True,
    )
    test_db_session.add(rider_user)
    await test_db_session.commit()
    await test_db_session.refresh(rider_user)

    rider = Rider(
        user_id=rider_user.id,
        approval_status=ApprovalStatus.PENDING,
        vehicle_plate="KMEE 901P",
    )
    test_db_session.add(rider)
    await test_db_session.commit()
    await test_db_session.refresh(rider)

    token = create_access_token(admin_user.id, settings.secret_key.get_secret_value(), expires_minutes=60)

    # Execute vetting via POST
    vet_url = f"/{settings.admin_portal_path}/admin/actors/riders/{rider.id}/vet"
    response = await app_client.post(
        vet_url,
        data={"action": "approve"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    res_data = response.json()
    assert "approved" in res_data["detail"]

    # Verify database state
    await test_db_session.refresh(rider)
    assert rider.approval_status == ApprovalStatus.APPROVED



@pytest.mark.asyncio
async def test_product_creation_and_variant_handling(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies that an admin can create a product with size variant attributes and initial stock
    """
    settings = get_settings()

    # 1. Setup admin
    admin_user = User(
        first_name="Stock",
        last_name="Manager",
        username="stockmgr",
        email="stock@bansigo.store",
        phone="+254711889900",
        password_hash=await hash_password_async("MgrPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    settings.require_verified_email = False
    test_db_session.add(admin_user)
    await test_db_session.commit()
    await test_db_session.refresh(admin_user)

    admin_row = Admin(user_id=admin_user.id, level=AdminLevel.OPERATIONS)
    test_db_session.add(admin_row)

    # 2. Setup category
    category = Category(name="Staples", slug="staples", created_by=admin_user.id, updated_by=admin_user.id)
    test_db_session.add(category)
    await test_db_session.commit()
    await test_db_session.refresh(category)

    token = create_access_token(admin_user.id, settings.secret_key.get_secret_value(), expires_minutes=60)

    # 3. Create Base Product (e.g. 1kg variant)
    url = f"/{settings.admin_portal_path}/admin/products"
    res1 = await app_client.post(
        url,
        data={
            "name": "Daawat Long Grain Rice 1kg",
            "pack_size_label": "1 kg",
            "sku": "RICE-DAAWAT-1KG",
            "barcode": "616110099001",
            "category_id": category.id,
            "unit": "piece",
            "price": "280.00",
            "cost_price": "230.00",
            "tax_class": "zero_rated",
            "initial_stock": "50.000",
            "reorder_level": "10.000",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res1.status_code == 200
    prod_id = res1.json()["product_id"]

    # 4. Create Size Variant (e.g. 2kg variant)
    res2 = await app_client.post(
        url,
        data={
            "name": "Daawat Long Grain Rice 2kg",
            "pack_size_label": "2 kg",
            "sku": "RICE-DAAWAT-2KG",
            "barcode": "616110099002",
            "category_id": category.id,
            "unit": "piece",
            "price": "540.00",
            "cost_price": "445.00",
            "tax_class": "zero_rated",
            "initial_stock": "75.000",
            "reorder_level": "15.000",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res2.status_code == 200

    # 5. Patch price on 1kg product
    patch_res = await app_client.patch(
        f"{url}/{prod_id}",
        data={"price": "275.00", "reorder_level": "12.000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch_res.status_code == 200

    # 6. Toggle product active status
    toggle_res = await app_client.post(
        f"{url}/{prod_id}/toggle-status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert toggle_res.status_code == 200
    assert toggle_res.json()["is_active"] is False


@pytest.mark.asyncio
async def test_superadmin_vs_operations_security_restrictions(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies that operations admin cannot change security policies or promote admins,
    while superadmin can
    """
    settings = get_settings()

    # Create Operations Admin
    ops_user = User(
        first_name="Store",
        last_name="Manager",
        username="opsmgr",
        email="ops@bansigo.store",
        phone="+254722114477",
        password_hash=await hash_password_async("Pass123!"),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    settings.require_verified_email = False
    test_db_session.add(ops_user)
    await test_db_session.commit()
    await test_db_session.refresh(ops_user)

    ops_admin = Admin(user_id=ops_user.id, level=AdminLevel.OPERATIONS)
    test_db_session.add(ops_admin)
    await test_db_session.commit()

    ops_token = create_access_token(ops_user.id, settings.secret_key.get_secret_value(), expires_minutes=60)

    # Operations admin tries to modify security settings -> 403 Forbidden
    sec_url = f"/{settings.admin_portal_path}/admin/security/settings"
    res_forbidden = await app_client.post(
        sec_url,
        data={"access_tokens_expire_minutes": 45},
        headers={"Authorization": f"Bearer {ops_token}"},
    )
    assert res_forbidden.status_code == 403

    # Create Superadmin
    super_user = User(
        first_name="Business",
        last_name="Owner",
        username="bizowner",
        email="bizowner@bansigo.store",
        phone="+254711335577",
        password_hash=await hash_password_async("OwnerPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    settings.require_verified_email = False
    test_db_session.add(super_user)
    await test_db_session.commit()
    await test_db_session.refresh(super_user)

    super_admin = Admin(user_id=super_user.id, level=AdminLevel.SUPER)
    test_db_session.add(super_admin)
    await test_db_session.commit()

    super_token = create_access_token(super_user.id, settings.secret_key.get_secret_value(), expires_minutes=60)

    # Superadmin updates security settings -> 200 OK
    res_ok = await app_client.post(
        sec_url,
        data={"access_tokens_expire_minutes": 45, "require_verified_email": "true"},
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["current"]["access_tokens_expire_minutes"] == 45


@pytest.mark.asyncio
async def test_admin_login_authentication_flow(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies standard form submission and session cookie issuance on login
    """
    settings = get_settings()

    raw_password = "SecretPassword123!"
    user = User(
        first_name="Admin",
        last_name="LoginTest",
        username="adminlogin",
        email="adminlogin@bansigo.store",
        phone="+254799887766",
        password_hash=await hash_password_async(raw_password),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    settings.require_verified_email = False
    test_db_session.add(user)
    await test_db_session.commit()

    login_url = f"/{settings.admin_portal_path}/admin/login"

    # Bad password -> 401
    bad_res = await app_client.post(login_url, data={"username": "adminlogin", "password": "WrongPassword"})
    assert bad_res.status_code == 401
    assert "Invalid administrative username or password" in bad_res.text

    # Correct password -> 303 Redirect to dashboard + cookie set
    good_res = await app_client.post(
        login_url,
        data={"username": "adminlogin", "password": raw_password},
        follow_redirects=False,
    )
    assert good_res.status_code == 303
    assert "access_token" in good_res.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_product_gallery_images_reorder_and_persistence(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies product creation and updates with arrangeable gallery images
    """
    import json
    settings = get_settings()

    user = User(
        first_name="Store",
        last_name="Manager",
        username="gallery_admin",
        email="gallery_admin@bansigo.store",
        phone="+254700112233",
        password_hash=await hash_password_async("Pass123!"),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    test_db_session.add(user)
    await test_db_session.commit()
    await test_db_session.refresh(user)

    admin = Admin(user_id=user.id, level=AdminLevel.SUPER)
    test_db_session.add(admin)

    category = Category(name="Pantry Goods", slug="pantry-goods")
    test_db_session.add(category)
    await test_db_session.commit()
    await test_db_session.refresh(category)

    token = create_access_token(user.id, settings.secret_key.get_secret_value(), expires_minutes=60)
    prod_url = f"/{settings.admin_portal_path}/admin/products"

    gallery = ["https://bansigo.store/img/flour-1.jpg", "https://bansigo.store/img/flour-2.jpg"]
    res = await app_client.post(
        prod_url,
        data={
            "name": "Super Maize Meal 2kg",
            "category_id": category.id,
            "sku": "SMM-2KG",
            "price": "220.00",
            "unit": "piece",
            "gallery_images": json.dumps(gallery),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    prod_id = res.json()["product_id"]

    # Verify persisted in database
    from src.repositories import ProductRepository
    prod = await ProductRepository(test_db_session).get_by_id(prod_id)
    assert prod is not None
    assert prod.image_url == "https://bansigo.store/img/flour-1.jpg"
    assert prod.gallery_images == gallery

    # Reorder images (move flour-2 to primary cover)
    reordered_gallery = ["https://bansigo.store/img/flour-2.jpg", "https://bansigo.store/img/flour-1.jpg", "https://bansigo.store/img/flour-3.jpg"]
    patch_res = await app_client.patch(
        f"{prod_url}/{prod_id}",
        data={"gallery_images": json.dumps(reordered_gallery)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch_res.status_code == 200

    await test_db_session.refresh(prod)
    assert prod.gallery_images == reordered_gallery
    assert prod.image_url == "https://bansigo.store/img/flour-2.jpg"


@pytest.mark.asyncio
async def test_two_factor_auth_lifecycle(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies 2fa challenge request, code confirmation, and account disabling
    """
    settings = get_settings()
    settings.mail_suppress_send = True

    user = User(
        first_name="Admin",
        last_name="2FA",
        username="admin_2fa_user",
        email="twofa_admin@bansigo.store",
        phone="+254711998877",
        password_hash=await hash_password_async("Pass123!"),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    test_db_session.add(user)
    await test_db_session.commit()
    await test_db_session.refresh(user)

    admin = Admin(user_id=user.id, level=AdminLevel.SUPER)
    test_db_session.add(admin)
    await test_db_session.commit()

    token = create_access_token(user.id, settings.secret_key.get_secret_value(), expires_minutes=60)
    base_url = f"/{settings.admin_portal_path}/admin/security/2fa"

    # 1. Request 2FA OTP
    req_res = await app_client.post(
        f"{base_url}/request",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert req_res.status_code == 200
    assert "Two-factor authentication code sent" in req_res.json()["detail"]

    # Retrieve issued code from verification_tokens table
    from src.models import VerificationToken, TokenPurpose
    from sqlalchemy import select
    token_row = (
        await test_db_session.execute(
            select(VerificationToken).where(
                VerificationToken.user_id == user.id,
                VerificationToken.purpose == TokenPurpose.TWO_FACTOR_AUTH,
            )
        )
    ).scalar_one_or_none()
    assert token_row is not None

    code = req_res.json().get("dev_code")
    assert code is not None

    # 2. Confirm 2FA OTP
    confirm_res = await app_client.post(
        f"{base_url}/confirm",
        data={"code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm_res.status_code == 200
    assert confirm_res.json()["two_factor_enabled"] is True

    await test_db_session.refresh(user)
    assert user.two_factor_enabled is True

    # 3. Disable 2FA
    disable_res = await app_client.post(
        f"{base_url}/disable",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert disable_res.status_code == 200
    assert disable_res.json()["two_factor_enabled"] is False

    await test_db_session.refresh(user)
    assert user.two_factor_enabled is False


@pytest.mark.asyncio
async def test_superadmin_self_regulation_prevented(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies that a superadmin cannot demote or deactivate their own account
    """
    settings = get_settings()

    user = User(
        first_name="Solo",
        last_name="Owner",
        username="solo_owner",
        email="solo_owner@bansigo.store",
        phone="+254711556677",
        password_hash=await hash_password_async("OwnerPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    test_db_session.add(user)
    await test_db_session.commit()
    await test_db_session.refresh(user)

    admin = Admin(user_id=user.id, level=AdminLevel.SUPER)
    test_db_session.add(admin)
    await test_db_session.commit()
    await test_db_session.refresh(admin)

    token = create_access_token(user.id, settings.secret_key.get_secret_value(), expires_minutes=60)

    # Try changing own admin level -> 403 Forbidden
    level_url = f"/{settings.admin_portal_path}/admin/actors/admins/{admin.id}/level"
    res_level = await app_client.patch(
        level_url,
        data={"new_level": "operations"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_level.status_code == 403
    assert "cannot alter their own privilege level" in res_level.json()["detail"]

    # Try deactivating own user account -> 403 Forbidden
    status_url = f"/{settings.admin_portal_path}/admin/actors/users/{user.id}/toggle-status"
    res_status = await app_client.post(
        status_url,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_status.status_code == 403
    assert "cannot deactivate their own account" in res_status.json()["detail"]

    # Check that get_actors_data excludes self
    from src.services.admin_service import AdminService
    admin_service = AdminService(test_db_session, settings)
    actors = await admin_service.get_actors_data(current_admin_user_id=user.id)
    admin_ids = [a["user_id"] for a in actors["admins"]]
    assert user.id not in admin_ids


@pytest.mark.asyncio
async def test_reviews_repository_and_summary(test_db_session: AsyncSession):
    """
    verifies database review creation, summary statistics, and formatting
    """
    from src.models import Customer, Review, ReviewTargetType
    from src.repositories import ReviewRepository
    from src.services.admin_service import AdminService
    settings = get_settings()

    cust_user = User(
        first_name="Jane",
        last_name="Muthoni",
        username="jane_m",
        email="jane.m@example.com",
        phone="+254722123456",
        password_hash="fakehash",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    test_db_session.add(cust_user)
    await test_db_session.commit()
    await test_db_session.refresh(cust_user)

    customer = Customer(user_id=cust_user.id)
    test_db_session.add(customer)
    await test_db_session.commit()
    await test_db_session.refresh(customer)

    # Add reviews
    r1 = Review(customer_id=customer.id, target_type=ReviewTargetType.GENERAL, rating=5, comment="Excellent shopping service!")
    r2 = Review(customer_id=customer.id, target_type=ReviewTargetType.DELIVERY, rating=4, comment="Quick rider arrival.")
    test_db_session.add_all([r1, r2])
    await test_db_session.commit()

    admin_service = AdminService(test_db_session, settings)
    summary = await admin_service.get_reviews_summary()

    assert summary["total_reviews"] == 2
    assert summary["average_rating"] == "4.50"
    assert summary["satisfaction_rate"] == "100%"
    assert len(summary["reviews"]) == 2
    assert summary["reviews"][0]["customer_name"] == "Jane Muthoni"


@pytest.mark.asyncio
async def test_bulk_excel_workbook_import_and_upload(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies that the multi-sheet Kenyan products Excel workbook parses cleanly,
    provisions categories and brands, establishes inventory, and supports idempotency.
    """
    import os
    from decimal import Decimal
    from src.helpers.catalogue_import_export import import_products_from_excel
    from src.models import Product, Inventory, Category, Brand, UnitType, TaxClass
    from sqlalchemy import select

    settings = get_settings()

    # 1. Create admin user
    admin_user = User(
        first_name="Catalogue",
        last_name="Admin",
        username="cat_admin",
        email="cat_admin@bansigo.store",
        phone="+254711998877",
        password_hash="hash123",
        role=UserRole.ADMIN,
        is_active=True,
    )
    test_db_session.add(admin_user)
    await test_db_session.commit()
    await test_db_session.refresh(admin_user)

    admin_row = Admin(user_id=admin_user.id, level=AdminLevel.SUPER)
    test_db_session.add(admin_row)
    await test_db_session.commit()

    # 2. Load generated Excel workbook
    excel_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "catalogue", "kenyan_products_catalogue.xlsx")
    assert os.path.exists(excel_path), f"Workbook missing at {excel_path}"

    with open(excel_path, "rb") as f:
        excel_bytes = f.read()

    # 3. Direct helper ingestion
    report = await import_products_from_excel(excel_bytes, actor_id=admin_user.id, db=test_db_session)
    assert report["errors"] == [], f"Errors during excel import: {report['errors']}"
    assert report["created_count"] >= 200
    assert report["total_processed"] >= 200

    # 4. Verify specific sample Kenyan products
    stix = (await test_db_session.execute(
        select(Product).where(Product.sku == "SNCK-STIX-CHIL-30G")
    )).scalar_one_or_none()
    assert stix is not None
    assert stix.name == "Stix Potato Crisps Chilli Lemon 30g"
    assert stix.price == Decimal("30.00")
    assert stix.unit == UnitType.PIECE
    assert stix.pack_size_label == "30g"
    assert stix.tax_class == TaxClass.STANDARD

    # 5. Verify HTTP bulk upload endpoint with .xlsx
    token = create_access_token(admin_user.id, settings.secret_key.get_secret_value(), expires_minutes=60)
    bulk_url = f"/{settings.admin_portal_path}/admin/products/bulk-upload"
    response = await app_client.post(
        bulk_url,
        files={"file": ("kenyan_products.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    upload_res = response.json()
    assert upload_res["errors"] == []
    # On second upload, existing SKUs are updated
    assert upload_res["updated_count"] >= 200
