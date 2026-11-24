# tests/test_order_delivery_lifecycle.py

from datetime import date, timedelta
from decimal import Decimal
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from src import create_app
from src.database import Base, get_db
from src.models import (
    Address,
    ApprovalStatus,
    Category,
    Customer,
    Delivery,
    DeliveryStatus,
    DeliveryZone,
    Inventory,
    Order,
    OrderStatus,
    Payment,
    PaymentChannel,
    PaymentMethod,
    PaymentStatus,
    Product,
    Rider,
    RiderStatus,
    TaxClass,
    UnitType,
    User,
    UserRole,
    VehicleType,
)
from src.security import create_access_token, hash_password_async, make_handover_code, make_pickup_code
from src.services.delivery_service import DeliveryService
from utilities import utc_now


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _seed_customer_and_product(db: AsyncSession):
    pwd = await hash_password_async("Secret123!")
    c_user = User(
        first_name="Amina",
        last_name="Ochieng",
        username=f"cust_{uuid.uuid4().hex[:6]}",
        email=f"cust_{uuid.uuid4().hex[:6]}@test.com",
        phone="+254711100200",
        password_hash=pwd,
        role=UserRole.CUSTOMER,
        is_active=True,
        is_verified=True,
    )
    db.add(c_user)
    await db.flush()
    customer = Customer(user_id=c_user.id)
    db.add(customer)

    cat = Category(name="Groceries", slug=f"groceries-{uuid.uuid4().hex[:4]}", is_active=True)
    db.add(cat)
    await db.flush()

    prod = Product(
        category_id=cat.id,
        sku=f"SKU-{uuid.uuid4().hex[:6]}",
        name="Fresh Tomatoes 1kg",
        slug=f"tomatoes-{uuid.uuid4().hex[:6]}",
        price=Decimal("120.00"),
        unit=UnitType.KG,
        tax_class=TaxClass.EXEMPT,
        is_active=True,
    )
    db.add(prod)
    await db.flush()
    db.add(Inventory(product_id=prod.id, quantity_on_hand=Decimal("100.00"), quantity_reserved=Decimal("0.00")))

    zone = DeliveryZone(
        name=f"Migori Central {uuid.uuid4().hex[:4]}",
        delivery_fee=Decimal("50.00"),
        min_order_amount=Decimal("50.00"),
        estimated_minutes=20,
        is_active=True,
        created_by=c_user.id,
        updated_by=c_user.id,
    )
    db.add(zone)
    await db.flush()

    settings = get_settings()
    s_lat = Decimal(str(round(float(settings.supermarket_latitude) + 0.012, 6)))
    s_lon = Decimal(str(round(float(settings.supermarket_longitude) + 0.008, 6)))

    address = Address(
        customer_id=customer.id,
        zone_id=zone.id,
        label="Home",
        recipient_name="Amina Ochieng",
        recipient_phone="+254711100200",
        area="Wasweta 1",
        street_address="Migori Town Road",
        latitude=s_lat,
        longitude=s_lon,
        is_default=True,
    )
    db.add(address)
    await db.flush()
    return c_user, customer, prod, address


async def _seed_rider(db: AsyncSession, *, lat: Decimal, lon: Decimal, plate_suffix: str) -> tuple[User, Rider]:
    pwd = await hash_password_async("Rider123!")
    r_user = User(
        first_name="Rider",
        last_name=plate_suffix,
        username=f"rider_{plate_suffix}_{uuid.uuid4().hex[:4]}",
        email=f"rider_{plate_suffix}_{uuid.uuid4().hex[:4]}@test.com",
        phone=f"+254722{plate_suffix[:6].ljust(6, '0')}",
        password_hash=pwd,
        role=UserRole.RIDER,
        is_active=True,
        is_verified=True,
    )
    db.add(r_user)
    await db.flush()
    rider = Rider(
        user_id=r_user.id,
        approval_status=ApprovalStatus.APPROVED,
        status=RiderStatus.AVAILABLE,
        vehicle_type=VehicleType.MOTORCYCLE,
        vehicle_plate=f"KM{plate_suffix[:4]}X",
        licence_number=f"DL-{plate_suffix}",
        licence_expiry=date.today() + timedelta(days=365),
        last_latitude=lat,
        last_longitude=lon,
        last_seen_at=utc_now(),
    )
    db.add(rider)
    await db.flush()
    return r_user, rider


