# src/models/simulation.py

"""
Persistent relational models for end-to-end multi-agent simulation runs,
chronological actor lifecycle events, and head-to-head co-algorithm evaluations
(Dijkstra vs A* road routing; Apriori vs FP-Growth association rule recommenders).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin, UTCDateTime
from .types import Coordinate


class SimulationRun(Base, TimestampMixin):
    """
    Master record for a complete multi-agent system simulation study run.
    """

    __tablename__ = "simulation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    seed: Mapped[int] = mapped_column(Integer, nullable=False, default=42)

    total_agents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_baskets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_baskets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    routing_comparisons_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommender_comparisons_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    config_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    summary_metrics_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    events: Mapped[list["SimulationEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="raise"
    )
    routing_comparisons: Mapped[list["RoutingAlgorithmComparison"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="raise"
    )
    recommender_comparisons: Mapped[list["RecommenderAlgorithmComparison"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="raise"
    )


class SimulationEvent(Base, TimestampMixin):
    """
    Immutable chronological trace of every autonomous agent action executed during a simulation run.
    """

    __tablename__ = "simulation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    actor_role: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    actor_subrole: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    http_method: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    endpoint: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    entity_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payload_summary: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    run: Mapped["SimulationRun"] = relationship(back_populates="events", lazy="raise")

    __table_args__ = (
        Index("idx_sim_event_run_seq", "run_id", "sequence_no"),
        Index("idx_sim_event_role_action", "actor_role", "action"),
    )


class RoutingAlgorithmComparison(Base, TimestampMixin):
    """
    Captures every live road-routing query alongside its exact counterfactual co-algorithm
    execution (Dijkstra vs A*) on the Migori OpenStreetMap MultiDiGraph.
    """

    __tablename__ = "simulation_routing_comparisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    delivery_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deliveries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rider_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("riders.id", ondelete="SET NULL"), nullable=True, index=True
    )

    context: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    weight_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="travel_time")

    source_lat: Mapped[Decimal] = mapped_column(Coordinate, nullable=False)
    source_lon: Mapped[Decimal] = mapped_column(Coordinate, nullable=False)
    target_lat: Mapped[Decimal] = mapped_column(Coordinate, nullable=False)
    target_lon: Mapped[Decimal] = mapped_column(Coordinate, nullable=False)
    source_node: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_node: Mapped[int] = mapped_column(BigInteger, nullable=False)
    straight_line_distance_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    selected_algorithm: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    co_algorithm: Mapped[str] = mapped_column(String(20), nullable=False)

    # Dijkstra telemetry
    dijkstra_distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    dijkstra_duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    dijkstra_exec_ms: Mapped[float] = mapped_column(Float, nullable=False)
    dijkstra_nodes_visited: Mapped[int] = mapped_column(Integer, nullable=False)
    dijkstra_edges_relaxed: Mapped[int] = mapped_column(Integer, nullable=False)
    dijkstra_pq_pushes: Mapped[int] = mapped_column(Integer, nullable=False)
    dijkstra_pq_pops: Mapped[int] = mapped_column(Integer, nullable=False)
    dijkstra_path_nodes: Mapped[int] = mapped_column(Integer, nullable=False)
    dijkstra_turn_steps: Mapped[int] = mapped_column(Integer, nullable=False)

    # A* telemetry
    astar_distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    astar_duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    astar_exec_ms: Mapped[float] = mapped_column(Float, nullable=False)
    astar_nodes_visited: Mapped[int] = mapped_column(Integer, nullable=False)
    astar_edges_relaxed: Mapped[int] = mapped_column(Integer, nullable=False)
    astar_pq_pushes: Mapped[int] = mapped_column(Integer, nullable=False)
    astar_pq_pops: Mapped[int] = mapped_column(Integer, nullable=False)
    astar_heuristic_evals: Mapped[int] = mapped_column(Integer, nullable=False)
    astar_path_nodes: Mapped[int] = mapped_column(Integer, nullable=False)
    astar_turn_steps: Mapped[int] = mapped_column(Integer, nullable=False)

    # Comparative metrics
    exact_path_parity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cost_delta_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    distance_delta_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    node_reduction_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    speedup_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    road_detour_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    dominant_highway_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    run: Mapped["SimulationRun"] = relationship(back_populates="routing_comparisons", lazy="raise")

    __table_args__ = (
        Index("idx_sim_routing_run_ctx", "run_id", "context"),
    )


class RecommenderAlgorithmComparison(Base, TimestampMixin):
    """
    Captures every live recommendation event and corpus checkpoint alongside its
    counterfactual co-algorithm execution (Apriori vs FP-Growth).
    """

    __tablename__ = "simulation_recommender_comparisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    context: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    corpus_basket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_support_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.01)
    min_confidence_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)
    target_product_ids_json: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)

    selected_algorithm: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    co_algorithm: Mapped[str] = mapped_column(String(20), nullable=False)

    # Apriori telemetry
    apriori_exec_ms: Mapped[float] = mapped_column(Float, nullable=False)
    apriori_itemset_ms: Mapped[float] = mapped_column(Float, nullable=False)
    apriori_rule_ms: Mapped[float] = mapped_column(Float, nullable=False)
    apriori_frequent_items: Mapped[int] = mapped_column(Integer, nullable=False)
    apriori_frequent_itemsets: Mapped[int] = mapped_column(Integer, nullable=False)
    apriori_candidates_generated: Mapped[int] = mapped_column(Integer, nullable=False)
    apriori_candidates_pruned: Mapped[int] = mapped_column(Integer, nullable=False)
    apriori_db_scans: Mapped[int] = mapped_column(Integer, nullable=False)
    apriori_rules_count: Mapped[int] = mapped_column(Integer, nullable=False)
    apriori_avg_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    apriori_avg_lift: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    apriori_max_lift: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    apriori_avg_conviction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    apriori_avg_zhang: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    apriori_top_ids_json: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)
    apriori_rule_matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # FP-Growth telemetry
    fpgrowth_exec_ms: Mapped[float] = mapped_column(Float, nullable=False)
    fpgrowth_itemset_ms: Mapped[float] = mapped_column(Float, nullable=False)
    fpgrowth_rule_ms: Mapped[float] = mapped_column(Float, nullable=False)
    fpgrowth_frequent_items: Mapped[int] = mapped_column(Integer, nullable=False)
    fpgrowth_frequent_itemsets: Mapped[int] = mapped_column(Integer, nullable=False)
    fpgrowth_tree_nodes: Mapped[int] = mapped_column(Integer, nullable=False)
    fpgrowth_cond_trees_built: Mapped[int] = mapped_column(Integer, nullable=False)
    fpgrowth_cond_tree_nodes: Mapped[int] = mapped_column(Integer, nullable=False)
    fpgrowth_prefix_paths: Mapped[int] = mapped_column(Integer, nullable=False)
    fpgrowth_db_scans: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    fpgrowth_rules_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fpgrowth_avg_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fpgrowth_avg_lift: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fpgrowth_max_lift: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fpgrowth_avg_conviction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fpgrowth_avg_zhang: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fpgrowth_top_ids_json: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)
    fpgrowth_rule_matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Comparative & downstream behavioral outcomes
    itemset_parity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rule_parity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    top_k_jaccard_overlap: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    top_k_exact_rank_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    speedup_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    impressions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cart_adds_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    purchases_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    run: Mapped["SimulationRun"] = relationship(back_populates="recommender_comparisons", lazy="raise")

    __table_args__ = (
        Index("idx_sim_rec_run_ctx", "run_id", "context"),
        Index("idx_sim_rec_corpus", "run_id", "corpus_basket_count"),
    )
