# src/algorithms/route_engines/engine.py

from decimal import Decimal
from pathlib import Path
import random
from typing import Optional, Sequence
import networkx as nx
import osmnx as ox

from utilities import get_logger
from .a_star import AStarRouter
from .dijkstra import DijkstraRouter
from .spatial_index import SpatialIndex, haversine_distance_m
from .types import RouteResult, RoutingAlgorithm

log = get_logger(__name__)


def _build_fallback_graph(supermarket_lat: float, supermarket_lon: float) -> nx.MultiDiGraph:
    """
    Constructs a deterministic local road graph for test environments where graphml is not present.
    """
    g = nx.MultiDiGraph()
    # Central supermarket node
    center_id = 4408472422
    g.add_node(center_id, y=supermarket_lat, x=supermarket_lon, street_count=3)

    # 4 satellite nodes (North, South, East, West ~1km away)
    satellites = [
        (4408472423, supermarket_lat + 0.009, supermarket_lon, "residential", 1000.0, "North Road"),
        (4408472424, supermarket_lat - 0.009, supermarket_lon, "trunk", 1000.0, "Migori Highway"),
        (4408472425, supermarket_lat, supermarket_lon + 0.009, "secondary", 1000.0, "East Avenue"),
        (4408472426, supermarket_lat, supermarket_lon - 0.009, "tertiary", 1000.0, "Market Street"),
    ]

    for nid, lat, lon, hway, dist, name in satellites:
        g.add_node(nid, y=lat, x=lon, street_count=2)
        # Bidirectional edges
        g.add_edge(center_id, nid, key=0, length=dist, highway=hway, name=name, oneway=False)
        g.add_edge(nid, center_id, key=0, length=dist, highway=hway, name=name, oneway=False)

    return g


