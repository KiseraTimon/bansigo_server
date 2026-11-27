# src/schemas/simulation.py

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel

from .common import ORMModel


class SimulationRunOut(ORMModel):
    id: int
    run_code: str
    title: str
    status: str
    seed: int
    total_agents: int
    target_baskets: int
    completed_baskets: int
    total_events: int
    routing_comparisons_count: int
    recommender_comparisons_count: int
    config_json: Optional[dict[str, Any]] = None
    summary_metrics_json: Optional[dict[str, Any]] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class SimulationEventIn(BaseModel):
    phase: str
    actor_role: str
    actor_subrole: Optional[str] = None
    actor_user_id: Optional[int] = None
    session_id: Optional[str] = None
    action: str
    http_method: Optional[str] = None
    endpoint: Optional[str] = None
    http_status: Optional[int] = None
    latency_ms: float = 0.0
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    payload_summary: Optional[dict[str, Any]] = None
