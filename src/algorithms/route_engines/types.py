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
    if street_name and street_name.strip() and street_name.strip().lower() not in ("none", "null"):
        return street_name.strip()
    tag = (highway_type or "road").lower().strip()
    mapping = {
        "trunk": "Main Highway",
        "trunk_link": "Main Highway",
        "primary": "Main Highway",
        "primary_link": "Main Highway",
        "secondary": "Arterial Road",
        "secondary_link": "Arterial Road",
        "tertiary": "Connecting Street",
        "tertiary_link": "Connecting Street",
        "residential": "Local Street",
        "living_street": "Local Street",
        "unclassified": "Local Street",
        "service": "Access Lane",
        "track": "Access Lane",
    }
    return mapping.get(tag, "Local Road")


def _step_bearing(step: "RouteStep") -> Optional[float]:
    if len(step.coordinates) >= 2 and step.coordinates[0] != step.coordinates[-1]:
        return _bearing_deg(step.coordinates[0], step.coordinates[-1])
    return None


def coalesce_route_steps(steps: list["RouteStep"]) -> list["RouteStep"]:
    """
    Merges consecutive micro-edges on the same road (or short <25m unnamed connectors)
    into meaningful navigation legs before generating turn-by-turn instructions.
    """
    if len(steps) <= 1:
        return steps

    merged: list[RouteStep] = [steps[0]]
    for nxt in steps[1:]:
        cur = merged[-1]
        cur_label = _format_road_label(cur.street_name, cur.highway_type)
        nxt_label = _format_road_label(nxt.street_name, nxt.highway_type)
        same_named = (
            cur.street_name
            and nxt.street_name
            and cur.street_name.strip().lower() == nxt.street_name.strip().lower()
        )
        same_label = cur_label == nxt_label

        b1 = _step_bearing(cur)
        b2 = _step_bearing(nxt)
        small_bend = (
            b1 is not None
            and b2 is not None
            and abs((b2 - b1 + 540.0) % 360.0 - 180.0) < 30.0
        )

        is_tiny_unnamed = (not nxt.street_name) and nxt.distance_m < 25.0
        if same_named or (same_label and small_bend) or is_tiny_unnamed:
            combined_coords = list(cur.coordinates)
            if nxt.coordinates:
                combined_coords.extend(nxt.coordinates[1:] if combined_coords else nxt.coordinates)
            cur.to_node = nxt.to_node
            cur.distance_m += nxt.distance_m
            cur.duration_s += nxt.duration_s
            cur.coordinates = combined_coords
            if not cur.street_name and nxt.street_name:
                cur.street_name = nxt.street_name
        else:
            merged.append(nxt)
    return merged


def populate_turn_instructions(steps: list["RouteStep"]) -> list["RouteStep"]:
    """Coalesces micro-edges and populates human-readable turn-by-turn instructions."""
    steps[:] = coalesce_route_steps(steps)
    prev_bearing: Optional[float] = None
    for idx, step in enumerate(steps):
        road_label = _format_road_label(step.street_name, step.highway_type)
        step.street_name = road_label

        curr_bearing = _step_bearing(step)

        if idx == 0 or prev_bearing is None or curr_bearing is None:
            direction = _compass_direction(curr_bearing) if curr_bearing is not None else ""
            step.maneuver_type = "straight"
            step.instruction = f"Head {direction} on {road_label}".strip() if direction else f"Head along {road_label}"
        else:
            delta = (curr_bearing - prev_bearing + 540.0) % 360.0 - 180.0
            abs_d = abs(delta)
            if abs_d < 25.0:
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
    nodes_visited: int = 0
    edges_relaxed: int = 0
    pq_pushes: int = 0
    pq_pops: int = 0
    heuristic_evals: int = 0
    execution_time_ms: float = 0.0

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
                "nodes_visited": self.nodes_visited,
                "edges_relaxed": self.edges_relaxed,
                "execution_time_ms": round(self.execution_time_ms, 4),
            },
            "geometry": {
                "type": "LineString",
                # GeoJSON coordinates order is [longitude, latitude]
                "coordinates": [[round(lon, 6), round(lat, 6)] for lat, lon in self.coordinates],
            },
        }
