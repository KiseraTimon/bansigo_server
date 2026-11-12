# tests/test_auth_social.py

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src import create_app
from src.database import Base, get_db
from src.models import Customer, User, UserRole
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
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_firebase_config_endpoint(app_client: AsyncClient):
    """
    verifies that GET /api/auth/firebase/config returns public configuration for client initialization.
    """
    res = await app_client.get("/api/auth/firebase/config")
    assert res.status_code == 200
    data = res.json()
    assert data["project_id"] == "bansigo-customer"
    assert data["auth_domain"] == "bansigo-customer.firebaseapp.com"
    assert "apiKey" in data or "api_key" in data


@pytest.mark.asyncio
async def test_social_auth_new_user_without_phone(app_client: AsyncClient):
    """
    verifies that a new user signing in via Google/Firebase is registered smoothly,
    receives a JWT access token, has their email pre-verified, but is flagged as requires_phone=True.
    """
    token_str = "test_token_googleuid123_jane.doe@example.com"
    res = await app_client.post("/api/auth/social", json={
        "provider": "google",
        "token": token_str
    })
    assert res.status_code == 200
    data = res.json()
    assert data["is_new_user"] is True
    assert data["requires_phone"] is True
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    user = data["user"]
    assert user["email"] == "jane.doe@example.com"
    assert user["first_name"] == "Test"
    assert user["last_name"] == "SocialUser"
    assert user["is_verified"] is True
    assert user["phone"] is None


@pytest.mark.asyncio
async def test_complete_phone_flow(app_client: AsyncClient):
    """
    verifies the progressive onboarding flow:
    1. Social login registers user without phone
    2. User completes phone via /complete-phone endpoint
    3. User profile reflects complete status
    """
    # 1. Social register
    token_str = "test_token_uid456_peter.pan@example.com"
    auth_res = await app_client.post("/api/auth/social", json={
        "provider": "firebase",
        "token": token_str
    })
    assert auth_res.status_code == 200
    auth_data = auth_res.json()
    access_token = auth_data["access_token"]
    assert auth_data["requires_phone"] is True

    # 2. Complete phone
    headers = {"Authorization": f"Bearer {access_token}"}
    complete_res = await app_client.post(
        "/api/auth/complete-phone",
        json={"phone": "+254712345678"},
        headers=headers
    )
    assert complete_res.status_code == 200
    updated_user = complete_res.json()
    assert updated_user["phone"] == "+254712345678"
    assert updated_user["is_profile_complete"] is True

    # 3. Next social login should indicate phone is already present (requires_phone=False)
    login_again = await app_client.post("/api/auth/social", json={
        "provider": "firebase",
        "token": token_str
    })
    assert login_again.status_code == 200
    assert login_again.json()["is_new_user"] is False
    assert login_again.json()["requires_phone"] is False


