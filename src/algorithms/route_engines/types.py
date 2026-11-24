# src/algorithms/route_engines/types.py

import enum
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


class RoutingAlgorithm(str, enum.Enum):
    """
    Supported shortest path routing engines.
    """
    DIJKSTRA = "dijkstra"
    A_STAR = "a_star"


def _bearing_deg(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Computes initial compass bearing in degrees [0, 360) from p1=(lat, lon) to p2=(lat, lon)."""
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _compass_direction(bearing: float) -> str:
    dirs = ["North", "Northeast", "East", "Southeast", "South", "Southwest", "West", "Northwest"]
    return dirs[int((bearing + 22.5) // 45) % 8]


def _format_road_label(street_name: Optional[str], highway_type: str) -> str:
    if street_name and street_name.strip() and street_name.strip().lower() != "none":
        return street_name.strip()
    cleaned = (highway_type or "road").replace("_", " ").strip().title()
    return f"{cleaned} Road" if "road" not in cleaned.lower() and "street" not in cleaned.lower() else cleaned


def populate_turn_instructions(steps: list["RouteStep"]) -> list["RouteStep"]:
    """Populates human-readable turn-by-turn instructions and maneuver types from edge bearings."""
    prev_bearing: Optional[float] = None
    for idx, step in enumerate(steps):
        road_label = _format_road_label(step.street_name, step.highway_type)
        if not step.street_name:
            step.street_name = road_label

        curr_bearing: Optional[float] = None
        if len(step.coordinates) >= 2 and step.coordinates[0] != step.coordinates[-1]:
            curr_bearing = _bearing_deg(step.coordinates[0], step.coordinates[-1])

        if idx == 0 or prev_bearing is None or curr_bearing is None:
            direction = _compass_direction(curr_bearing) if curr_bearing is not None else ""
            step.maneuver_type = "straight"
            step.instruction = f"Head {direction} on {road_label}".strip() if direction else f"Head along {road_label}"
        else:
            delta = (curr_bearing - prev_bearing + 540.0) % 360.0 - 180.0
            abs_d = abs(delta)
            if abs_d < 20.0:
                step.maneuver_type = "straight"
                step.instruction = f"Continue on {road_label}"
            elif delta > 0:
                if abs_d < 55.0:
                    step.maneuver_type = "slight_right"
                    step.instruction = f"Keep right onto {road_label}"
                elif abs_d < 130.0:
                    step.maneuver_type = "turn_right"
                    step.instruction = f"Turn right onto {road_label}"
                else:
                    step.maneuver_type = "sharp_right"
                    step.instruction = f"Sharp right onto {road_label}"
            else:
                if abs_d < 55.0:
                    step.maneuver_type = "slight_left"
                    step.instruction = f"Keep left onto {road_label}"
                elif abs_d < 130.0:
                    step.maneuver_type = "turn_left"
                    step.instruction = f"Turn left onto {road_label}"
                else:
                    step.maneuver_type = "sharp_left"
                    step.instruction = f"Sharp left onto {road_label}"

        if curr_bearing is not None:
            prev_bearing = curr_bearing
    return steps


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
    instruction: str = ""
    maneuver_type: str = "straight"

    def to_dict(self) -> dict[str, Any]:
        road_label = _format_road_label(self.street_name, self.highway_type)
        return {
            "from_node": self.from_node,
            "to_node": self.to_node,
            "street_name": road_label,
            "highway_type": self.highway_type,
            "instruction": self.instruction or f"Continue on {road_label}",
            "type": self.maneuver_type or "straight",
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
