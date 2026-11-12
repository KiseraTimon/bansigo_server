# src/algorithms/route_engines/types.py

import enum
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


class RoutingAlgorithm(str, enum.Enum):
    """
    Supported shortest path routing engines.
    """
    DIJKSTRA = "dijkstra"
    A_STAR = "a_star"


@dataclass
class RouteStep:
    """
    Represents an atomic edge segment / manoeuvre along a traversed road route.
    """
    from_node: int
    to_node: int
    street_name: Optional[str]
    highway_type: str
    distance_m: float
    duration_s: float
    speed_kmh: float
    coordinates: list[tuple[float, float]] = field(default_factory=list)  # (lat, lon) sequence

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_node": self.from_node,
            "to_node": self.to_node,
            "street_name": self.street_name,
            "highway_type": self.highway_type,
            "distance_m": round(self.distance_m, 1),
            "duration_s": round(self.duration_s, 1),
            "speed_kmh": round(self.speed_kmh, 1),
            "coordinates": [[round(lat, 6), round(lon, 6)] for lat, lon in self.coordinates],
        }


@dataclass
class RouteResult:
    """
    Output of a routing engine execution containing metrics, path nodes, coordinates, and turn steps.
    """
    algorithm: RoutingAlgorithm
    source_node: int
    target_node: int
    total_distance_m: float
    total_duration_s: float
    node_path: list[int]
    coordinates: list[tuple[float, float]]  # (latitude, longitude) sequence
    steps: list[RouteStep] = field(default_factory=list)

    @property
    def estimated_minutes(self) -> int:
        return max(1, round(self.total_duration_s / 60))

    def to_waypoints_list(self) -> list[list[float]]:
        """Returns sequence of [latitude, longitude] pairs suitable for JSON / map polylines."""
        return [[round(lat, 6), round(lon, 6)] for lat, lon in self.coordinates]

    def to_waypoints_json(self) -> str:
        """Serializes waypoints to a compact JSON string for database persistence."""
        return json.dumps(self.to_waypoints_list())

    def to_geojson(self) -> dict[str, Any]:
        """Returns standard GeoJSON LineString feature for mapping interfaces."""
        return {
            "type": "Feature",
            "properties": {
                "algorithm": self.algorithm.value,
                "distance_m": round(self.total_distance_m, 1),
                "duration_s": round(self.total_duration_s, 1),
                "estimated_minutes": self.estimated_minutes,
                "node_count": len(self.node_path),
            },
            "geometry": {
                "type": "LineString",
                # GeoJSON coordinates order is [longitude, latitude]
                "coordinates": [[round(lon, 6), round(lat, 6)] for lat, lon in self.coordinates],
            },
        }
