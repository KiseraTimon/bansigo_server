# scripts/run_system_simulation.py

"""
CLI entrypoint to execute the BansiGo 54-Agent End-to-End Lifecycle & Co-Algorithm Simulation
and persist all events, orders, deliveries, reviews, and algorithm comparisons into the database.
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_settings
from src import Base, _sync_missing_columns, create_app
from src.algorithms.route_engines import init_router
from src.database import AsyncSessionLocal, engine
from src.simulation import SimulationConfig, SystemSimulationOrchestrator


async def main_async(baskets: int, seed: int) -> dict:
    settings = get_settings()
    import src.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sync_missing_columns)

    road_router = init_router()
    app = create_app()
    app.state.road_router = road_router
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = SimulationConfig(
        target_baskets=baskets,
        seed=seed,
        run_scaling_benchmarks=True,
        od_benchmark_pairs=45,
    )
    orchestrator = SystemSimulationOrchestrator(
        app=app,
        session_factory=AsyncSessionLocal,
        settings=settings,
        config=cfg,
    )

    try:
        result = await orchestrator.execute(progress_cb=lambda m: print(m, flush=True))
        print("\n=== SIMULATION SUMMARY ===")
        print(json.dumps(result, indent=2, default=str))
        return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BansiGo Multi-Agent End-to-End Simulation")
    parser.add_argument("--baskets", type=int, default=335, help="Number of synthetic shopping baskets (default: 335)")
    parser.add_argument("--seed", type=int, default=20261127, help="Deterministic PRNG seed")
    args = parser.parse_args()

    asyncio.run(main_async(baskets=args.baskets, seed=args.seed))


if __name__ == "__main__":
    main()
