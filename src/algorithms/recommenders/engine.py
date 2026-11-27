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

    def compare_algorithms(
        self,
        baskets: list[Basket] | list[set[int]],
        target_product_ids: Sequence[int] | None = None,
        available_product_ids: Sequence[int] | None = None,
        limit: int = 6,
        selected: str | None = None,
    ) -> dict[str, Any]:
        """
        Executes a comprehensive side-by-side comparison of Apriori and FP-Growth
        on the exact same basket corpus and shopping context, alternating order
        to eliminate memory allocator / cache warm-up bias.
        """
        chosen = self.select_algorithm(selected)
        co_algo = "fpgrowth" if chosen == "apriori" else "apriori"

        if random.random() < 0.5:
            mine_a = self.mine(baskets, algorithm="apriori")
            mine_f = self.mine(baskets, algorithm="fpgrowth")
        else:
            mine_f = self.mine(baskets, algorithm="fpgrowth")
            mine_a = self.mine(baskets, algorithm="apriori")

        recs_a, _ = self.recommend(
            baskets=baskets,
            target_product_ids=target_product_ids,
            available_product_ids=available_product_ids,
            limit=limit,
            algorithm="apriori",
        )
        recs_f, _ = self.recommend(
            baskets=baskets,
            target_product_ids=target_product_ids,
            available_product_ids=available_product_ids,
            limit=limit,
            algorithm="fpgrowth",
        )

        def _rule_stats(rules: list[Rule]) -> dict[str, float]:
            if not rules:
                return {
                    "avg_confidence": 0.0,
                    "avg_lift": 0.0,
                    "max_lift": 0.0,
                    "avg_leverage": 0.0,
                    "avg_conviction": 0.0,
                    "avg_zhang": 0.0,
                    "avg_kulczynski": 0.0,
                    "avg_imbalance": 0.0,
                }
            n = len(rules)
            return {
                "avg_confidence": round(sum(r.confidence for r in rules) / n, 4),
                "avg_lift": round(sum(r.lift for r in rules) / n, 4),
                "max_lift": round(max(r.lift for r in rules), 4),
                "avg_leverage": round(sum(r.leverage for r in rules) / n, 5),
                "avg_conviction": round(sum(r.conviction for r in rules) / n, 4),
                "avg_zhang": round(sum(r.zhang for r in rules) / n, 4),
                "avg_kulczynski": round(sum(r.kulczynski for r in rules) / n, 4),
                "avg_imbalance": round(sum(r.imbalance for r in rules) / n, 4),
            }

        itemsets_a = set((mine_a.itemsets or {}).keys())
        itemsets_f = set((mine_f.itemsets or {}).keys())
        itemset_parity = (itemsets_a == itemsets_f)

        rules_sig_a = {(r.antecedent, r.consequent) for r in mine_a.rules}
        rules_sig_f = {(r.antecedent, r.consequent) for r in mine_f.rules}
        rule_parity = (rules_sig_a == rules_sig_f)

        top_a = [r.product_id for r in recs_a]
        top_f = [r.product_id for r in recs_f]
        union_set = set(top_a) | set(top_f)
        jaccard = (len(set(top_a) & set(top_f)) / len(union_set)) if union_set else 1.0
        exact_rank = (top_a == top_f)

        rule_matched_a = sum(1 for r in recs_a if r.reason.startswith("Frequently bought"))
        rule_matched_f = sum(1 for r in recs_f if r.reason.startswith("Frequently bought"))

        ms_a = mine_a.timings_ms.get("total_ms", 0.0)
        ms_f = mine_f.timings_ms.get("total_ms", 0.0)
        speedup = ms_a / max(0.0001, ms_f) if ms_f > 0 else 1.0

        return {
            "corpus_basket_count": mine_a.quality.kept,
            "selected_algorithm": chosen,
            "co_algorithm": co_algo,
            "apriori_mining": mine_a,
            "fpgrowth_mining": mine_f,
            "apriori_stats": _rule_stats(mine_a.rules),
            "fpgrowth_stats": _rule_stats(mine_f.rules),
            "apriori_top_ids": top_a,
            "fpgrowth_top_ids": top_f,
            "apriori_rule_matched": rule_matched_a,
            "fpgrowth_rule_matched": rule_matched_f,
            "itemset_parity": itemset_parity,
            "rule_parity": rule_parity,
            "top_k_jaccard_overlap": round(jaccard, 4),
            "top_k_exact_rank_match": exact_rank,
            "speedup_factor": round(speedup, 4),
        }