@pytest.mark.asyncio
async def test_complete_phone_conflict(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies that attempting to complete a phone number already used by another customer raises 409 Conflict.
    """
    # Create existing user with phone
    existing = User(
        first_name="Alice",
        last_name="Smith",
        username="alicesmith",
        email="alice@example.com",
        phone="+254799999999",
        password_hash=await hash_password_async("Password123!"),
        role=UserRole.CUSTOMER,
        is_active=True
    )
    existing.customer = Customer()
    test_db_session.add(existing)
    await test_db_session.commit()

    # New social user
    token_str = "test_token_bob_bob@example.com"
    auth_res = await app_client.post("/api/auth/social", json={
        "provider": "google",
        "token": token_str
    })
    token = auth_res.json()["access_token"]

    # Try setting phone to existing user's phone
    res = await app_client.post(
        "/api/auth/complete-phone",
        json={"phone": "+254799999999"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 409
    assert "already in use" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_social_auth_account_linking_by_email(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies account linking: when an email previously registered manually signs in with Google,
    the account is linked with the social provider rather than duplicating rows.
    """
    # Manual user exists
    manual_user = User(
        first_name="Charles",
        last_name="Darwin",
        username="cdarwin",
        email="charles@example.com",
        phone="+254711223344",
        password_hash=await hash_password_async("Password123!"),
        role=UserRole.CUSTOMER,
        is_active=True,
        is_verified=False
    )
    manual_user.customer = Customer()
    test_db_session.add(manual_user)
    await test_db_session.commit()

    # Now Charles signs in via Google OAuth
    token_str = "test_token_googleuid999_charles@example.com"
    res = await app_client.post("/api/auth/social", json={
        "provider": "google",
        "token": token_str
    })
    assert res.status_code == 200
    data = res.json()
    assert data["is_new_user"] is False
    assert data["requires_phone"] is False
    assert data["user"]["email"] == "charles@example.com"
    # email is now verified by Google
    assert data["user"]["is_verified"] is True
    # phone is preserved
    assert data["user"]["phone"] == "+254711223344"


@pytest.mark.asyncio
async def test_manual_registration_still_enforces_phone(app_client: AsyncClient):
    """
    ensures that standard manual signup still strictly requires phone number.
    """
    # Missing phone -> 422
    invalid_payload = {
        "first_name": "Test",
        "last_name": "User",
        "email": "manualtest@example.com",
        "password": "ValidPassword123!",
        "password_confirm": "ValidPassword123!"
    }
    res = await app_client.post("/api/auth/signup", json=invalid_payload)
    assert res.status_code == 422

    # Valid payload with phone -> 201
    valid_payload = {
        "first_name": "Test",
        "last_name": "User",
        "email": "manualtest@example.com",
        "phone": "+254788112233",
        "password": "ValidPassword123!",
        "password_confirm": "ValidPassword123!"
    }
    res_valid = await app_client.post("/api/auth/signup", json=valid_payload)
    assert res_valid.status_code == 201
    assert res_valid.json()["phone"] == "+254788112233"


@pytest.mark.asyncio
async def test_social_user_password_login_prevented(app_client: AsyncClient):
    """
    verifies that a social user who has no password cannot authenticate via username/password /login route
    until they explicitly set a password.
    """
    token_str = "test_token_oauthuser1_oauthuser1@example.com"
    res = await app_client.post("/api/auth/social", json={
        "provider": "google",
        "token": token_str
    })
    assert res.status_code == 200

    # Try logging in with password
    login_res = await app_client.post("/api/auth/login", data={
        "username": "oauthuser1@example.com",
        "password": "SomeRandomPassword123!"
    })
    assert login_res.status_code == 401


@pytest.mark.asyncio
async def test_deactivated_social_user_blocked(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    verifies that if an account was deactivated, social login rejects authentication with 403.
    """
    deactivated = User(
        first_name="Deact",
        last_name="User",
        username="deactuser",
        email="deact@example.com",
        phone="+254700000001",
        password_hash=None,
        role=UserRole.CUSTOMER,
        is_active=False
    )
    deactivated.customer = Customer()
    test_db_session.add(deactivated)
    await test_db_session.commit()

    token_str = "test_token_uiddeact_deact@example.com"
    res = await app_client.post("/api/auth/social", json={
        "provider": "google",
        "token": token_str
    })
    assert res.status_code == 403
    assert "deactivated" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_unique_username_generation_for_multiple_social_users(app_client: AsyncClient):
    """
    verifies that when multiple social users share the exact same names,
    the auth service auto-increments unique usernames (e.g. testsocialuser, testsocialuser2).
    """
    user1_res = await app_client.post("/api/auth/social", json={
        "provider": "google",
        "token": "test_token_user1_user1@example.com"
    })
    assert user1_res.status_code == 200
    u1_username = user1_res.json()["user"]["username"]

    user2_res = await app_client.post("/api/auth/social", json={
        "provider": "google",
        "token": "test_token_user2_user2@example.com"
    })
    assert user2_res.status_code == 200
    u2_username = user2_res.json()["user"]["username"]

    assert u1_username != u2_username
    assert u2_username.startswith(u1_username)
