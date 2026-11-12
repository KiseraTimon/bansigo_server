# tests/test_customer_notifications.py

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src import create_app
from src.database import Base, get_db


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
async def test_customer_notifications(test_db_session):
    app = create_app()

    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Fetch notifications
        res = await client.get("/api/customer/notifications")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert data["total"] >= 1
        assert "unread_count" in data

        first_id = data["items"][0]["id"]

        # 2. Mark single notification as read
        read_res = await client.patch(f"/api/customer/notifications/{first_id}/read")
        assert read_res.status_code == 200
        assert read_res.json()["is_read"] is True

        # 3. Mark all as read
        read_all_res = await client.post("/api/customer/notifications/read-all")
        assert read_all_res.status_code == 200
        assert read_all_res.json()["status"] == "success"
