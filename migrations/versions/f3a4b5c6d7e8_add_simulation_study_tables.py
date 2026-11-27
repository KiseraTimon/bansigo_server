# migrations/versions/f3a4b5c6d7e8_add_simulation_study_tables.py
"""add simulation runs, events, and co-algorithm comparison tables

Revision ID: f3a4b5c6d7e8
Revises: e5867d4bc48f
Create Date: 2026-11-27 05:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e5867d4bc48f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_code", sa.String(length=40), nullable=False, unique=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("total_agents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_baskets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_baskets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("routing_comparisons_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recommender_comparisons_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("summary_metrics_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "simulation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=40), nullable=False),
        sa.Column("actor_role", sa.String(length=30), nullable=False),
        sa.Column("actor_subrole", sa.String(length=50), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.String(length=80), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("http_method", sa.String(length=10), nullable=True),
        sa.Column("endpoint", sa.String(length=180), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("entity_type", sa.String(length=40), nullable=True),
        sa.Column("entity_id", sa.String(length=50), nullable=True),
        sa.Column("payload_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "simulation_routing_comparisons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("delivery_id", sa.Integer(), sa.ForeignKey("deliveries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rider_id", sa.Integer(), sa.ForeignKey("riders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("context", sa.String(length=40), nullable=False),
        sa.Column("weight_mode", sa.String(length=20), nullable=False),
        sa.Column("source_lat", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("source_lon", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("target_lat", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("target_lon", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("source_node", sa.BigInteger(), nullable=False),
        sa.Column("target_node", sa.BigInteger(), nullable=False),
        sa.Column("straight_line_distance_m", sa.Float(), nullable=False),
        sa.Column("selected_algorithm", sa.String(length=20), nullable=False),
        sa.Column("co_algorithm", sa.String(length=20), nullable=False),
        sa.Column("dijkstra_distance_m", sa.Float(), nullable=False),
        sa.Column("dijkstra_duration_s", sa.Float(), nullable=False),
        sa.Column("dijkstra_exec_ms", sa.Float(), nullable=False),
        sa.Column("dijkstra_nodes_visited", sa.Integer(), nullable=False),
        sa.Column("dijkstra_edges_relaxed", sa.Integer(), nullable=False),
        sa.Column("dijkstra_pq_pushes", sa.Integer(), nullable=False),
        sa.Column("dijkstra_pq_pops", sa.Integer(), nullable=False),
        sa.Column("dijkstra_path_nodes", sa.Integer(), nullable=False),
        sa.Column("dijkstra_turn_steps", sa.Integer(), nullable=False),
        sa.Column("astar_distance_m", sa.Float(), nullable=False),
        sa.Column("astar_duration_s", sa.Float(), nullable=False),
        sa.Column("astar_exec_ms", sa.Float(), nullable=False),
        sa.Column("astar_nodes_visited", sa.Integer(), nullable=False),
        sa.Column("astar_edges_relaxed", sa.Integer(), nullable=False),
        sa.Column("astar_pq_pushes", sa.Integer(), nullable=False),
        sa.Column("astar_pq_pops", sa.Integer(), nullable=False),
        sa.Column("astar_heuristic_evals", sa.Integer(), nullable=False),
        sa.Column("astar_path_nodes", sa.Integer(), nullable=False),
        sa.Column("astar_turn_steps", sa.Integer(), nullable=False),
        sa.Column("exact_path_parity", sa.Boolean(), nullable=False),
        sa.Column("cost_delta_s", sa.Float(), nullable=False),
        sa.Column("distance_delta_m", sa.Float(), nullable=False),
        sa.Column("node_reduction_ratio", sa.Float(), nullable=False),
        sa.Column("speedup_factor", sa.Float(), nullable=False),
        sa.Column("road_detour_factor", sa.Float(), nullable=False),
        sa.Column("dominant_highway_type", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "simulation_recommender_comparisons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.String(length=80), nullable=True),
        sa.Column("context", sa.String(length=40), nullable=False),
        sa.Column("corpus_basket_count", sa.Integer(), nullable=False),
        sa.Column("min_support_used", sa.Float(), nullable=False),
        sa.Column("min_confidence_used", sa.Float(), nullable=False),
        sa.Column("target_product_ids_json", sa.JSON(), nullable=True),
        sa.Column("selected_algorithm", sa.String(length=20), nullable=False),
        sa.Column("co_algorithm", sa.String(length=20), nullable=False),
        sa.Column("apriori_exec_ms", sa.Float(), nullable=False),
        sa.Column("apriori_itemset_ms", sa.Float(), nullable=False),
        sa.Column("apriori_rule_ms", sa.Float(), nullable=False),
        sa.Column("apriori_frequent_items", sa.Integer(), nullable=False),
        sa.Column("apriori_frequent_itemsets", sa.Integer(), nullable=False),
        sa.Column("apriori_candidates_generated", sa.Integer(), nullable=False),
        sa.Column("apriori_candidates_pruned", sa.Integer(), nullable=False),
        sa.Column("apriori_db_scans", sa.Integer(), nullable=False),
        sa.Column("apriori_rules_count", sa.Integer(), nullable=False),
        sa.Column("apriori_avg_confidence", sa.Float(), nullable=False),
        sa.Column("apriori_avg_lift", sa.Float(), nullable=False),
        sa.Column("apriori_max_lift", sa.Float(), nullable=False),
        sa.Column("apriori_avg_conviction", sa.Float(), nullable=False),
        sa.Column("apriori_avg_zhang", sa.Float(), nullable=False),
        sa.Column("apriori_top_ids_json", sa.JSON(), nullable=True),
        sa.Column("apriori_rule_matched", sa.Integer(), nullable=False),
        sa.Column("fpgrowth_exec_ms", sa.Float(), nullable=False),
        sa.Column("fpgrowth_itemset_ms", sa.Float(), nullable=False),
        sa.Column("fpgrowth_rule_ms", sa.Float(), nullable=False),
        sa.Column("fpgrowth_frequent_items", sa.Integer(), nullable=False),
        sa.Column("fpgrowth_frequent_itemsets", sa.Integer(), nullable=False),
        sa.Column("fpgrowth_tree_nodes", sa.Integer(), nullable=False),
        sa.Column("fpgrowth_cond_trees_built", sa.Integer(), nullable=False),
        sa.Column("fpgrowth_cond_tree_nodes", sa.Integer(), nullable=False),
        sa.Column("fpgrowth_prefix_paths", sa.Integer(), nullable=False),
        sa.Column("fpgrowth_db_scans", sa.Integer(), nullable=False),
        sa.Column("fpgrowth_rules_count", sa.Integer(), nullable=False),
        sa.Column("fpgrowth_avg_confidence", sa.Float(), nullable=False),
        sa.Column("fpgrowth_avg_lift", sa.Float(), nullable=False),
        sa.Column("fpgrowth_max_lift", sa.Float(), nullable=False),
        sa.Column("fpgrowth_avg_conviction", sa.Float(), nullable=False),
        sa.Column("fpgrowth_avg_zhang", sa.Float(), nullable=False),
        sa.Column("fpgrowth_top_ids_json", sa.JSON(), nullable=True),
        sa.Column("fpgrowth_rule_matched", sa.Integer(), nullable=False),
        sa.Column("itemset_parity", sa.Boolean(), nullable=False),
        sa.Column("rule_parity", sa.Boolean(), nullable=False),
        sa.Column("top_k_jaccard_overlap", sa.Float(), nullable=False),
        sa.Column("top_k_exact_rank_match", sa.Boolean(), nullable=False),
        sa.Column("speedup_factor", sa.Float(), nullable=False),
        sa.Column("impressions_count", sa.Integer(), nullable=False),
        sa.Column("clicks_count", sa.Integer(), nullable=False),
        sa.Column("cart_adds_count", sa.Integer(), nullable=False),
        sa.Column("purchases_count", sa.Integer(), nullable=False),
        sa.Column("user_rating", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("simulation_recommender_comparisons")
    op.drop_table("simulation_routing_comparisons")
    op.drop_table("simulation_events")
    op.drop_table("simulation_runs")