class RoadNetworkRouter:
    """
    Main road network routing facade coordinating OSMnx graph topology, spatial indices,
    Dijkstra, A*, randomized engine selection, and rider dispatch assignment.
    """

    def __init__(
        self,
        graphml_path: Path | str,
        supermarket_coords: tuple[float, float] = (-1.061219, 34.474196),
        max_delivery_radius_km: float = 7.0,
        base_delivery_fee: Decimal = Decimal("50.00"),
        delivery_fee_per_km: Decimal = Decimal("20.00"),
    ):
        self.graphml_path = Path(graphml_path)
        self.supermarket_coords = supermarket_coords
        self.max_delivery_radius_km = max_delivery_radius_km
        self.base_delivery_fee = base_delivery_fee
        self.delivery_fee_per_km = delivery_fee_per_km

        self.dijkstra = DijkstraRouter()
        self.astar = AStarRouter()

        self.graph = self._load_graph()
        self.spatial_index = self._build_spatial_index()
        self.supermarket_node, _ = self.spatial_index.find_nearest_node(*self.supermarket_coords)

        log.info(
            "RoadNetworkRouter initialized with %d nodes, %d edges. Supermarket node: %s",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
            self.supermarket_node,
        )

    def _load_graph(self) -> nx.MultiDiGraph:
        if self.graphml_path.exists():
            log.info("Loading road graph from %s...", self.graphml_path)
            try:
                g = ox.load_graphml(self.graphml_path)
                if len(g.nodes) > 0:
                    sample_node = next(iter(g.nodes))
                    node_lat = float(g.nodes[sample_node]["y"])
                    node_lon = float(g.nodes[sample_node]["x"])
                    dist_to_graph = haversine_distance_m(self.supermarket_coords[0], self.supermarket_coords[1], node_lat, node_lon)
                    if dist_to_graph <= 50000.0:
                        return g
                    log.warning(
                        "GraphML %s is centered around (%.4f, %.4f), but supermarket is at (%.4f, %.4f) (~%.1f km away). Initializing localized road graph.",
                        self.graphml_path, node_lat, node_lon, self.supermarket_coords[0], self.supermarket_coords[1], dist_to_graph / 1000.0
                    )
                    return _build_fallback_graph(self.supermarket_coords[0], self.supermarket_coords[1])
                return g
            except Exception as e:
                log.warning("Failed loading graphml from %s (%s). Using fallback.", self.graphml_path, e)

        log.warning("GraphML file %s not found. Initializing fallback road graph.", self.graphml_path)
        return _build_fallback_graph(self.supermarket_coords[0], self.supermarket_coords[1])

    def _build_spatial_index(self) -> SpatialIndex:
        node_ids = list(self.graph.nodes)
        lats = [float(self.graph.nodes[n]["y"]) for n in node_ids]
        lons = [float(self.graph.nodes[n]["x"]) for n in node_ids]
        return SpatialIndex(node_ids, lats, lons)

    def is_within_coverage(self, lat: float, lon: float) -> tuple[bool, float]:
        """
        Validates if coordinate is within the 7km delivery radius of Bansi Mega Supermarket.
        Returns: (is_within, distance_meters)
        """
        return self.spatial_index.is_within_radius(
            lat,
            lon,
            self.supermarket_coords[0],
            self.supermarket_coords[1],
            self.max_delivery_radius_km,
        )

    def calculate_delivery_fee(self, distance_m: float) -> Decimal:
        """
        Computes dynamic delivery fee: Base KES 50 + KES 20/km rounded to whole shillings.
        """
        km = Decimal(str(max(0.0, distance_m / 1000.0)))
        fee = self.base_delivery_fee + (km * self.delivery_fee_per_km)
        return Decimal(round(fee))

    def find_route(
        self,
        source_lat: float,
        source_lon: float,
        target_lat: float,
        target_lon: float,
        algorithm: Optional[RoutingAlgorithm] = None,
        weight: str = "travel_time",
    ) -> RouteResult:
        """
        Calculates optimal route between two coordinates. If algorithm is not specified,
        randomly selects between Dijkstra and A* as required by dispatch policy.
        """
        source_node, _ = self.spatial_index.find_nearest_node(source_lat, source_lon)
        target_node, _ = self.spatial_index.find_nearest_node(target_lat, target_lon)

        chosen_algo = algorithm or random.choice([RoutingAlgorithm.DIJKSTRA, RoutingAlgorithm.A_STAR])

        if chosen_algo == RoutingAlgorithm.A_STAR:
            result = self.astar.find_route(self.graph, source_node, target_node, weight=weight)
        else:
            result = self.dijkstra.find_route(self.graph, source_node, target_node, weight=weight)

        return result

    def route_from_supermarket(
        self,
        target_lat: float,
        target_lon: float,
        algorithm: Optional[RoutingAlgorithm] = None,
    ) -> RouteResult:
        """
        Routes directly from Bansi Mega Supermarket to customer dropoff location.
        Randomly assigns Dijkstra or A* if algorithm is None.
        """
        return self.find_route(
            source_lat=self.supermarket_coords[0],
            source_lon=self.supermarket_coords[1],
            target_lat=target_lat,
            target_lon=target_lon,
            algorithm=algorithm,
            weight="travel_time",
        )

    def select_best_rider(
        self,
        riders: Sequence[Any],
        target_lat: float,
        target_lon: float,
    ) -> Optional[tuple[Any, RouteResult, RouteResult]]:
        """
        Identifies the optimal rider for a dispatch job by computing ETA from rider to supermarket,
        combined with delivery route from supermarket to customer destination.
        Returns: (best_rider, route_to_supermarket, route_to_customer) or None
        """
        candidates = [
            r for r in riders
            if getattr(r, "last_latitude", None) is not None
            and getattr(r, "last_longitude", None) is not None
        ]
        if not candidates:
            return None

        # Route from supermarket to customer
        store_to_customer = self.route_from_supermarket(target_lat, target_lon)

        best_rider = None
        best_rider_route = None
        min_total_duration = float("inf")

        for rider in candidates:
            r_lat = float(rider.last_latitude)
            r_lon = float(rider.last_longitude)

            try:
                # Route from rider's current position to supermarket
                rider_to_store = self.find_route(
                    source_lat=r_lat,
                    source_lon=r_lon,
                    target_lat=self.supermarket_coords[0],
                    target_lon=self.supermarket_coords[1],
                )
                total_duration = rider_to_store.total_duration_s + store_to_customer.total_duration_s

                # Small tie-breaking adjustment for higher rated riders
                rating = float(getattr(rider, "rating_average", 0.0) or 0.0)
                score = total_duration - (rating * 30.0)  # 30 second bonus per star

                if score < min_total_duration:
                    min_total_duration = score
                    best_rider = rider
                    best_rider_route = rider_to_store
            except Exception as e:
                log.warning("Could not calculate route for rider %s: %s", getattr(rider, "id", None), e)

        if best_rider and best_rider_route:
            return best_rider, best_rider_route, store_to_customer

        return None
