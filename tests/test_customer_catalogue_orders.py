# tests/test_customer_catalogue_orders.py

import uuid
from decimal import Decimal
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from src import create_app
from src.database import Base, get_db
from src.models import (
    Address,
    Category,
    Customer,
    DeliveryZone,
    Inventory,
    Product,
    TaxClass,
    UnitType,
    User,
    UserRole,
)
from src.security import create_access_token, hash_password_async


@pytest_asyncio.fixture
async def test_db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_customer_catalogue_and_orders(test_db_session):
    app = create_app()
    settings = get_settings()

    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    # Create customer user
    hashed_pwd = await hash_password_async("Password123!")
    user = User(
        first_name="Catalogue",
        last_name="Tester",
        username="cataloguetester",
        email="customer.order@test.com",
        phone="+254711999888",
        password_hash=hashed_pwd,
        role=UserRole.CUSTOMER,
        is_active=True,
        is_verified=True,
    )
    test_db_session.add(user)
    await test_db_session.flush()

    customer = Customer(user_id=user.id)
    test_db_session.add(customer)
    await test_db_session.flush()

    # Create test category
    cat = Category(
        name="Dairy Products",
        slug="dairy-products",
        is_active=True,
    )
    test_db_session.add(cat)
    await test_db_session.flush()

    # Create test product
    product = Product(
        category_id=cat.id,
        sku="TEST-MILK-1",
        name="Arla DANO Full Cream Milk Powder Instant",
        slug="test-arla-dano-milk",
        description="Fresh whole milk powder rich in vitamins and calcium.",
        pack_size_label="1 KG",
        price=Decimal("182.00"),
        compare_at_price=Decimal("220.00"),
        unit=UnitType.PIECE,
        tax_class=TaxClass.STANDARD,
        is_active=True,
    )
    test_db_session.add(product)
    await test_db_session.flush()

    inventory = Inventory(
        product_id=product.id,
        quantity_on_hand=Decimal("50.00"),
        quantity_reserved=Decimal("0.00"),
    )
    test_db_session.add(inventory)

    zone = DeliveryZone(
        name="CBD / Upper Hill Zone",
        delivery_fee=Decimal("50.00"),
        min_order_amount=Decimal("100.00"),
        estimated_minutes=25,
        is_active=True,
        created_by=user.id,
        updated_by=user.id,
    )
    test_db_session.add(zone)
    await test_db_session.flush()

    address = Address(
        customer_id=customer.id,
        zone_id=zone.id,
        label="Home",
        recipient_name="Catalogue Tester",
        recipient_phone="+254711999888",
        area="Upper Hill",
        street_address="Kenyatta Ave, Migori",
        latitude=Decimal("-1.286389"),
        longitude=Decimal("36.817222"),
        is_default=True,
    )
    test_db_session.add(address)
    await test_db_session.commit()

    token = create_access_token(user.id, settings.secret_key.get_secret_value(), expires_minutes=60)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test categories
        cat_resp = await client.get("/api/customer/categories")
        assert cat_resp.status_code == 200

        # Test products listing
        prod_resp = await client.get("/api/customer/products")
        assert prod_resp.status_code == 200
        data = prod_resp.json()
        assert "items" in data
        assert len(data["items"]) >= 1

        # Test single product detail
        detail_resp = await client.get(f"/api/customer/products/{product.id}")
        assert detail_resp.status_code == 200
        p_json = detail_resp.json()
        assert p_json["name"] == "Arla DANO Full Cream Milk Powder Instant"
        assert p_json["pack_size_label"] == "1 KG"

        # Test related products
        related_resp = await client.get(f"/api/customer/products/{product.id}/related")
        assert related_resp.status_code == 200

        # Test orders list (authenticated)
        orders_resp = await client.get(
            "/api/customer/orders?tab=ongoing",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert orders_resp.status_code == 200
        orders_data = orders_resp.json()
        assert "items" in orders_data
        assert orders_data["total"] == 0

        # Test checkout
        checkout_payload = {
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"product_id": product.id, "quantity": 2}],
            "address_id": address.id,
            "customer_note": "Call on arrival",
            "fulfilment_type": "delivery",
            "payment_method": "mpesa",
        }
        checkout_resp = await client.post(
            "/api/customer/orders/checkout",
            json=checkout_payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert checkout_resp.status_code == 201
        order_json = checkout_resp.json()
        order_id = order_json["id"]
        assert order_json["status"] == "pending_payment"

        # Test Mpesa STK prompt initiation
        stk_key = str(uuid.uuid4())
        stk_resp = await client.post(
            f"/api/customer/orders/{order_id}/pay/mpesa",
            json={
                "idempotency_key": stk_key,
                "phone": "+254711999888",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert stk_resp.status_code == 200
        stk_data = stk_resp.json()
        assert stk_data["status"] == "pending"
        assert stk_data["order_id"] == order_id
        assert stk_data["created_at"] is not None

        # Test prompt resend / retry with identical idempotency key returns same attempt with valid created_at
        retry_resp = await client.post(
            f"/api/customer/orders/{order_id}/pay/mpesa",
            json={
                "idempotency_key": stk_key,
                "phone": "+254711999888",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert retry_resp.status_code == 200
        retry_data = retry_resp.json()
        assert retry_data["id"] == stk_data["id"]
        assert retry_data["created_at"] is not None

        # Test manual Mpesa receipt entry fallback
        manual_resp = await client.post(
            f"/api/customer/orders/{order_id}/pay/manual",
            json={"transaction_code": "QA12345678"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert manual_resp.status_code == 200
        manual_data = manual_resp.json()
        assert manual_data["status"] == "confirmed"

        # Test payment status endpoint
        status_resp = await client.get(
            f"/api/customer/orders/{order_id}/payment-status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["order_id"] == order_id
        assert "status" in status_data


@pytest.mark.asyncio
async def test_unverified_customer_cannot_place_order(test_db_session):
    app = create_app()

    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    hashed_pwd = await hash_password_async("Password123!")
    unverified_user = User(
        first_name="Unverified",
        last_name="Shopper",
        username="unverifiedshopper",
        email="unverified@test.com",
        phone="+254711000111",
        password_hash=hashed_pwd,
        role=UserRole.CUSTOMER,
        is_active=True,
        is_verified=False,
    )
    test_db_session.add(unverified_user)
    await test_db_session.flush()

    customer = Customer(user_id=unverified_user.id)
    test_db_session.add(customer)
    await test_db_session.flush()

    # Product
    cat = Category(name="Snacks", slug="snacks-test", is_active=True)
    test_db_session.add(cat)
    await test_db_session.flush()

    product = Product(
        category_id=cat.id,
        name="Potato Crisps",
        slug="potato-crisps",
        sku="SNK-001",
        price=Decimal("120.00"),
        unit=UnitType.PIECE,
        tax_class=TaxClass.STANDARD,
        is_active=True,
    )
    test_db_session.add(product)
    await test_db_session.flush()

    inventory = Inventory(
        product_id=product.id,
        quantity_on_hand=Decimal("100"),
        quantity_reserved=Decimal("0.00"),
    )
    test_db_session.add(inventory)
    await test_db_session.flush()

    zone = DeliveryZone(
        name="Migori Town Unverified",
        delivery_fee=Decimal("50.00"),
        min_order_amount=Decimal("100.00"),
        estimated_minutes=20,
        is_active=True,
        created_by=unverified_user.id,
        updated_by=unverified_user.id,
    )
    test_db_session.add(zone)
    await test_db_session.flush()

    address = Address(
        customer_id=customer.id,
        zone_id=zone.id,
        label="Home",
        recipient_name="Unverified Shopper",
        recipient_phone="+254711000111",
        area="Kakrao",
        street_address="Kakrao",
        latitude=Decimal("-1.061219"),
        longitude=Decimal("34.474196"),
        is_default=True,
    )
    test_db_session.add(address)
    await test_db_session.commit()

    settings = get_settings()
    token = create_access_token(unverified_user.id, settings.secret_key.get_secret_value(), expires_minutes=60)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        checkout_resp = await client.post(
            "/api/customer/orders/checkout",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "items": [{"product_id": product.id, "quantity": 1}],
                "fulfilment_type": "delivery",
                "payment_method": "mpesa",
                "address_id": address.id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert checkout_resp.status_code == 403
        assert "verification is required" in checkout_resp.json()["detail"].lower()
