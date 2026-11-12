# src/algorithms/recommenders/apriori.py

from __future__ import annotations

import itertools
from collections import defaultdict

from .types import Basket, MiningConfig, MiningResult, Rule, DataQuality, CONVICTION_CAP


class AprioriRecommender:
    """
    Complete Apriori association rule mining algorithm.
    Generates frequent itemsets and derives association rules evaluated
    by support, confidence, lift, leverage, and conviction.
    """

    def __init__(self, config: MiningConfig | None = None):
        self.config = config or MiningConfig(
            algorithm="apriori",
            min_support=0.02,
            min_confidence=0.2,
            min_lift=1.0,
            max_itemset_size=4,
        )

    def mine(self, baskets: list[Basket] | list[set[int]]) -> MiningResult:
        quality = DataQuality(received=len(baskets))
        clean_baskets: list[frozenset[int]] = []

        for b in baskets:
            items = b.items if isinstance(b, Basket) else frozenset(b)
            if not items:
                quality.empty += 1
                continue
            if len(items) > self.config.max_basket_size:
                quality.oversized += 1
                continue
            clean_baskets.append(items)

        quality.kept = len(clean_baskets)
        n_baskets = len(clean_baskets)
        if n_baskets == 0:
            return MiningResult(
                config=self.config,
                rules=[],
                popular=[],
                quality=quality,
                total_weight=0.0,
                n_frequent_items=0,
                n_itemsets=0,
                itemsets={},
            )

        min_count = max(self.config.min_support * n_baskets, self.config.min_support_count)

        # 1. Frequent 1-itemsets
        item_counts: dict[int, int] = defaultdict(int)
        for basket in clean_baskets:
            for item in basket:
                item_counts[item] += 1

        # Popular single items ranked
        popular = sorted(
            [(item, count / n_baskets) for item, count in item_counts.items()],
            key=lambda x: x[1],
            reverse=True,
        )[: self.config.popular_size]

        frequent_itemsets: dict[frozenset[int], float] = {}
        current_l: set[frozenset[int]] = set()

        for item, count in item_counts.items():
            if count >= min_count:
                fs = frozenset([item])
                supp = count / n_baskets
                frequent_itemsets[fs] = supp
                current_l.add(fs)

        n_frequent_items = len(current_l)

        # 2. Frequent k-itemsets (k >= 2)
        k = 2
        while current_l and k <= self.config.max_itemset_size:
            # Candidate generation: join step
            candidates: set[frozenset[int]] = set()
            l_list = list(current_l)
            for i in range(len(l_list)):
                for j in range(i + 1, len(l_list)):
                    union = l_list[i] | l_list[j]
                    if len(union) == k:
                        # Prune step: all (k-1) subsets must be in current_l
                        subsets_ok = True
                        for item in union:
                            if (union - frozenset([item])) not in current_l:
                                subsets_ok = False
                                break
                        if subsets_ok:
                            candidates.add(union)

            if not candidates:
                break

            # Count support for candidates
            candidate_counts: dict[frozenset[int], int] = defaultdict(int)
            for basket in clean_baskets:
                for cand in candidates:
                    if cand.issubset(basket):
                        candidate_counts[cand] += 1

            next_l: set[frozenset[int]] = set()
            for cand, count in candidate_counts.items():
                if count >= min_count:
                    supp = count / n_baskets
                    frequent_itemsets[cand] = supp
                    next_l.add(cand)

            current_l = next_l
            k += 1

        # 3. Association rule generation
        rules: list[Rule] = []
        for itemset, supp in frequent_itemsets.items():
            if len(itemset) < 2:
                continue

            for r in range(1, min(len(itemset), self.config.max_antecedent_size + 1)):
                for ante_combo in itertools.combinations(itemset, r):
                    ante = frozenset(ante_combo)
                    cons = itemset - ante
                    if len(cons) > self.config.max_consequent_size or len(cons) == 0:
                        continue

                    ante_supp = frequent_itemsets.get(ante)
                    if not ante_supp or ante_supp == 0:
                        continue

                    confidence = supp / ante_supp
                    if confidence < self.config.min_confidence:
                        continue

                    cons_supp = frequent_itemsets.get(cons, 0.0)
                    if cons_supp == 0:
                        continue

                    lift = confidence / cons_supp
                    if lift < self.config.min_lift:
                        continue

                    leverage = supp - (ante_supp * cons_supp)
                    conviction = (
                        CONVICTION_CAP
                        if (1.0 - confidence) == 0
                        else min(CONVICTION_CAP, (1.0 - cons_supp) / (1.0 - confidence))
                    )

                    denom = max(supp * (1.0 - ante_supp), ante_supp * (cons_supp - supp))
                    zhang = (supp - ante_supp * cons_supp) / denom if denom > 0 else 0.0

                    rev_conf = supp / cons_supp if cons_supp > 0 else 0.0
                    kulczynski = 0.5 * (confidence + rev_conf)
                    imbalance = abs(ante_supp - cons_supp) / (ante_supp + cons_supp - supp) if (ante_supp + cons_supp - supp) > 0 else 0.0

                    rule = Rule(
                        antecedent=tuple(sorted(ante)),
                        consequent=tuple(sorted(cons)),
                        support=supp,
                        antecedent_support=ante_supp,
                        consequent_support=cons_supp,
                        confidence=confidence,
                        lift=lift,
                        leverage=leverage,
                        conviction=conviction,
                        zhang=zhang,
                        kulczynski=kulczynski,
                        imbalance=imbalance,
                    )
                    rules.append(rule)
                    if len(rules) >= self.config.max_rules:
                        break

        rules.sort(key=lambda r: (r.lift * r.confidence, r.support), reverse=True)

        return MiningResult(
            config=self.config,
            rules=rules,
            popular=popular,
            quality=quality,
            total_weight=float(n_baskets),
            n_frequent_items=n_frequent_items,
            n_itemsets=len(frequent_itemsets),
            itemsets={tuple(sorted(k)): v for k, v in frequent_itemsets.items()},
        )
