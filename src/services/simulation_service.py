# src/services/simulation_service.py

"""
Service coordinating persistence of multi-agent simulation runs, actor lifecycle
events, and co-algorithm benchmark comparisons (Dijkstra vs A*, Apriori vs FP-Growth).
"""

from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.algorithms.recommenders import Basket, HybridRecommenderEngine, MiningConfig
from src.algorithms.route_engines import get_router
from src.models import (
    Order,
    OrderItem,
    OrderStatus,
    Product,
    RecommenderAlgorithmComparison,
    RoutingAlgorithmComparison,
    SimulationEvent,
    SimulationRun,
)
from src.repositories import SimulationRepository
from src.schemas import SimulationEventIn
from utilities import get_logger, utc_now

log = get_logger(__name__)


class SimulationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SimulationRepository(db)

    async def start_run(
        self,
        *,
        run_code: str,
        title: str,
        seed: int,
        total_agents: int,
        target_baskets: int,
        config: dict[str, Any] | None = None,
    ) -> SimulationRun:
        run = SimulationRun(
            run_code=run_code,
            title=title,
            status="running",
            seed=seed,
            total_agents=total_agents,
            target_baskets=target_baskets,
            config_json=config or {},
            started_at=utc_now(),
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        log.info("Started simulation run %s (id=%s, seed=%s)", run.run_code, run.id, seed)
        return run

    async def finish_run(
        self,
        run_id: int,
        *,
        completed_baskets: int,
        summary_metrics: dict[str, Any],
        status: str = "completed",
    ) -> SimulationRun:
        run = await self.repo.get_by_id(run_id)
        if run is None:
            raise ValueError(f"SimulationRun {run_id} not found")
        counts = await self.repo.count_for_run(run_id)
        run.status = status
        run.completed_baskets = completed_baskets
        run.total_events = counts["events"]
        run.routing_comparisons_count = counts["routing_comparisons"]
        run.recommender_comparisons_count = counts["recommender_comparisons"]
        run.summary_metrics_json = summary_metrics
        run.completed_at = utc_now()
        await self.db.commit()
        await self.db.refresh(run)
        log.info(
            "Completed simulation run %s: baskets=%d, events=%d, routing_cmp=%d, rec_cmp=%d",
            run.run_code,
            completed_baskets,
            run.total_events,
            run.routing_comparisons_count,
            run.recommender_comparisons_count,
        )
        return run

    async def record_event(
        self,
        run_id: int,
        sequence_no: int,
        data: SimulationEventIn,
        *,
        commit: bool = True,
    ) -> SimulationEvent:
        ev = SimulationEvent(
            run_id=run_id,
            sequence_no=sequence_no,
            phase=data.phase,
            actor_role=data.actor_role,
            actor_subrole=data.actor_subrole,
            actor_user_id=data.actor_user_id,
            session_id=data.session_id,
            action=data.action,
            http_method=data.http_method,
            endpoint=data.endpoint,
            http_status=data.http_status,
            latency_ms=round(data.latency_ms, 3),
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            payload_summary=data.payload_summary,
        )
        self.db.add(ev)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        return ev

    async def record_routing_comparison(
        self,
        run_id: int,
        *,
        source_lat: float,
        source_lon: float,
        target_lat: float,
        target_lon: float,
        context: str,
        weight_mode: str = "travel_time",
        selected_algorithm: Optional[str] = None,
        order_id: Optional[int] = None,
        delivery_id: Optional[int] = None,
        rider_id: Optional[int] = None,
        commit: bool = True,
    ) -> RoutingAlgorithmComparison:
        router = get_router()
        cmp_data = router.compare_algorithms(
            source_lat=source_lat,
            source_lon=source_lon,
            target_lat=target_lat,
            target_lon=target_lon,
            weight=weight_mode,
            selected=selected_algorithm,
        )
        d_res = cmp_data["dijkstra"]
        a_res = cmp_data["a_star"]

        row = RoutingAlgorithmComparison(
            run_id=run_id,
            order_id=order_id,
            delivery_id=delivery_id,
            rider_id=rider_id,
            context=context,
            weight_mode=weight_mode,
            source_lat=Decimal(f"{source_lat:.6f}"),
            source_lon=Decimal(f"{source_lon:.6f}"),
            target_lat=Decimal(f"{target_lat:.6f}"),
            target_lon=Decimal(f"{target_lon:.6f}"),
            source_node=cmp_data["source_node"],
            target_node=cmp_data["target_node"],
            straight_line_distance_m=cmp_data["straight_line_distance_m"],
            selected_algorithm=cmp_data["selected_algorithm"],
            co_algorithm=cmp_data["co_algorithm"],
            dijkstra_distance_m=round(d_res.total_distance_m, 2),
            dijkstra_duration_s=round(d_res.total_duration_s, 3),
            dijkstra_exec_ms=d_res.execution_time_ms,
            dijkstra_nodes_visited=d_res.nodes_visited,
            dijkstra_edges_relaxed=d_res.edges_relaxed,
            dijkstra_pq_pushes=d_res.pq_pushes,
            dijkstra_pq_pops=d_res.pq_pops,
            dijkstra_path_nodes=len(d_res.node_path),
            dijkstra_turn_steps=len(d_res.steps),
            astar_distance_m=round(a_res.total_distance_m, 2),
            astar_duration_s=round(a_res.total_duration_s, 3),
            astar_exec_ms=a_res.execution_time_ms,
            astar_nodes_visited=a_res.nodes_visited,
            astar_edges_relaxed=a_res.edges_relaxed,
            astar_pq_pushes=a_res.pq_pushes,
            astar_pq_pops=a_res.pq_pops,
            astar_heuristic_evals=a_res.heuristic_evals,
            astar_path_nodes=len(a_res.node_path),
            astar_turn_steps=len(a_res.steps),
            exact_path_parity=cmp_data["exact_path_parity"],
            cost_delta_s=cmp_data["cost_delta_s"],
            distance_delta_m=cmp_data["distance_delta_m"],
            node_reduction_ratio=cmp_data["node_reduction_ratio"],
            speedup_factor=cmp_data["speedup_factor"],
            road_detour_factor=cmp_data["road_detour_factor"],
            dominant_highway_type=cmp_data["dominant_highway_type"],
        )
        await self.repo.add_routing_comparison(row)
        if commit:
            await self.db.commit()
        return row

    async def _load_live_baskets_and_products(
        self, max_baskets: Optional[int] = None
    ) -> tuple[list[Basket], list[int]]:
        stmt = (
            select(Order.id, OrderItem.product_id)
            .join(OrderItem, Order.id == OrderItem.order_id)
            .where(Order.status != OrderStatus.CANCELLED)
            .order_by(Order.id.asc())
        )
        rows = (await self.db.execute(stmt)).all()

        basket_map: dict[int, set[int]] = {}
        for oid, pid in rows:
            if oid not in basket_map:
                basket_map[oid] = set()
            basket_map[oid].add(pid)

        baskets = [
            Basket(ref=str(oid), items=frozenset(items))
            for oid, items in basket_map.items()
            if len(items) >= 2
        ]
        if max_baskets is not None:
            baskets = baskets[:max_baskets]

        prod_ids = list(
            (await self.db.execute(select(Product.id).where(Product.is_active.is_(True)))).scalars().all()
        )
        return baskets, prod_ids

    async def record_recommender_comparison(
        self,
        run_id: int,
        *,
        context: str,
        target_product_ids: Sequence[int] | None = None,
        selected_algorithm: Optional[str] = None,
        customer_id: Optional[int] = None,
        order_id: Optional[int] = None,
        session_id: Optional[str] = None,
        impressions_count: int = 0,
        clicks_count: int = 0,
        cart_adds_count: int = 0,
        purchases_count: int = 0,
        user_rating: Optional[int] = None,
        custom_config: Optional[MiningConfig] = None,
        max_baskets: Optional[int] = None,
        limit: int = 6,
        commit: bool = True,
    ) -> RecommenderAlgorithmComparison:
        baskets, prod_ids = await self._load_live_baskets_and_products(max_baskets=max_baskets)
        engine = HybridRecommenderEngine(config=custom_config)
        cmp_data = engine.compare_algorithms(
            baskets=baskets,
            target_product_ids=target_product_ids,
            available_product_ids=prod_ids,
            limit=limit,
            selected=selected_algorithm,
        )

        mine_a = cmp_data["apriori_mining"]
        mine_f = cmp_data["fpgrowth_mining"]
        stats_a = cmp_data["apriori_stats"]
        stats_f = cmp_data["fpgrowth_stats"]

        row = RecommenderAlgorithmComparison(
            run_id=run_id,
            customer_id=customer_id,
            order_id=order_id,
            session_id=session_id,
            context=context,
            corpus_basket_count=cmp_data["corpus_basket_count"],
            min_support_used=engine.config.min_support,
            min_confidence_used=engine.config.min_confidence,
            target_product_ids_json=list(target_product_ids) if target_product_ids else [],
            selected_algorithm=cmp_data["selected_algorithm"],
            co_algorithm=cmp_data["co_algorithm"],
            apriori_exec_ms=mine_a.timings_ms.get("total_ms", 0.0),
            apriori_itemset_ms=mine_a.timings_ms.get("itemset_mining_ms", 0.0),
            apriori_rule_ms=mine_a.timings_ms.get("rule_generation_ms", 0.0),
            apriori_frequent_items=mine_a.n_frequent_items,
            apriori_frequent_itemsets=mine_a.n_itemsets,
            apriori_candidates_generated=mine_a.diagnostics.get("candidates_generated", 0),
            apriori_candidates_pruned=mine_a.diagnostics.get("candidates_pruned", 0),
            apriori_db_scans=mine_a.diagnostics.get("db_scans", 0),
            apriori_rules_count=len(mine_a.rules),
            apriori_avg_confidence=stats_a["avg_confidence"],
            apriori_avg_lift=stats_a["avg_lift"],
            apriori_max_lift=stats_a["max_lift"],
            apriori_avg_conviction=stats_a["avg_conviction"],
            apriori_avg_zhang=stats_a["avg_zhang"],
            apriori_top_ids_json=cmp_data["apriori_top_ids"],
            apriori_rule_matched=cmp_data["apriori_rule_matched"],
            fpgrowth_exec_ms=mine_f.timings_ms.get("total_ms", 0.0),
            fpgrowth_itemset_ms=mine_f.timings_ms.get("itemset_mining_ms", 0.0),
            fpgrowth_rule_ms=mine_f.timings_ms.get("rule_generation_ms", 0.0),
            fpgrowth_frequent_items=mine_f.n_frequent_items,
            fpgrowth_frequent_itemsets=mine_f.n_itemsets,
            fpgrowth_tree_nodes=mine_f.diagnostics.get("fp_tree_nodes", 0),
            fpgrowth_cond_trees_built=mine_f.diagnostics.get("cond_trees_built", 0),
            fpgrowth_cond_tree_nodes=mine_f.diagnostics.get("cond_tree_nodes", 0),
            fpgrowth_prefix_paths=mine_f.diagnostics.get("prefix_paths_extracted", 0),
            fpgrowth_db_scans=mine_f.diagnostics.get("db_scans", 2),
            fpgrowth_rules_count=len(mine_f.rules),
            fpgrowth_avg_confidence=stats_f["avg_confidence"],
            fpgrowth_avg_lift=stats_f["avg_lift"],
            fpgrowth_max_lift=stats_f["max_lift"],
            fpgrowth_avg_conviction=stats_f["avg_conviction"],
            fpgrowth_avg_zhang=stats_f["avg_zhang"],
            fpgrowth_top_ids_json=cmp_data["fpgrowth_top_ids"],
            fpgrowth_rule_matched=cmp_data["fpgrowth_rule_matched"],
            itemset_parity=cmp_data["itemset_parity"],
            rule_parity=cmp_data["rule_parity"],
            top_k_jaccard_overlap=cmp_data["top_k_jaccard_overlap"],
            top_k_exact_rank_match=cmp_data["top_k_exact_rank_match"],
            speedup_factor=cmp_data["speedup_factor"],
            impressions_count=impressions_count,
            clicks_count=clicks_count,
            cart_adds_count=cart_adds_count,
            purchases_count=purchases_count,
            user_rating=user_rating,
        )
        await self.repo.add_recommender_comparison(row)
        if commit:
            await self.db.commit()
        return row
