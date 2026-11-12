# tests/test_customer_addresses.py

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
    Customer,
    DeliveryZone,
    User,
    UserRole,
)
from src.security import create_access_token, hash_password_async


@pytest_asyncio.fixture
async def test_db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session


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
async def test_customer_addresses_crud(app_client: AsyncClient, test_db_session: AsyncSession):
    settings = get_settings()

    # 1. Create customer user & customer profile
    c_user = User(
        first_name="Jane",
        last_name="Doe",
        username="jane_addresses",
        phone="+254711999888",
        email="jane.address@example.com",
        role=UserRole.CUSTOMER,
        password_hash=await hash_password_async("Pass123!"),
        is_verified=True,
    )
    test_db_session.add(c_user)
    await test_db_session.flush()

    customer = Customer(user_id=c_user.id)
    test_db_session.add(customer)

    # 2. Create active delivery zone
    zone = DeliveryZone(
        name="CBD / Upper Hill Zone",
        delivery_fee=Decimal("60.00"),
        min_order_amount=Decimal("500.00"),
        estimated_minutes=25,
        is_active=True,
        created_by=c_user.id,
        updated_by=c_user.id,
    )
    test_db_session.add(zone)
    await test_db_session.commit()

    token = create_access_token(c_user.id, settings.secret_key.get_secret_value(), expires_minutes=60)
    headers = {"Authorization": f"Bearer {token}"}

    # 3. List zones
    resp_zones = await app_client.get("/api/customer/zones")
    assert resp_zones.status_code == 200
    zones_data = resp_zones.json()
    assert len(zones_data) >= 1
    assert zones_data[0]["name"] == "CBD / Upper Hill Zone"

    # 4. List addresses initially empty
    resp_empty = await app_client.get("/api/customer/addresses", headers=headers)
    assert resp_empty.status_code == 200
    assert resp_empty.json() == []

    # 5. Create new address
    new_addr = {
        "label": "Home",
        "recipient_name": "Jane Doe",
        "recipient_phone": "+254711999888",
        "zone_id": zone.id,
        "area": "Upper Hill",
        "street_address": "Kilimani Road, Apt 4B",
        "landmark": "Near Rahimtulla Tower",
        "directions": "Gate 2, ring bell 4B",
        "latitude": -1.295000,
        "longitude": 36.815000,
        "is_default": True,
    }
    resp_create = await app_client.post("/api/customer/addresses", json=new_addr, headers=headers)
    assert resp_create.status_code == 201
    created_data = resp_create.json()
    assert created_data["label"] == "Home"
    assert created_data["area"] == "Upper Hill"
    assert created_data["is_default"] is True
    addr_id = created_data["id"]

    # 6. Get single address
    resp_get = await app_client.get(f"/api/customer/addresses/{addr_id}", headers=headers)
    assert resp_get.status_code == 200
    assert resp_get.json()["id"] == addr_id

    # 7. Update address
    update_data = {
        "label": "Work Office",
        "landmark": "Opposite City Hall",
    }
    resp_update = await app_client.patch(f"/api/customer/addresses/{addr_id}", json=update_data, headers=headers)
    assert resp_update.status_code == 200
    assert resp_update.json()["label"] == "Work Office"
    assert resp_update.json()["landmark"] == "Opposite City Hall"

    # 8. Delete address
    resp_delete = await app_client.delete(f"/api/customer/addresses/{addr_id}", headers=headers)
    assert resp_delete.status_code == 204

    # 9. Verify deleted
    resp_after = await app_client.get("/api/customer/addresses", headers=headers)
    assert resp_after.status_code == 200
    assert resp_after.json() == []
