# tests/test_recommendations.py

import pytest
import pytest_asyncio
from decimal import Decimal
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src import create_app
from src.database import Base, get_db
from src.models import (
    Brand,
    Category,
    Customer,
    FulfilmentType,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    TaxClass,
    UnitType,
    User,
    UserRole,
)
from src.security import hash_password_async


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
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_recommendations_and_tracking(app_client: AsyncClient, test_db_session: AsyncSession):
    # 1. Seed brand, category, products
    brand = Brand(name="Fresh Farms", slug="fresh-farms")
    category = Category(name="Groceries", slug="groceries")
    test_db_session.add_all([brand, category])
    await test_db_session.flush()

    p1 = Product(name="Fresh Milk 500ml", slug="fresh-milk-500ml", sku="MILK-01", price=Decimal("60.00"), unit=UnitType.PIECE, tax_class=TaxClass.ZERO_RATED, is_active=True, brand_id=brand.id, category_id=category.id)
    p2 = Product(name="Brown Bread 400g", slug="brown-bread-400g", sku="BREAD-01", price=Decimal("70.00"), unit=UnitType.PIECE, tax_class=TaxClass.ZERO_RATED, is_active=True, brand_id=brand.id, category_id=category.id)
    p3 = Product(name="Eggs 6 Pack", slug="eggs-6-pack", sku="EGGS-01", price=Decimal("120.00"), unit=UnitType.PIECE, tax_class=TaxClass.ZERO_RATED, is_active=True, brand_id=brand.id, category_id=category.id)
    p4 = Product(name="Butter 250g", slug="butter-250g", sku="BUTTER-01", price=Decimal("180.00"), unit=UnitType.PIECE, tax_class=TaxClass.STANDARD, is_active=True, brand_id=brand.id, category_id=category.id)
    test_db_session.add_all([p1, p2, p3, p4])
    await test_db_session.flush()

    # 2. Seed Customer and Orders with co-purchased items (Bread + Milk + Butter)
    u = User(username="janecustomer", first_name="Jane", last_name="Customer", email="jane@example.com", phone="+254711999888", role=UserRole.CUSTOMER, password_hash=await hash_password_async("pass123"))
    test_db_session.add(u)
    await test_db_session.flush()
    c = Customer(user_id=u.id)
    test_db_session.add(c)
    await test_db_session.flush()

    # Order 1: Milk & Bread
    o1 = Order(customer_id=c.id, order_number="ORD-001", status=OrderStatus.CONFIRMED, fulfilment_type=FulfilmentType.PICKUP, subtotal=Decimal("130.00"), tax_total=Decimal("0"), total=Decimal("130.00"))
    test_db_session.add(o1)
    await test_db_session.flush()
    test_db_session.add_all([
        OrderItem(order_id=o1.id, product_id=p1.id, product_name=p1.name, sku=p1.sku, unit=p1.unit, unit_price=p1.price, tax_class=p1.tax_class, tax_rate=Decimal("0"), quantity=Decimal("1"), line_total=Decimal("60.00")),
        OrderItem(order_id=o1.id, product_id=p2.id, product_name=p2.name, sku=p2.sku, unit=p2.unit, unit_price=p2.price, tax_class=p2.tax_class, tax_rate=Decimal("0"), quantity=Decimal("1"), line_total=Decimal("70.00")),
    ])

    # Order 2: Milk & Bread & Butter
    o2 = Order(customer_id=c.id, order_number="ORD-002", status=OrderStatus.COMPLETED, fulfilment_type=FulfilmentType.PICKUP, subtotal=Decimal("310.00"), tax_total=Decimal("0"), total=Decimal("310.00"))
    test_db_session.add(o2)
    await test_db_session.flush()
    test_db_session.add_all([
        OrderItem(order_id=o2.id, product_id=p1.id, product_name=p1.name, sku=p1.sku, unit=p1.unit, unit_price=p1.price, tax_class=p1.tax_class, tax_rate=Decimal("0"), quantity=Decimal("1"), line_total=Decimal("60.00")),
        OrderItem(order_id=o2.id, product_id=p2.id, product_name=p2.name, sku=p2.sku, unit=p2.unit, unit_price=p2.price, tax_class=p2.tax_class, tax_rate=Decimal("0"), quantity=Decimal("1"), line_total=Decimal("70.00")),
        OrderItem(order_id=o2.id, product_id=p4.id, product_name=p4.name, sku=p4.sku, unit=p4.unit, unit_price=p4.price, tax_class=p4.tax_class, tax_rate=Decimal("16"), quantity=Decimal("1"), line_total=Decimal("180.00")),
    ])
    await test_db_session.commit()

    # 3. Test GET recommendations (server selects algorithm randomly)
    res = await app_client.get("/api/customer/recommendations?limit=4")
    assert res.status_code == 200
    data = res.json()
    assert len(data) > 0
    first_item = data[0]
    assert first_item["algorithm"] in ("apriori", "fpgrowth")
    assert "product" in first_item
    assert "recommendation_tag" in first_item

    # Test explicit algorithm query
    res_apriori = await app_client.get("/api/customer/recommendations?algorithm=apriori&limit=4")
    assert res_apriori.status_code == 200
    assert all(r["algorithm"] == "apriori" for r in res_apriori.json())

    res_fp = await app_client.get("/api/customer/recommendations?algorithm=fpgrowth&limit=4")
    assert res_fp.status_code == 200
    assert all(r["algorithm"] == "fpgrowth" for r in res_fp.json())

    # 4. Test Track recommendation events (impression, click, add_to_cart, helpfulness)
    track_payload = {
        "product_id": p2.id,
        "algorithm": "apriori",
        "event_type": "impression",
        "context": "home",
    }
    t_res = await app_client.post("/api/customer/recommendations/track", json=track_payload)
    assert t_res.status_code == 201
    assert t_res.json()["success"] is True

    # Track click
    await app_client.post("/api/customer/recommendations/track", json={
        "product_id": p2.id,
        "algorithm": "apriori",
        "event_type": "click",
        "context": "home",
    })

    # Track helpful feedback
    await app_client.post("/api/customer/recommendations/track", json={
        "product_id": p2.id,
        "algorithm": "apriori",
        "event_type": "helpful",
        "rating": 5,
        "feedback_text": "Great cross-sell suggestion!",
    })

    # Track fpgrowth impression and cart add
    await app_client.post("/api/customer/recommendations/track", json={
        "product_id": p4.id,
        "algorithm": "fpgrowth",
        "event_type": "impression",
        "context": "cart",
    })
    await app_client.post("/api/customer/recommendations/track", json={
        "product_id": p4.id,
        "algorithm": "fpgrowth",
        "event_type": "add_to_cart",
        "context": "cart",
    })

    # 5. Check recommendation stats
    stats_res = await app_client.get("/api/customer/recommendations/stats")
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert stats["total_events"] > 0
    assert stats["apriori"]["impressions"] >= 1
    assert stats["apriori"]["clicks"] >= 1
    assert stats["fpgrowth"]["cart_adds"] >= 1
    assert stats["apriori"]["avg_rating"] == 5.0
