# tests/test_osm_routing.py

import json
from decimal import Decimal
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from src import create_app
from src.algorithms.route_engines import (
    AStarRouter,
    DEFAULT_HIGHWAY_SPEEDS_KMH,
    DijkstraRouter,
    RoadNetworkRouter,
    RoutingAlgorithm,
    calculate_edge_length_m,
    calculate_edge_speed_kmh,
    calculate_edge_travel_time_s,
    calculate_edge_weight,
    get_router,
    init_router,
)
from src.database import Base, get_db
from src.models import (
    Address,
    ApprovalStatus,
    Customer,
    Delivery,
    DeliveryStatus,
    Order,
    OrderStatus,
    PaymentMethod,
    Rider,
    RiderStatus,
    User,
    UserRole,
    VehicleType,
)
from src.security import create_access_token, hash_password_async, make_handover_code


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

    app.dependency_overrides.clear()


# ==============================================================================
# ALGORITHM & ROUTE ENGINE UNIT TESTS
# ==============================================================================

def test_edge_weight_calculations():
    """Validates highway speed resolution, surface penalties, and travel times."""
    trunk_edge = {"highway": "trunk", "length": 1000.0}
    speed_trunk = calculate_edge_speed_kmh(trunk_edge)
    assert speed_trunk == DEFAULT_HIGHWAY_SPEEDS_KMH["trunk"]
    duration_trunk = calculate_edge_travel_time_s(trunk_edge)
    # 1000m at 80 km/h (22.22 m/s) ~ 45s
    assert 40.0 < duration_trunk < 50.0

    residential_edge = {"highway": "residential", "length": 500.0}
    speed_res = calculate_edge_speed_kmh(residential_edge)
    assert speed_res == DEFAULT_HIGHWAY_SPEEDS_KMH["residential"]

    # Surface penalty test: unpaved should take longer than paved
    paved_edge = {"highway": "secondary", "length": 1000.0, "surface": "paved"}
    unpaved_edge = {"highway": "secondary", "length": 1000.0, "surface": "unpaved"}
    assert calculate_edge_travel_time_s(unpaved_edge) > calculate_edge_travel_time_s(paved_edge)

    # Maxspeed tag parsing
    custom_speed_edge = {"highway": "residential", "maxspeed": "50", "length": 500.0}
    assert calculate_edge_speed_kmh(custom_speed_edge) == 50.0

    list_speed_edge = {"highway": "residential", "maxspeed": ["40", "30"], "length": 500.0}
    assert calculate_edge_speed_kmh(list_speed_edge) == 40.0


def test_dijkstra_and_a_star_consistency_on_migori_graph():
    """
    Ensures both Dijkstra and A* compute optimal routes on the 7km Migori OpenStreetMap graphml,
    and verify their distances and travel times agree within expected parity.
    """
    router = RoadNetworkRouter("migori_bansi_7km.graphml", supermarket_coords=(-1.0641, 34.4741))
    assert router.graph.number_of_nodes() > 1000
    assert router.supermarket_node is not None

    # Destination point ~1.5 km away from supermarket in Migori
    target_lat = -1.0720
    target_lon = 34.4820

    route_dijkstra = router.route_from_supermarket(target_lat, target_lon, algorithm=RoutingAlgorithm.DIJKSTRA)
    route_astar = router.route_from_supermarket(target_lat, target_lon, algorithm=RoutingAlgorithm.A_STAR)

    assert route_dijkstra.algorithm == RoutingAlgorithm.DIJKSTRA
    assert route_astar.algorithm == RoutingAlgorithm.A_STAR

    # Both must reach the target node
    assert route_dijkstra.target_node == route_astar.target_node
    assert route_dijkstra.source_node == router.supermarket_node

    # Distances and travel times must match optimal solution
    assert abs(route_dijkstra.total_distance_m - route_astar.total_distance_m) < 1.0
    assert abs(route_dijkstra.total_duration_s - route_astar.total_duration_s) < 0.1

    # Steps and waypoints validation
    assert len(route_dijkstra.steps) > 0
    assert len(route_dijkstra.coordinates) > 0
    waypoints = route_dijkstra.to_waypoints_list()
    assert len(waypoints) == len(route_dijkstra.coordinates)
    assert isinstance(waypoints[0][0], float)

    # GeoJSON validation
    geojson = route_dijkstra.to_geojson()
    assert geojson["type"] == "Feature"
    assert geojson["geometry"]["type"] == "LineString"
    assert len(geojson["geometry"]["coordinates"]) > 0


