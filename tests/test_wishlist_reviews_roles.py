# tests/test_wishlist_reviews_roles.py

from datetime import datetime, timezone
from decimal import Decimal
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from src import create_app
from src.database import Base, get_db
from src.models import (
    Admin,
    AdminLevel,
    ApprovalStatus,
    Category,
    Customer,
    Delivery,
    DeliveryStatus,
    FulfilmentType,
    Inventory,
    Order,
    OrderItem,
    OrderPaymentStatus,
    OrderStatus,
    Payment,
    PaymentChannel,
    PaymentMethod,
    PaymentStatus,
    Product,
    ReviewTargetType,
    Rider,
    RiderStatus,
    TaxClass,
    UnitType,
    User,
    UserRole,
    VehicleType,
)
from src.security import create_access_token, hash_password_async
from src.services.rider_service import RiderService


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


async def _create_admin(
    db: AsyncSession, *, suffix: str, level: AdminLevel
) -> tuple[User, Admin, str]:
    settings = get_settings()
    settings.require_verified_email = False
    user = User(
        first_name=level.value.title(),
        last_name="Admin",
        username=f"adm_{suffix}",
        email=f"adm_{suffix}@bansigo.store",
        phone=f"+25471000{abs(hash(suffix)) % 10000:04d}",
        password_hash=await hash_password_async("SecurePass123!"),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    admin = Admin(user_id=user.id, level=level)
    db.add(admin)
    await db.commit()
    await db.refresh(admin)

    token = create_access_token(user.id, settings.secret_key.get_secret_value(), expires_minutes=60)
    return user, admin, token


async def _create_customer_and_product(db: AsyncSession) -> tuple[User, Customer, Product, str]:
    settings = get_settings()
    settings.require_verified_email = False
    user = User(
        first_name="Amina",
        last_name="Otieno",
        username="amina_otieno",
        email="amina@example.com",
        phone="+254722111222",
        password_hash=await hash_password_async("CustPass123!"),
        role=UserRole.CUSTOMER,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()

    customer = Customer(user_id=user.id)
    cat = Category(name="Fresh Dairy", slug="fresh-dairy", is_active=True)
    db.add_all([customer, cat])
    await db.flush()

    product = Product(
        category_id=cat.id,
        sku="DAIRY-001",
        name="Brookside Whole Milk 500ml",
        slug="brookside-whole-milk-500ml",
        unit=UnitType.PIECE,
        pack_size_label="500ml",
        price=Decimal("70.00"),
        cost_price=Decimal("52.00"),
        tax_class=TaxClass.ZERO_RATED,
        is_active=True,
    )
    db.add(product)
    await db.flush()

    inv = Inventory(
        product_id=product.id,
        quantity_on_hand=Decimal("40"),
        quantity_reserved=Decimal("0"),
        reorder_level=Decimal("10"),
        reorder_quantity=Decimal("25"),
    )
    db.add(inv)
    await db.commit()
    await db.refresh(customer)
    await db.refresh(product)

    token = create_access_token(user.id, settings.secret_key.get_secret_value(), expires_minutes=60)
    return user, customer, product, token


@pytest.mark.asyncio
async def test_role_differentiated_dashboards_and_rbac(
    app_client: AsyncClient, test_db_session: AsyncSession
):
    settings = get_settings()
    base = f"/{settings.admin_portal_path}/admin"
    _, _, prod, _ = await _create_customer_and_product(test_db_session)

    _, _, fin_token = await _create_admin(test_db_session, suffix="fin", level=AdminLevel.FINANCE)
    _, _, inv_token = await _create_admin(test_db_session, suffix="inv", level=AdminLevel.INVENTORY)
    _, _, sup_token = await _create_admin(test_db_session, suffix="sup", level=AdminLevel.SUPPORT)
    _, _, ops_token = await _create_admin(test_db_session, suffix="ops", level=AdminLevel.OPERATIONS)

    # Finance dashboard renders Finance workspace, omits Security/Inventory sections, enforces RBAC
    app_client.cookies.set("access_token", fin_token)
    res_fin = await app_client.get(base)
    assert res_fin.status_code == 200
    assert 'data-admin-role="finance"' in res_fin.text
    assert "Finance, Payments &amp; Refunds Treasury" in res_fin.text
    assert "Inventory Control, Stock Movements" not in res_fin.text
    assert "Dispatch, Fleet Routing" not in res_fin.text

    # Finance cannot write inventory or security settings
    res_forbid_inv = await app_client.post(
        f"{base}/inventory/{prod.id}/receive",
        data={"quantity": "5"},
    )
    assert res_forbid_inv.status_code == 403

    res_forbid_sec = await app_client.post(
        f"{base}/security/settings",
        data={"log_level": "DEBUG"},
    )
    assert res_forbid_sec.status_code == 403

    # Inventory admin renders Inventory Control workspace and can receive stock & create supplier
    app_client.cookies.set("access_token", inv_token)
    res_inv = await app_client.get(base)
    assert res_inv.status_code == 200
    assert 'data-admin-role="inventory"' in res_inv.text
    assert "Inventory Control, Stock Movements &amp; Suppliers" in res_inv.text

    res_sup_create = await app_client.post(
        f"{base}/suppliers",
        data={"name": "Lake Basin Distributors", "phone": "+254733000111", "payment_terms_days": "14"},
    )
    assert res_sup_create.status_code == 200
    sup_id = res_sup_create.json()["supplier_id"]

    res_recv = await app_client.post(
        f"{base}/inventory/{prod.id}/receive",
        data={"quantity": "15", "supplier_id": str(sup_id), "unit_cost": "50.00", "note": "Morning intake"},
    )
    assert res_recv.status_code == 200
    assert "On Hand: 55" in res_recv.json()["detail"]

    # Support admin renders Customer Care workspace and cannot start order picking (Ops-only)
    app_client.cookies.set("access_token", sup_token)
    res_sup = await app_client.get(base)
    assert res_sup.status_code == 200
    assert 'data-admin-role="support"' in res_sup.text

    res_ops_forbid = await app_client.post(f"{base}/orders/1/start-picking")
    assert res_ops_forbid.status_code == 403

    # Operations admin sees Store Operations & Fleet Dispatch workspace
    app_client.cookies.set("access_token", ops_token)
    res_ops = await app_client.get(base)
    assert res_ops.status_code == 200
    assert 'data-admin-role="operations"' in res_ops.text
    assert "Dispatch, Fleet Routing &amp; Delivery Zones" in res_ops.text


@pytest.mark.asyncio
async def test_admin_order_picking_and_finance_maker_checker_refunds(
    app_client: AsyncClient, test_db_session: AsyncSession
):
    settings = get_settings()
    base = f"/{settings.admin_portal_path}/admin"
    _, customer, prod, _ = await _create_customer_and_product(test_db_session)
    _, _, ops_token = await _create_admin(test_db_session, suffix="ops2", level=AdminLevel.OPERATIONS)
    _, _, fin1_token = await _create_admin(test_db_session, suffix="fin1", level=AdminLevel.FINANCE)
    _, _, fin2_token = await _create_admin(test_db_session, suffix="fin2", level=AdminLevel.FINANCE)

    order = Order(
        order_number="ORD-TST-1001",
        customer_id=customer.id,
        status=OrderStatus.CONFIRMED,
        fulfilment_type=FulfilmentType.PICKUP,
        payment_method=PaymentMethod.MPESA,
        payment_status=OrderPaymentStatus.PAID,
        subtotal=Decimal("140.00"),
        tax_total=Decimal("0.00"),
        delivery_fee=Decimal("0.00"),
        discount_total=Decimal("0.00"),
        rounding_adjustment=Decimal("0.00"),
        total=Decimal("140.00"),
    )
    test_db_session.add(order)
    await test_db_session.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=prod.id,
        product_name=prod.name,
        sku=prod.sku,
        unit=prod.unit,
        tax_class=prod.tax_class,
        tax_rate=Decimal("0.00"),
        quantity=Decimal("2"),
        unit_price=Decimal("70.00"),
        line_total=Decimal("140.00"),
    )
    payment = Payment(
        order_id=order.id,
        channel=PaymentChannel.MPESA_STK,
        status=PaymentStatus.SUCCEEDED,
        amount=Decimal("140.00"),
        idempotency_key="pay-tst-1001",
        provider_receipt="TJ1234ABCD",
    )
    test_db_session.add_all([item, payment])
    await test_db_session.commit()
    await test_db_session.refresh(order)
    await test_db_session.refresh(item)
    await test_db_session.refresh(payment)

    # Operations admin without a Staff row can start picking and finish picking
    app_client.cookies.set("access_token", ops_token)
    r_start = await app_client.post(f"{base}/orders/{order.id}/start-picking")
    assert r_start.status_code == 200
    assert r_start.json()["status"] == "preparing"

    r_pick = await app_client.post(
        f"{base}/orders/{order.id}/items/{item.id}/pick",
        data={"pick_status": "picked", "quantity_picked": "2"},
    )
    assert r_pick.status_code == 200

    r_finish = await app_client.post(f"{base}/orders/{order.id}/finish-picking")
    assert r_finish.status_code == 200
    assert r_finish.json()["status"] == "ready"

    # Finance maker requests refund; same maker cannot self-approve; second finance approves & settles
    app_client.cookies.set("access_token", fin1_token)
    r_req = await app_client.post(
        f"{base}/finance/refunds",
        data={"payment_id": str(payment.id), "amount": "70.00", "reason": "Damaged carton"},
    )
    assert r_req.status_code == 200
    refund_id = r_req.json()["refund_id"]

    r_self_approve = await app_client.post(f"{base}/finance/refunds/{refund_id}/approve")
    assert r_self_approve.status_code == 403

    app_client.cookies.set("access_token", fin2_token)
    r_approve = await app_client.post(f"{base}/finance/refunds/{refund_id}/approve")
    assert r_approve.status_code == 200

    r_settle = await app_client.post(
        f"{base}/finance/refunds/{refund_id}/settle",
        data={"receipt": "REF-MPESA-991"},
    )
    assert r_settle.status_code == 200
    assert "REF-MPESA-991" in r_settle.json()["detail"]


@pytest.mark.asyncio
async def test_customer_wishlist_and_reviews_and_rider_wallet_cash_order(
    app_client: AsyncClient, test_db_session: AsyncSession
):
    settings = get_settings()
    _, customer, prod, cust_token = await _create_customer_and_product(test_db_session)

    # 1. Wishlist CRUD + batch sync
    headers = {"Authorization": f"Bearer {cust_token}"}
    r_empty = await app_client.get("/api/customer/wishlist", headers=headers)
    assert r_empty.status_code == 200
    assert r_empty.json() == []

    r_add = await app_client.post(f"/api/customer/wishlist/{prod.id}", headers=headers)
    assert r_add.status_code == 200
    assert len(r_add.json()) == 1
    assert r_add.json()[0]["id"] == prod.id

    r_del = await app_client.delete(f"/api/customer/wishlist/{prod.id}", headers=headers)
    assert r_del.status_code == 200
    assert r_del.json() == []

    r_sync = await app_client.post(
        "/api/customer/wishlist/sync",
        headers=headers,
        json={"product_ids": [prod.id]},
    )
    assert r_sync.status_code == 200
    assert [p["id"] for p in r_sync.json()] == [prod.id]

    # 2. Delivered CASH order + Rider
    rider_user = User(
        first_name="Brian",
        last_name="Kiprop",
        username="rider_brian",
        email="brian.rider@bansigo.store",
        phone="+254733445566",
        password_hash=await hash_password_async("RiderPass123!"),
        role=UserRole.RIDER,
        is_active=True,
        is_verified=True,
    )
    test_db_session.add(rider_user)
    await test_db_session.flush()

    rider = Rider(
        user_id=rider_user.id,
        national_id_number="30011223",
        licence_number="DL-99881",
        vehicle_type=VehicleType.MOTORCYCLE,
        vehicle_plate="KMEJ 441A",
        approval_status=ApprovalStatus.APPROVED,
        status=RiderStatus.AVAILABLE,
    )
    test_db_session.add(rider)
    await test_db_session.flush()

    order = Order(
        order_number="ORD-DLV-2002",
        customer_id=customer.id,
        status=OrderStatus.COMPLETED,
        fulfilment_type=FulfilmentType.DELIVERY,
        payment_method=PaymentMethod.CASH,
        payment_status=OrderPaymentStatus.PAID,
        subtotal=Decimal("140.00"),
        tax_total=Decimal("0.00"),
        delivery_fee=Decimal("120.00"),
        discount_total=Decimal("0.00"),
        rounding_adjustment=Decimal("0.00"),
        total=Decimal("260.00"),
        delivery_address_text="Posta Road, Migori",
        delivery_latitude=Decimal("-1.063000"),
        delivery_longitude=Decimal("34.475000"),
    )
    test_db_session.add(order)
    await test_db_session.flush()

    order_item = OrderItem(
        order_id=order.id,
        product_id=prod.id,
        product_name=prod.name,
        sku=prod.sku,
        unit=prod.unit,
        tax_class=prod.tax_class,
        tax_rate=Decimal("0.00"),
        quantity=Decimal("2"),
        unit_price=Decimal("70.00"),
        line_total=Decimal("140.00"),
    )
    delivery = Delivery(
        order_id=order.id,
        rider_id=rider.id,
        status=DeliveryStatus.DELIVERED,
        rider_fee=Decimal("84.00"),
        delivered_at=datetime.now(timezone.utc),
    )
    test_db_session.add_all([order_item, delivery])
    await test_db_session.commit()
    await test_db_session.refresh(order)
    await test_db_session.refresh(rider)

    # Verify RiderService.get_wallet handles PaymentMethod.CASH orders using order.total cleanly
    wallet = await RiderService(test_db_session).get_wallet(rider_user)
    assert wallet["cod_cash_in_hand"] == Decimal("260.00")
    assert wallet["total_earnings"] == Decimal("84.00")

    # 3. Order review status -> submit product review & rider delivery review
    r_status = await app_client.get(f"/api/customer/orders/{order.id}/reviews", headers=headers)
    assert r_status.status_code == 200
    status_data = r_status.json()
    assert status_data["can_review_delivery"] is True
    assert status_data["delivery_reviewed"] is False
    assert status_data["reviewable_products"][0]["product_id"] == prod.id

    r_prod_rev = await app_client.post(
        "/api/customer/reviews",
        headers=headers,
        json={
            "target_type": ReviewTargetType.PRODUCT.value,
            "product_id": prod.id,
            "order_id": order.id,
            "rating": 5,
            "comment": "Fresh and cold on arrival!",
        },
    )
    assert r_prod_rev.status_code == 201
    assert r_prod_rev.json()["rating"] == 5

    r_del_rev = await app_client.post(
        "/api/customer/reviews",
        headers=headers,
        json={
            "target_type": ReviewTargetType.DELIVERY.value,
            "order_id": order.id,
            "rider_id": rider.id,
            "rating": 4,
            "comment": "Fast and polite rider",
        },
    )
    assert r_del_rev.status_code == 201

    # Updating existing review for same order+product upserts in place (no duplicate row)
    r_upd = await app_client.post(
        "/api/customer/reviews",
        headers=headers,
        json={
            "target_type": ReviewTargetType.PRODUCT.value,
            "product_id": prod.id,
            "order_id": order.id,
            "rating": 4,
            "comment": "Updated comment",
        },
    )
    assert r_upd.status_code == 201
    assert r_upd.json()["rating"] == 4
    assert r_upd.json()["comment"] == "Updated comment"

    # Check product reviews endpoint & rider reviews endpoint + Rider rating recalculation
    r_prod_list = await app_client.get(f"/api/customer/products/{prod.id}/reviews")
    assert r_prod_list.status_code == 200
    assert r_prod_list.json()["total_reviews"] == 1
    assert float(r_prod_list.json()["average_rating"]) == 4.0

    rider_token = create_access_token(
        rider_user.id, settings.secret_key.get_secret_value(), expires_minutes=60
    )
    r_rider_reviews = await app_client.get(
        "/api/rider/reviews",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert r_rider_reviews.status_code == 200
    assert r_rider_reviews.json()["rating_count"] == 1
    assert float(r_rider_reviews.json()["average_rating"]) == 4.0

    refreshed_rider = (
        await test_db_session.execute(select(Rider).where(Rider.id == rider.id))
    ).scalar_one()
    assert refreshed_rider.rating_count == 1
    assert float(refreshed_rider.rating_average) == 4.0