@pytest.mark.asyncio
async def test_full_payment_autodispatch_pickup_code_tracking_and_handover(client: AsyncClient, db_session: AsyncSession):
    settings = get_settings()
    secret = settings.secret_key.get_secret_value()

    c_user, customer, prod, address = await _seed_customer_and_product(db_session)
    r_user, rider = await _seed_rider(
        db_session,
        lat=settings.supermarket_latitude,
        lon=settings.supermarket_longitude,
        plate_suffix="101A",
    )
    await db_session.commit()

    cust_headers = {"Authorization": f"Bearer {create_access_token(c_user.id, secret, 60)}"}
    rider_headers = {"Authorization": f"Bearer {create_access_token(r_user.id, secret, 60)}"}

    # 1. Checkout -> delivery_fee is dynamically calculated (> 50 for >1km distance)
    co_resp = await client.post(
        "/api/customer/orders/checkout",
        json={
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"product_id": prod.id, "quantity": 2}],
            "address_id": address.id,
            "fulfilment_type": "delivery",
            "payment_method": "mpesa",
        },
        headers=cust_headers,
    )
    assert co_resp.status_code == 201
    order_data = co_resp.json()
    order_id = order_data["id"]
    assert Decimal(order_data["delivery_fee"]) >= Decimal("50")

    # 2. Simulate pending STK payment and Daraja STK callback through /api/payments/mpesa/stk-callback
    checkout_req_id = f"ws_CO_TEST_{uuid.uuid4().hex[:8]}"
    payment = Payment(
        order_id=order_id,
        initiated_by=c_user.id,
        channel=PaymentChannel.MPESA_STK,
        status=PaymentStatus.PENDING,
        amount=Decimal(order_data["total"]),
        idempotency_key=f"stk-{uuid.uuid4().hex[:8]}",
        payer_phone="+254711100200",
        provider_checkout_request_id=checkout_req_id,
        expires_at=utc_now() + timedelta(seconds=90),
    )
    db_session.add(payment)
    await db_session.commit()

    cb_payload = {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "MR-1001",
                "CheckoutRequestID": checkout_req_id,
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": float(order_data["total"])},
                        {"Name": "MpesaReceiptNumber", "Value": f"UC{uuid.uuid4().hex[:8].upper()}"},
                        {"Name": "TransactionDate", "Value": 20261124183000},
                        {"Name": "PhoneNumber", "Value": 254711100200},
                    ]
                },
            }
        }
    }
    cb_resp = await client.post("/api/payments/mpesa/stk-callback", json=cb_payload)
    assert cb_resp.status_code == 200
    assert cb_resp.json()["ResultCode"] == 0

    # Payment status endpoint returns succeeded & order was auto-dispatched to rider
    ps_resp = await client.get(f"/api/customer/orders/{order_id}/payment-status?query_daraja=false", headers=cust_headers)
    assert ps_resp.status_code == 200
    assert ps_resp.json()["status"] == "succeeded"

    active_resp = await client.get("/api/rider/deliveries/active", headers=rider_headers)
    assert active_resp.status_code == 200
    deliveries = active_resp.json()
    assert len(deliveries) == 1
    delivery_id = deliveries[0]["id"]
    assert deliveries[0]["status"] == "assigned"

    # 3. Rider accepts offer -> pickup code notification generated
    acc_resp = await client.post(
        f"/api/rider/deliveries/{delivery_id}/respond",
        json={"accept": True},
        headers=rider_headers,
    )
    assert acc_resp.status_code == 200
    assert acc_resp.json()["status"] == "accepted"

    notif_resp = await client.get("/api/rider/notifications", headers=rider_headers)
    assert notif_resp.status_code == 200
    pickup_notifs = [n for n in notif_resp.json()["items"] if n["type"] == "pickup_code"]
    assert len(pickup_notifs) == 1

    pickup_code = make_pickup_code(secret, delivery_id, settings.pickup_code_length)
    handover_code = make_handover_code(secret, delivery_id, settings.handover_code_length)
    assert pickup_code != handover_code
    assert pickup_code in pickup_notifs[0]["title"]

    # Wrong pickup code fails
    bad_pick = await client.post(
        f"/api/rider/deliveries/{delivery_id}/pickup",
        json={"pickup_code": "0000" if pickup_code != "0000" else "9999"},
        headers=rider_headers,
    )
    assert bad_pick.status_code in (400, 422)

    # Correct pickup code transitions delivery -> picked_up & order -> out_for_delivery
    good_pick = await client.post(
        f"/api/rider/deliveries/{delivery_id}/pickup",
        json={"pickup_code": pickup_code},
        headers=rider_headers,
    )
    assert good_pick.status_code == 200
    assert good_pick.json()["status"] == "picked_up"

    # Rider GPS ping reflects in customer tracking + separate handover PIN shown to customer
    await client.post(
        "/api/rider/location",
        json={"latitude": float(address.latitude), "longitude": float(address.longitude)},
        headers=rider_headers,
    )
    track_resp = await client.get(f"/api/customer/orders/{order_id}/tracking", headers=cust_headers)
    assert track_resp.status_code == 200
    track_data = track_resp.json()
    assert track_data["order_status"] == "out_for_delivery"
    assert track_data["handover_code"] == handover_code
    assert track_data["rider_location"]["latitude"] == pytest.approx(float(address.latitude), abs=1e-5)

    # Arrive + complete with separate customer handover PIN
    arr_resp = await client.post(f"/api/rider/deliveries/{delivery_id}/arrive", headers=rider_headers)
    assert arr_resp.status_code == 200

    comp_resp = await client.post(
        f"/api/rider/deliveries/{delivery_id}/complete",
        json={"handover_code": handover_code},
        headers=rider_headers,
    )
    assert comp_resp.status_code == 200
    assert comp_resp.json()["status"] == "delivered"