def test_random_routing_algorithm_selection():
    """Verifies that randomized routing engine selection picks both Dijkstra and A* across multiple jobs."""
    router = RoadNetworkRouter("migori_bansi_7km.graphml", supermarket_coords=(-1.0641, 34.4741))
    target_lat = -1.0700
    target_lon = 34.4800

    algorithms_chosen = set()
    for _ in range(20):
        res = router.route_from_supermarket(target_lat, target_lon)
        algorithms_chosen.add(res.algorithm)

    # With 20 trials, probability of not seeing both is 2 * (0.5)^20 ~ 2e-6
    assert RoutingAlgorithm.DIJKSTRA in algorithms_chosen
    assert RoutingAlgorithm.A_STAR in algorithms_chosen


def test_coverage_and_delivery_fee_calculations():
    """Tests 7km radius validation and base+km fee calculation."""
    router = get_router()

    # Point ~1km away -> inside coverage
    inside_lat, inside_lon = router.supermarket_coords[0] + 0.008, router.supermarket_coords[1]
    is_within, dist_m = router.is_within_coverage(inside_lat, inside_lon)
    assert is_within is True
    assert dist_m < 2000.0

    # Point ~15km away -> outside coverage
    outside_lat, outside_lon = router.supermarket_coords[0] + 0.15, router.supermarket_coords[1]
    is_within_far, dist_far_m = router.is_within_coverage(outside_lat, outside_lon)
    assert is_within_far is False
    assert dist_far_m > 10000.0

    # Dynamic fee: Base 50 + KES 20/km
    fee_1km = router.calculate_delivery_fee(1000.0)
    assert fee_1km == Decimal("70")
    fee_3km = router.calculate_delivery_fee(3000.0)
    assert fee_3km == Decimal("110")


# ==============================================================================
# CUSTOMER ROUTER END-TO-END TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_customer_estimate_and_coverage(app_client: AsyncClient):
    """Tests POST /api/customer/delivery/estimate and GET /api/customer/delivery/coverage."""
    settings = get_settings()
    s_lat, s_lon = float(settings.supermarket_latitude), float(settings.supermarket_longitude)

    # Coverage check inside 7km
    resp = await app_client.get(f"/api/customer/delivery/coverage?lat={s_lat + 0.005}&lon={s_lon + 0.005}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_covered"] is True
    assert data["max_radius_km"] == 7.0
    assert "Bansi Mega Supermarket" in data["supermarket_name"]

    # Delivery estimate inside coverage
    resp_est = await app_client.post(
        "/api/customer/delivery/estimate",
        json={"latitude": round(s_lat + 0.005, 6), "longitude": round(s_lon + 0.005, 6)},
    )
    assert resp_est.status_code == 200
    est_data = resp_est.json()
    assert est_data["is_deliverable"] is True
    assert est_data["distance_m"] > 0
    assert est_data["duration_s"] > 0
    assert float(est_data["delivery_fee"]) >= 50
    assert est_data["routing_algorithm"] in ("dijkstra", "a_star")
    assert len(est_data["waypoints"]) > 0

    # Delivery estimate outside 7km coverage
    resp_outside = await app_client.post(
        "/api/customer/delivery/estimate",
        json={"latitude": -1.3000, "longitude": 34.4800},
    )
    assert resp_outside.status_code in (400, 409, 422)
    assert "coverage" in resp_outside.json()["detail"].lower()


