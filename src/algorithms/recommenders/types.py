# src/recommender/types.py

"""
shared types for the recommendation engines.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

Algorithm = Literal["apriori", "fpgrowth"]

EPS = 1e-9                  # tolerance for float comparisons against thresholds
CONVICTION_CAP = 999.0      # conviction is infinite when confidence == 1;


class InsufficientDataError(ValueError):
    """
    called when not enough clean baskets to mine anything meaningful
    """


@dataclass(frozen=True, slots=True)
class Basket:
    """
    one purchase: the SET of product ids bought together.
    """

    ref: str
    items: frozenset[int]
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class MiningConfig:
    """
    tuning for the recommender engines
    """

    algorithm: Algorithm = "fpgrowth"

    # frequent itemsets
    min_support: float = 0.01                  # fraction of (weighted) baskets
    min_support_count: float = 3.0             # absolute floor, in "full-weight" baskets
    max_itemset_size: int = 4
    max_basket_size: int = 60                       # bigger baskets (wholesale-like outliers)
    max_item_support: float | None = None      # drop near-ubiquitous items (carrier bags) before mining
    half_life_days: float | None = None        # recency weighting: a basket this old counts half as much

    # rules
    min_confidence: float = 0.3
    min_lift: float = 1.0
    max_antecedent_size: int = 3
    max_consequent_size: int = 1
    prune_redundant: bool = True
    min_improvement: float = 0.0
    max_rules: int = 50_000

    # data sufficiency / output
    min_transactions: int = 30
    popular_size: int = 100

    def __post_init__(self) -> None:
        if self.algorithm not in ("apriori", "fpgrowth"):
            raise ValueError("algorithm must be 'apriori' or 'fpgrowth'")
        if not 0 < self.min_support <= 1:
            raise ValueError("min_support must be in (0, 1]")
        if self.min_support_count < 1:
            raise ValueError("min_support_count must be >= 1")
        if not 0 < self.min_confidence <= 1:
            raise ValueError("min_confidence must be in (0, 1]")
        if self.min_lift < 0:
            raise ValueError("min_lift must be >= 0")
        if not 2 <= self.max_itemset_size <= 6:
            raise ValueError("max_itemset_size must be between 2 and 6")
        if self.max_antecedent_size < 1 or self.max_consequent_size < 1:
            raise ValueError("antecedent/consequent sizes must be >= 1")
        if self.max_item_support is not None and not 0 < self.max_item_support <= 1:
            raise ValueError("max_item_support must be in (0, 1]")
        if self.half_life_days is not None and self.half_life_days <= 0:
            raise ValueError("half_life_days must be > 0")
        if self.min_improvement < 0:
            raise ValueError("min_improvement must be >= 0")
        if self.max_basket_size < 2:
            raise ValueError("max_basket_size must be >= 2")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Rule:
    """
    maps the antecedent -> consequent of interestingness measures.
    All supports are fractions of the (recency-weighted) basket mass
    """

    antecedent: tuple[int, ...]
    consequent: tuple[int, ...]
    support: float                  # P(A and C)
    antecedent_support: float       # P(A)
    consequent_support: float       # P(C)
    confidence: float               # P(C | A)
    lift: float                     # P(C | A) / P(C); > 1; means there is a genuine positive association
    leverage: float                 # P(A and C) - P(A) P(C)
    conviction: float               # how much more often A would occur without C if they were independent
    zhang: float                    # Zhang's metric in [-1, 1]: robust to sparsity and imbalance
    kulczynski: float               # null-invariant: mean of P(C|A) and P(A|C)
    imbalance: float                # 0 = symmetric rule, 1 = completely lopsided
    rule_id: int | None = None           # database id once persisted


@dataclass(slots=True)
class DataQuality:
    """
    this class tracks which attribute are dropped and why
    """

    received: int = 0
    kept: int = 0
    duplicates: int = 0
    empty: int = 0
    oversized: int = 0


@dataclass(slots=True)
class MiningResult:
    """
    attributes of a complete mining process
    """

    config: MiningConfig
    rules: list[Rule]
    popular: list[tuple[int, float]]            # (product id, support); ranked by the most popular
    quality: DataQuality
    total_weight: float                         # recency-weighted basket mass (the support denominator)
    n_frequent_items: int
    n_itemsets: int
    timings_ms: dict[str, float] = field(default_factory=dict)
    itemsets: dict[tuple[int, ...], float] | None = None   # product-id space
