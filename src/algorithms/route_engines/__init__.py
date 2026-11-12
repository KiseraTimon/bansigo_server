# src/algorithms/route_engines/__init__.py

from pathlib import Path
from typing import Optional

from config import get_settings
from .a_star import AStarRouter
from .dijkstra import DijkstraRouter
from .edge_weights import (
    DEFAULT_HIGHWAY_SPEEDS_KMH,
    MAX_NETWORK_SPEED_MPS,
    calculate_edge_length_m,
    calculate_edge_speed_kmh,
    calculate_edge_travel_time_s,
    calculate_edge_weight,
)
from .engine import RoadNetworkRouter
from .spatial_index import SpatialIndex, haversine_distance_m
from .types import RouteResult, RouteStep, RoutingAlgorithm

_ROUTER_INSTANCE: Optional[RoadNetworkRouter] = None


def init_router(
    graphml_path: Optional[Path | str] = None,
    supermarket_coords: Optional[tuple[float, float]] = None,
    max_delivery_radius_km: Optional[float] = None,
) -> RoadNetworkRouter:
    """
    Initializes and caches the singleton RoadNetworkRouter. Called during FastAPI lifespan startup.
    """
    global _ROUTER_INSTANCE
    settings = get_settings()

    path = graphml_path or settings.road_network_graphml_path
    coords = supermarket_coords or (float(settings.supermarket_latitude), float(settings.supermarket_longitude))
    radius = max_delivery_radius_km or settings.delivery_max_radius_km

    _ROUTER_INSTANCE = RoadNetworkRouter(
        graphml_path=path,
        supermarket_coords=coords,
        max_delivery_radius_km=radius,
        base_delivery_fee=settings.delivery_base_fee,
        delivery_fee_per_km=settings.delivery_fee_per_km,
    )
    return _ROUTER_INSTANCE


def get_router() -> RoadNetworkRouter:
    """
    Provides access to the active RoadNetworkRouter singleton. Lazily initializes if not yet created.
    """
    global _ROUTER_INSTANCE
    if _ROUTER_INSTANCE is None:
        _ROUTER_INSTANCE = init_router()
    return _ROUTER_INSTANCE


__all__ = [
    "AStarRouter",
    "DEFAULT_HIGHWAY_SPEEDS_KMH",
    "DijkstraRouter",
    "MAX_NETWORK_SPEED_MPS",
    "RoadNetworkRouter",
    "RouteResult",
    "RouteStep",
    "RoutingAlgorithm",
    "SpatialIndex",
    "calculate_edge_length_m",
    "calculate_edge_speed_kmh",
    "calculate_edge_travel_time_s",
    "calculate_edge_weight",
    "get_router",
    "haversine_distance_m",
    "init_router",
]