@pytest.mark.asyncio
async def test_customer_tracking_and_handover_code(app_client: AsyncClient, test_db_session: AsyncSession):
    """Tests GET /api/customer/orders/{id}/tracking and handover-code."""
    # Create customer user and profile
    pwd_hash = await hash_password_async("CustomerPass123!")
    user = User(
        first_name="Jane",
        last_name="Otieno",
        username="jane_otieno",
        phone="+254711000001",
        email="jane.customer@example.com",
        role=UserRole.CUSTOMER,
        password_hash=pwd_hash,
        is_verified=True,
    )
    test_db_session.add(user)
    await test_db_session.flush()

    customer = Customer(user_id=user.id)
    test_db_session.add(customer)
    await test_db_session.flush()

    # Create order with delivery coordinates in Migori
    order = Order(
        order_number="ORD-MIG-001",
        customer_id=customer.id,
        subtotal=Decimal("1500.00"),
        delivery_fee=Decimal("70.00"),
        total=Decimal("1570.00"),
        status=OrderStatus.CONFIRMED,
        delivery_latitude=Decimal("-1.0680"),
        delivery_longitude=Decimal("34.4780"),
        delivery_address_text="Migori Town Center",
    )
    test_db_session.add(order)
    await test_db_session.flush()

    settings = get_settings()

    # Create a rider to assign
    r_u = User(
        first_name="Sam",
        last_name="Rider",
        username="sam_rider",
        phone="+254711000099",
        email="sam.rider@example.com",
        role=UserRole.RIDER,
        password_hash=pwd_hash,
        is_verified=True,
    )
    test_db_session.add(r_u)
    await test_db_session.flush()

    rider = Rider(
        user_id=r_u.id,
        approval_status=ApprovalStatus.APPROVED,
        status=RiderStatus.BUSY,
        vehicle_type=VehicleType.MOTORCYCLE,
        vehicle_plate="KMDB999Y",
        national_id_number="99988877",
        last_latitude=Decimal("-1.0645"),
        last_longitude=Decimal("34.4745"),
    )
    test_db_session.add(rider)
    await test_db_session.flush()

    delivery = Delivery(
        order_id=order.id,
        rider_id=rider.id,
        status=DeliveryStatus.ASSIGNED,
        rider_fee=Decimal("49.00"),
        estimated_distance_m=1200,
        estimated_duration_s=110,
        routing_algorithm="a_star",
        pickup_latitude=Decimal("-1.0641"),
        pickup_longitude=Decimal("34.4741"),
    )
    test_db_session.add(delivery)
    await test_db_session.commit()

    token = create_access_token(user.id, settings.secret_key.get_secret_value(), expires_minutes=60)
    headers = {"Authorization": f"Bearer {token}"}

    # Tracking endpoint
    resp_track = await app_client.get(f"/api/customer/orders/{order.id}/tracking", headers=headers)
    assert resp_track.status_code == 200
    track_data = resp_track.json()
    assert track_data["order_id"] == order.id
    assert track_data["status"] == "assigned"
    assert track_data["routing_algorithm"] == "a_star"
    assert track_data["estimated_distance_m"] == 1200
    assert track_data["supermarket_location"]["latitude"] == -1.0641

    # Handover code endpoint
    resp_code = await app_client.get(f"/api/customer/orders/{order.id}/handover-code", headers=headers)
    assert resp_code.status_code == 200
    code_data = resp_code.json()
    assert code_data["order_id"] == order.id
    assert len(code_data["handover_code"]) >= 4


