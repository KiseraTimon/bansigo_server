# src/algorithms/recommenders/engine.py

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Sequence

from .apriori import AprioriRecommender
from .fpgrowth import FPGrowthRecommender
from .types import Basket, MiningConfig, MiningResult, Rule


@dataclass
class RecommendedProduct:
    product_id: int
    score: float
    algorithm: str  # "apriori" or "fpgrowth"
    reason: str
    recommendation_tag: str = "Recommended"


class HybridRecommenderEngine:
    """
    Facade coordinating Apriori and FP-Growth engines.
    Selected at random when generating recommendations to compare performance,
    study acceptance rates, helpfulness, and usability.
    """

    def __init__(self, config: MiningConfig | None = None):
        self.config = config or MiningConfig(
            min_support=0.01,
            min_support_count=1.0,
            min_confidence=0.1,
            min_lift=0.8,
            max_itemset_size=4,
        )
        self.apriori_engine = AprioriRecommender(self.config)
        self.fpgrowth_engine = FPGrowthRecommender(self.config)

    def select_algorithm(self, requested: str | None = None) -> str:
        """Selects algorithm; if not explicitly requested, picks randomly between apriori and fpgrowth."""
        if requested in ("apriori", "fpgrowth"):
            return requested
        return random.choice(["apriori", "fpgrowth"])

    def mine(self, baskets: list[Basket] | list[set[int]], algorithm: str = "fpgrowth") -> MiningResult:
        if algorithm == "apriori":
            return self.apriori_engine.mine(baskets)
        return self.fpgrowth_engine.mine(baskets)

    def recommend(
        self,
        baskets: list[Basket] | list[set[int]],
        target_product_ids: Sequence[int] | None = None,
        available_product_ids: Sequence[int] | None = None,
        limit: int = 6,
        algorithm: str | None = None,
    ) -> tuple[list[RecommendedProduct], str]:
        """
        Generates product recommendations using either Apriori or FP-Growth (selected randomly).
        Returns (list[RecommendedProduct], chosen_algorithm).
        """
        chosen_algorithm = self.select_algorithm(algorithm)
        mining_res = self.mine(baskets, algorithm=chosen_algorithm)

        target_set = set(target_product_ids or [])
        available_set = set(available_product_ids or []) if available_product_ids else None

        recommended_map: dict[int, tuple[float, str]] = {}

        # 1. Match association rules where antecedent is a subset of target products
        for rule in mining_res.rules:
            ante_set = set(rule.antecedent)
            if target_set and ante_set.issubset(target_set):
                for cons_item in rule.consequent:
                    if cons_item not in target_set:
                        if available_set is not None and cons_item not in available_set:
                            continue
                        score = rule.lift * rule.confidence
                        reason = f"Frequently bought with {list(rule.antecedent)}"
                        if cons_item not in recommended_map or score > recommended_map[cons_item][0]:
                            recommended_map[cons_item] = (score, reason)

        # 2. If not enough from rules, backfill from mined popular items
        if len(recommended_map) < limit:
            for item, supp in mining_res.popular:
                if item not in target_set and item not in recommended_map:
                    if available_set is not None and item not in available_set:
                        continue
                    recommended_map[item] = (supp * 10.0, "Popular customer choice")
                    if len(recommended_map) >= limit:
                        break

        # 3. If still empty (e.g. no orders yet), backfill from available product catalogue
        if len(recommended_map) < limit and available_set:
            shuffled_available = list(available_set - target_set)
            random.seed(42)  # stable deterministic fallback
            random.shuffle(shuffled_available)
            for item in shuffled_available:
                if item not in recommended_map:
                    recommended_map[item] = (1.0, "Customer favorite")
                    if len(recommended_map) >= limit:
                        break

        # Sort and format output
        sorted_items = sorted(recommended_map.items(), key=lambda x: x[1][0], reverse=True)[:limit]
        results = [
            RecommendedProduct(
                product_id=p_id,
                score=round(score_reason[0], 4),
                algorithm=chosen_algorithm,
                reason=score_reason[1],
                recommendation_tag="⭐ Recommended" if chosen_algorithm == "fpgrowth" else "AI Pick",
            )
            for p_id, score_reason in sorted_items
        ]

        return results, chosen_algorithm
