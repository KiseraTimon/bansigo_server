# src/algorithms/recommenders/fpgrowth.py

from __future__ import annotations

import itertools
from collections import defaultdict
from typing import Optional

from .types import Basket, MiningConfig, MiningResult, Rule, DataQuality, CONVICTION_CAP


class FPNode:
    """A node in the Frequent Pattern Tree."""

    def __init__(self, item: int | None, count: int, parent: Optional[FPNode] = None):
        self.item = item
        self.count = count
        self.parent = parent
        self.children: dict[int, FPNode] = {}
        self.node_link: Optional[FPNode] = None

    def increment(self, count: int = 1) -> None:
        self.count += count


class FPTree:
    """Frequent Pattern Tree data structure for FP-Growth."""

    def __init__(self):
        self.root = FPNode(item=None, count=0)
        # item -> [count, head_node]
        self.header_table: dict[int, list] = {}

    def insert_transaction(self, transaction: list[int], count: int = 1) -> None:
        curr = self.root
        for item in transaction:
            if item in curr.children:
                curr.children[item].increment(count)
            else:
                new_node = FPNode(item=item, count=count, parent=curr)
                curr.children[item] = new_node

                # Link in header table
                if item in self.header_table:
                    if self.header_table[item][1] is None:
                        self.header_table[item][1] = new_node
                    else:
                        ptr = self.header_table[item][1]
                        while ptr.node_link is not None:
                            ptr = ptr.node_link
                        ptr.node_link = new_node
            curr = curr.children[item]

    def find_prefix_paths(self, item: int) -> list[tuple[list[int], int]]:
        """Collects prefix paths for an item from its node-link chain."""
        prefix_paths: list[tuple[list[int], int]] = []
        node = self.header_table.get(item, [0, None])[1]

        while node is not None:
            path: list[int] = []
            curr = node.parent
            while curr is not None and curr.item is not None:
                path.append(curr.item)
                curr = curr.parent
            if path:
                prefix_paths.append((list(reversed(path)), node.count))
            node = node.node_link

        return prefix_paths


class FPGrowthRecommender:
    """
    Complete FP-Growth association rule mining algorithm.
    Builds an FP-Tree, extracts frequent itemsets recursively via conditional FP-Trees,
    and mines high-confidence, high-lift association rules.
    """

    def __init__(self, config: MiningConfig | None = None):
        self.config = config or MiningConfig(
            algorithm="fpgrowth",
            min_support=0.02,
            min_confidence=0.2,
            min_lift=1.0,
            max_itemset_size=4,
        )

    def mine(self, baskets: list[Basket] | list[set[int]]) -> MiningResult:
        quality = DataQuality(received=len(baskets))
        clean_baskets: list[list[int]] = []

        for b in baskets:
            items = b.items if isinstance(b, Basket) else frozenset(b)
            if not items:
                quality.empty += 1
                continue
            if len(items) > self.config.max_basket_size:
                quality.oversized += 1
                continue
            clean_baskets.append(list(items))

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

        # 1. Count 1-item frequencies
        item_counts: dict[int, int] = defaultdict(int)
        for basket in clean_baskets:
            for item in basket:
                item_counts[item] += 1

        popular = sorted(
            [(item, count / n_baskets) for item, count in item_counts.items()],
            key=lambda x: x[1],
            reverse=True,
        )[: self.config.popular_size]

        frequent_items = {item: count for item, count in item_counts.items() if count >= min_count}
        n_frequent_items = len(frequent_items)

        if not frequent_items:
            return MiningResult(
                config=self.config,
                rules=[],
                popular=popular,
                quality=quality,
                total_weight=float(n_baskets),
                n_frequent_items=0,
                n_itemsets=0,
                itemsets={},
            )

        # 2. Build initial FP-Tree
        fp_tree = FPTree()
        for item, count in frequent_items.items():
            fp_tree.header_table[item] = [count, None]

        for basket in clean_baskets:
            # Sort frequent items in descending order of frequency
            sorted_items = [item for item in basket if item in frequent_items]
            sorted_items.sort(key=lambda x: (frequent_items[x], -x), reverse=True)
            if sorted_items:
                fp_tree.insert_transaction(sorted_items, count=1)

        # 3. Mine frequent itemsets recursively
        frequent_itemsets: dict[frozenset[int], float] = {}

        # Frequent 1-itemsets
        for item, count in frequent_items.items():
            frequent_itemsets[frozenset([item])] = count / n_baskets

        def _mine_tree(tree: FPTree, prefix: frozenset[int]) -> None:
            if len(prefix) >= self.config.max_itemset_size:
                return

            # Process items in header table ordered by ascending frequency
            sorted_header_items = sorted(
                tree.header_table.keys(),
                key=lambda x: tree.header_table[x][0],
            )

            for item in sorted_header_items:
                count = tree.header_table[item][0]
                new_prefix = prefix | frozenset([item])
                frequent_itemsets[new_prefix] = count / n_baskets

                if len(new_prefix) >= self.config.max_itemset_size:
                    continue

                # Build conditional pattern base
                prefix_paths = tree.find_prefix_paths(item)
                if not prefix_paths:
                    continue

                # Count items in conditional pattern base
                cond_counts: dict[int, int] = defaultdict(int)
                for path, path_count in prefix_paths:
                    for p_item in path:
                        cond_counts[p_item] += path_count

                # Filter conditional frequent items
                cond_frequent = {p: c for p, c in cond_counts.items() if c >= min_count}
                if not cond_frequent:
                    continue

                # Build conditional FP-tree
                cond_tree = FPTree()
                for c_item, c_count in cond_frequent.items():
                    cond_tree.header_table[c_item] = [c_count, None]

                for path, path_count in prefix_paths:
                    sorted_path = [p for p in path if p in cond_frequent]
                    sorted_path.sort(key=lambda x: (cond_frequent[x], -x), reverse=True)
                    if sorted_path:
                        cond_tree.insert_transaction(sorted_path, count=path_count)

                _mine_tree(cond_tree, new_prefix)

        _mine_tree(fp_tree, frozenset())

        # 4. Association rule generation
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
