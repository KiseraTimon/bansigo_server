# tests/test_simulation.py

"""
Automated unit and integration tests for the instrumented routing/recommender
co-algorithm comparison engines, persistent simulation models, and multi-agent
end-to-end simulation orchestrator.
"""

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from src import create_app
from src.algorithms.recommenders import Basket, HybridRecommenderEngine, MiningConfig
from src.algorithms.route_engines import init_router
from src.database import Base, get_db
from src.models import (
    Order,
    RecommendationEvent,
    RecommenderAlgorithmComparison,
    Review,
    RoutingAlgorithmComparison,
    SimulationEvent,
    SimulationRun,
    User,
)
from src.simulation import SimulationConfig, SystemSimulationOrchestrator


@pytest_asyncio.fixture
async def sim_session_factory():
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await test_engine.dispose()


def test_recommender_instrumentation_and_co_algorithm_parity():
    baskets = [
        Basket(ref=f"b-{i}", items=frozenset([1, 2, 3] if i % 2 == 0 else [1, 2, 4]))
        for i in range(40)
    ] + [
        Basket(ref=f"c-{i}", items=frozenset([5, 6, 7]))
        for i in range(20)
    ]

    cfg = MiningConfig(min_support=0.05, min_support_count=2.0, min_confidence=0.25, min_lift=1.0)
    engine = HybridRecommenderEngine(cfg)
    cmp = engine.compare_algorithms(baskets=baskets, target_product_ids=[1, 2], available_product_ids=[1, 2, 3, 4, 5, 6, 7], limit=4)

    assert cmp["corpus_basket_count"] == 60
    assert cmp["itemset_parity"] is True
    assert cmp["rule_parity"] is True
    assert cmp["apriori_mining"].diagnostics["db_scans"] >= 2
    assert cmp["fpgrowth_mining"].diagnostics["db_scans"] == 2
    assert cmp["fpgrowth_mining"].diagnostics["fp_tree_nodes"] > 0
    assert "total_ms" in cmp["apriori_mining"].timings_ms
    assert "total_ms" in cmp["fpgrowth_mining"].timings_ms


def test_routing_instrumentation_and_co_algorithm_optimality():
    router = init_router()
    sm_lat, sm_lon = router.supermarket_coords
    # Test route within coverage radius
    cmp = router.compare_algorithms(
        source_lat=sm_lat,
        source_lon=sm_lon,
        target_lat=sm_lat - 0.008,
        target_lon=sm_lon + 0.006,
        weight="travel_time",
    )
    d_res = cmp["dijkstra"]
    a_res = cmp["a_star"]

    assert d_res.nodes_visited >= 1
    assert a_res.nodes_visited >= 1
    assert a_res.nodes_visited <= d_res.nodes_visited
    assert cmp["cost_delta_s"] < 1e-4
    assert cmp["distance_delta_m"] < 1e-2


@pytest.mark.asyncio
async def test_multi_agent_end_to_end_simulation_persistence(sim_session_factory):
    settings = get_settings()
    road_router = init_router()
    app = create_app()
    app.state.road_router = road_router

    async def _override_get_db():
        async with sim_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        # Compact 18-basket test run exercising all 54 agents & all 4 phases quickly in CI
        cfg = SimulationConfig(
            target_baskets=18,
            seed=12345,
            run_scaling_benchmarks=True,
            od_benchmark_pairs=6,
        )
        orchestrator = SystemSimulationOrchestrator(
            app=app,
            session_factory=sim_session_factory,
            settings=settings,
            config=cfg,
        )
        result = await orchestrator.execute()

        assert result["baskets_created"] == 18
        assert result["orders_completed"] >= 14
        assert result["total_events"] > 100
        assert result["routing_comparisons_count"] > 15
        assert result["recommender_comparisons_count"] > 10

        async with sim_session_factory() as db:
            run_row = (await db.execute(select(SimulationRun))).scalar_one()
            assert run_row.status == "completed"
            assert run_row.total_agents == 54

            user_cnt = (await db.execute(select(func.count(User.id)))).scalar_one()
            order_cnt = (await db.execute(select(func.count(Order.id)))).scalar_one()
            ev_cnt = (await db.execute(select(func.count(SimulationEvent.id)))).scalar_one()
            rt_cnt = (await db.execute(select(func.count(RoutingAlgorithmComparison.id)))).scalar_one()
            rc_cnt = (await db.execute(select(func.count(RecommenderAlgorithmComparison.id)))).scalar_one()
            rec_ev_cnt = (await db.execute(select(func.count(RecommendationEvent.id)))).scalar_one()
            rev_cnt = (await db.execute(select(func.count(Review.id)))).scalar_one()

            assert user_cnt >= 54
            assert order_cnt >= 18
            assert ev_cnt == result["total_events"]
            assert rt_cnt == result["routing_comparisons_count"]
            assert rc_cnt == result["recommender_comparisons_count"]
            assert rec_ev_cnt > 0
            assert rev_cnt > 0
    finally:
        app.dependency_overrides.clear()