# ==============================================================================
# RIDER ROUTER & DISPATCHING INTEGRATION TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_rider_lifecycle_navigation_and_dispatch(app_client: AsyncClient, test_db_session: AsyncSession):
    """
    Tests complete rider lifecycle:
    1. Rider onboarding application & availability
    2. GPS location pinging
    3. Auto-dispatch selection using road routing
    4. Offer response, pickup at Bansi Mega Supermarket, arrival, and completion with PIN
    5. Active navigation route instructions
    """
    settings = get_settings()
    s_lat, s_lon = float(settings.supermarket_latitude), float(settings.supermarket_longitude)

    # 1. Create rider user & profile
    r_user = User(
        first_name="Kevin",
        last_name="Omondi",
        username="kevin_omondi",
        phone="+254711000002",
        email="kevin.rider@example.com",
        role=UserRole.RIDER,
        password_hash=await hash_password_async("RiderPass123!"),
        is_verified=True,
    )
    test_db_session.add(r_user)
    await test_db_session.flush()

    rider = Rider(
        user_id=r_user.id,
        approval_status=ApprovalStatus.APPROVED,
        status=RiderStatus.AVAILABLE,
        vehicle_type=VehicleType.MOTORCYCLE,
        vehicle_plate="KMDA123X",
        national_id_number="12345678",
        licence_number="DL-12345",
        last_latitude=Decimal(str(round(s_lat + 0.009, 6))),
        last_longitude=Decimal(str(round(s_lon, 6))),
    )
    test_db_session.add(rider)

    # 2. Create customer and order
    c_user = User(
        first_name="Alice",
        last_name="Achieng",
        username="alice_achieng",
        phone="+254711000003",
        email="alice.test@example.com",
        role=UserRole.CUSTOMER,
        password_hash=await hash_password_async("CustPass123!"),
        is_verified=True,
    )
    test_db_session.add(c_user)
    await test_db_session.flush()

    customer = Customer(user_id=c_user.id)
    test_db_session.add(customer)
    await test_db_session.flush()

    order = Order(
        order_number="ORD-MIG-002",
        customer_id=customer.id,
        subtotal=Decimal("2000.00"),
        delivery_fee=Decimal("70.00"),
        total=Decimal("2070.00"),
        status=OrderStatus.READY,
        payment_method=PaymentMethod.MPESA,
        delivery_latitude=Decimal(str(round(s_lat, 6))),
        delivery_longitude=Decimal(str(round(s_lon + 0.009, 6))),
        delivery_address_text="Bansi Delivery Destination",
    )
    test_db_session.add(order)
    await test_db_session.flush()

    delivery = Delivery(
        order_id=order.id,
        status=DeliveryStatus.UNASSIGNED,
        rider_fee=Decimal("49.00"),
    )
    test_db_session.add(delivery)
    await test_db_session.commit()

    rider_token = create_access_token(r_user.id, settings.secret_key.get_secret_value(), expires_minutes=60)
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    # 3. Rider profile and location ping
    resp_prof = await app_client.get("/api/rider/profile", headers=rider_headers)
    assert resp_prof.status_code == 200
    assert resp_prof.json()["vehicle_plate"] == "KMDA123X"

    resp_ping = await app_client.post(
        "/api/rider/location",
        json={"latitude": round(s_lat + 0.009, 6), "longitude": round(s_lon, 6)},
        headers=rider_headers,
    )
    assert resp_ping.status_code == 200

    # 4. Dispatch assignment via DeliveryService with randomized routing engine
    from src.services import DeliveryService
    del_service = DeliveryService(test_db_session, settings)
    assigned_delivery, assigned_rider = await del_service.auto_dispatch(delivery.id, r_user)

    assert assigned_delivery.status == DeliveryStatus.ASSIGNED
    assert assigned_delivery.rider_id == rider.id
    assert assigned_delivery.routing_algorithm in ("dijkstra", "a_star")
    assert assigned_delivery.estimated_distance_m is not None
    assert assigned_delivery.estimated_distance_m > 0
    assert assigned_delivery.route_waypoints is not None

    # 5. Rider active deliveries
    resp_active = await app_client.get("/api/rider/deliveries/active", headers=rider_headers)
    assert resp_active.status_code == 200
    active_jobs = resp_active.json()
    assert len(active_jobs) == 1
    assert active_jobs[0]["id"] == delivery.id
    assert active_jobs[0]["routing_algorithm"] in ("dijkstra", "a_star")

    # 6. Delivery detail endpoint
    resp_detail = await app_client.get(f"/api/rider/deliveries/{delivery.id}", headers=rider_headers)
    assert resp_detail.status_code == 200
    d_data = resp_detail.json()
    assert d_data["pickup_location"]["latitude"] == float(settings.supermarket_latitude)
    assert d_data["dropoff_location"]["latitude"] == float(round(s_lat, 6))

    # 7. Navigation route to Bansi Mega Supermarket (leg 1: to store)
    resp_nav_store = await app_client.get(f"/api/rider/deliveries/{delivery.id}/navigation", headers=rider_headers)
    assert resp_nav_store.status_code == 200
    nav_store_data = resp_nav_store.json()
    assert nav_store_data["leg"] == "to_supermarket"
    assert nav_store_data["distance_m"] > 0
    assert len(nav_store_data["waypoints"]) > 0

    # 8. Accept offer
    resp_accept = await app_client.post(
        f"/api/rider/deliveries/{delivery.id}/respond",
        json={"accept": True},
        headers=rider_headers,
    )
    assert resp_accept.status_code == 200
    assert resp_accept.json()["status"] == "accepted"

    # 9. Pickup parcel at Bansi Mega Supermarket
    resp_pick = await app_client.post(f"/api/rider/deliveries/{delivery.id}/pickup", headers=rider_headers)
    assert resp_pick.status_code == 200
    assert resp_pick.json()["status"] == "picked_up"

    # 10. Navigation route to customer (leg 2: to customer)
    resp_nav_cust = await app_client.get(f"/api/rider/deliveries/{delivery.id}/navigation", headers=rider_headers)
    assert resp_nav_cust.status_code == 200
    nav_cust_data = resp_nav_cust.json()
    assert nav_cust_data["leg"] == "to_customer"
    assert nav_cust_data["distance_m"] > 0

    # 11. Arrive at customer address
    resp_arrive = await app_client.post(f"/api/rider/deliveries/{delivery.id}/arrive", headers=rider_headers)
    assert resp_arrive.status_code == 200
    assert resp_arrive.json()["status"] == "arrived"

    # 12. Complete delivery with valid handover code
    code = make_handover_code(settings.secret_key.get_secret_value(), delivery.id, settings.handover_code_length)
    resp_complete = await app_client.post(
        f"/api/rider/deliveries/{delivery.id}/complete",
        json={"handover_code": code},
        headers=rider_headers,
    )
    assert resp_complete.status_code == 200
    assert resp_complete.json()["status"] == "delivered"