@pytest.mark.asyncio
async def test_rejection_consequences_redistribution_and_manual_fallback(client: AsyncClient, db_session: AsyncSession):
    settings = get_settings()
    secret = settings.secret_key.get_secret_value()

    c_user, customer, prod, address = await _seed_customer_and_product(db_session)
    r1_user, r1 = await _seed_rider(
        db_session, lat=settings.supermarket_latitude, lon=settings.supermarket_longitude, plate_suffix="201B"
    )
    r2_user, r2 = await _seed_rider(
        db_session,
        lat=settings.supermarket_latitude + Decimal("0.005"),
        lon=settings.supermarket_longitude,
        plate_suffix="202C",
    )
    await db_session.commit()

    cust_headers = {"Authorization": f"Bearer {create_access_token(c_user.id, secret, 60)}"}
    r1_headers = {"Authorization": f"Bearer {create_access_token(r1_user.id, secret, 60)}"}
    r2_headers = {"Authorization": f"Bearer {create_access_token(r2_user.id, secret, 60)}"}

    # Cash checkout triggers immediate auto-dispatch to closest rider r1
    co_resp = await client.post(
        "/api/customer/orders/checkout",
        json={
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"product_id": prod.id, "quantity": 1}],
            "address_id": address.id,
            "fulfilment_type": "delivery",
            "payment_method": "cash",
        },
        headers=cust_headers,
    )
    assert co_resp.status_code == 201

    r1_active = (await client.get("/api/rider/deliveries/active", headers=r1_headers)).json()
    assert len(r1_active) == 1
    delivery_id = r1_active[0]["id"]

    # r1 rejects WITHOUT justification -> penalized & delivery auto-reassigned to next best rider r2!
    rej1 = await client.post(
        f"/api/rider/deliveries/{delivery_id}/respond",
        json={"accept": False},
        headers=r1_headers,
    )
    assert rej1.status_code == 200

    r1_prof = (await client.get("/api/rider/profile", headers=r1_headers)).json()
    assert r1_prof["unjustified_rejections_count"] == 1
    assert r1_prof["penalty_points"] == 10

    r2_active = (await client.get("/api/rider/deliveries/active", headers=r2_headers)).json()
    assert len(r2_active) == 1
    assert r2_active[0]["id"] == delivery_id

    # r2 rejects WITH valid justification -> no penalty points, and since no more riders exist, falls back to manual assignment!
    rej2 = await client.post(
        f"/api/rider/deliveries/{delivery_id}/respond",
        json={"accept": False, "reason_code": "vehicle_breakdown", "reason_text": "Rear tyre puncture"},
        headers=r2_headers,
    )
    assert rej2.status_code == 200
    rej2_data = rej2.json()
    assert rej2_data["status"] == "unassigned"
    assert rej2_data["needs_manual_assignment"] is True

    r2_prof = (await client.get("/api/rider/profile", headers=r2_headers)).json()
    assert r2_prof["unjustified_rejections_count"] == 0
    assert r2_prof["penalty_points"] == 0


@pytest.mark.asyncio
async def test_multi_order_batching_and_overdue_sla_sweeper(client: AsyncClient, db_session: AsyncSession):
    settings = get_settings()
    secret = settings.secret_key.get_secret_value()

    c_user, customer, prod, address = await _seed_customer_and_product(db_session)
    r_user, rider = await _seed_rider(
        db_session, lat=settings.supermarket_latitude, lon=settings.supermarket_longitude, plate_suffix="303D"
    )
    await db_session.commit()

    cust_headers = {"Authorization": f"Bearer {create_access_token(c_user.id, secret, 60)}"}
    rider_headers = {"Authorization": f"Bearer {create_access_token(r_user.id, secret, 60)}"}

    # Place 2 cash orders -> both batch onto the same rider (within max_active_deliveries=3)
    for _ in range(2):
        resp = await client.post(
            "/api/customer/orders/checkout",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "items": [{"product_id": prod.id, "quantity": 1}],
                "address_id": address.id,
                "fulfilment_type": "delivery",
                "payment_method": "cash",
            },
            headers=cust_headers,
        )
        assert resp.status_code == 201

    active = (await client.get("/api/rider/deliveries/active", headers=rider_headers)).json()
    assert len(active) == 2

    # Force overdue transit on first delivery and run SLA sweeper
    d0 = await db_session.get(Delivery, active[0]["id"])
    d0.status = DeliveryStatus.PICKED_UP
    d0.picked_up_at = utc_now() - timedelta(minutes=90)
    d0.delivery_due_at = utc_now() - timedelta(minutes=30)
    await db_session.commit()

    svc = DeliveryService(db_session, settings)
    stats = await svc.sweep_delivery_timers()
    assert stats["overdue_deliveries"] >= 1

    r_prof = (await client.get("/api/rider/profile", headers=rider_headers)).json()
    assert r_prof["overdue_deliveries_count"] >= 1
    assert r_prof["penalty_points"] >= 15
