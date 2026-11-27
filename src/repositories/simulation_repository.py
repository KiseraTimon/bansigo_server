# src/repositories/simulation_repository.py

"""
Repository handling database queries for simulation runs, actor events,
routing algorithm comparisons, and recommender algorithm comparisons.
"""

from typing import Any, Sequence
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    RecommenderAlgorithmComparison,
    RoutingAlgorithmComparison,
    SimulationEvent,
    SimulationRun,
)
from .base_repository import BaseRepository


class SimulationRepository(BaseRepository[SimulationRun]):
    def __init__(self, db: AsyncSession):
        super().__init__(SimulationRun, db)

    async def get_by_code(self, run_code: str) -> SimulationRun | None:
        stmt = select(SimulationRun).where(SimulationRun.run_code == run_code)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_latest_completed_run(self) -> SimulationRun | None:
        stmt = (
            select(SimulationRun)
            .where(SimulationRun.status == "completed")
            .order_by(SimulationRun.id.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def add_events_bulk(self, events: Sequence[SimulationEvent]) -> None:
        if events:
            self.db.add_all(events)
            await self.db.flush()

    async def add_routing_comparison(self, comp: RoutingAlgorithmComparison) -> RoutingAlgorithmComparison:
        self.db.add(comp)
        await self.db.flush()
        return comp

    async def add_recommender_comparison(self, comp: RecommenderAlgorithmComparison) -> RecommenderAlgorithmComparison:
        self.db.add(comp)
        await self.db.flush()
        return comp

    async def list_events_for_run(self, run_id: int) -> list[SimulationEvent]:
        stmt = (
            select(SimulationEvent)
            .where(SimulationEvent.run_id == run_id)
            .order_by(SimulationEvent.sequence_no.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_routing_comparisons(self, run_id: int) -> list[RoutingAlgorithmComparison]:
        stmt = (
            select(RoutingAlgorithmComparison)
            .where(RoutingAlgorithmComparison.run_id == run_id)
            .order_by(RoutingAlgorithmComparison.id.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_recommender_comparisons(self, run_id: int) -> list[RecommenderAlgorithmComparison]:
        stmt = (
            select(RecommenderAlgorithmComparison)
            .where(RecommenderAlgorithmComparison.run_id == run_id)
            .order_by(RecommenderAlgorithmComparison.id.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_event_breakdown_by_role_and_phase(self, run_id: int) -> list[tuple[str, str, int, float]]:
        stmt = (
            select(
                SimulationEvent.actor_role,
                SimulationEvent.phase,
                func.count(SimulationEvent.id),
                func.avg(SimulationEvent.latency_ms),
            )
            .where(SimulationEvent.run_id == run_id)
            .group_by(SimulationEvent.actor_role, SimulationEvent.phase)
            .order_by(SimulationEvent.actor_role, SimulationEvent.phase)
        )
        return list((await self.db.execute(stmt)).all())

    async def count_for_run(self, run_id: int) -> dict[str, Any]:
        ev_cnt = (
            await self.db.execute(select(func.count(SimulationEvent.id)).where(SimulationEvent.run_id == run_id))
        ).scalar_one() or 0
        rt_cnt = (
            await self.db.execute(
                select(func.count(RoutingAlgorithmComparison.id)).where(RoutingAlgorithmComparison.run_id == run_id)
            )
        ).scalar_one() or 0
        rc_cnt = (
            await self.db.execute(
                select(func.count(RecommenderAlgorithmComparison.id)).where(
                    RecommenderAlgorithmComparison.run_id == run_id
                )
            )
        ).scalar_one() or 0
        return {
            "events": int(ev_cnt),
            "routing_comparisons": int(rt_cnt),
            "recommender_comparisons": int(rc_cnt),
        }
