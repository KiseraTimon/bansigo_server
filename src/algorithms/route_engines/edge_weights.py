# src/algorithms/route_engines/edge_weights.py

import re
from typing import Any, Union

# Highway classification baseline speeds (km/h) for urban & semi-urban Kenya road topology
DEFAULT_HIGHWAY_SPEEDS_KMH: dict[str, float] = {
    "motorway": 90.0,
    "motorway_link": 60.0,
    "trunk": 80.0,
    "trunk_link": 50.0,
    "primary": 60.0,
    "primary_link": 45.0,
    "secondary": 50.0,
    "secondary_link": 35.0,
    "tertiary": 40.0,
    "tertiary_link": 30.0,
    "residential": 30.0,
    "unclassified": 25.0,
    "living_street": 15.0,
    "service": 15.0,
    "track": 15.0,
    "road": 30.0,
}

# Theoretical network maximum speed in m/s used to maintain admissibility in A* heuristics
MAX_NETWORK_SPEED_MPS: float = 90.0 * 1000.0 / 3600.0  # 25.0 m/s

# Road surface deceleration factor (unpaved roads induce significant impedance)
SURFACE_PENALTY_FACTORS: dict[str, float] = {
    "paved": 1.0,
    "asphalt": 1.0,
    "concrete": 1.0,
    "paving_stones": 1.15,
    "sett": 1.20,
    "cobblestone": 1.25,
    "unpaved": 1.35,
    "compacted": 1.25,
    "gravel": 1.35,
    "fine_gravel": 1.30,
    "dirt": 1.40,
    "earth": 1.45,
    "ground": 1.40,
    "sand": 1.50,
}


def _extract_highway_tag(edge_data: dict[str, Any]) -> str:
    """Extracts scalar highway string even if OSMnx supplies a list."""
    val = edge_data.get("highway", "unclassified")
    if isinstance(val, list):
        val = val[0] if val else "unclassified"
    return str(val).lower()


def _parse_maxspeed(raw_speed: Any) -> float | None:
    """Safely extracts km/h numeric speed from raw OSM maxspeed tags."""
    if raw_speed is None:
        return None
    if isinstance(raw_speed, (int, float)):
        return float(raw_speed) if raw_speed > 0 else None
    if isinstance(raw_speed, list):
        for item in raw_speed:
            parsed = _parse_maxspeed(item)
            if parsed is not None:
                return parsed
        return None

    speed_str = str(raw_speed).strip().lower()
    if not speed_str or speed_str == "none":
        return None

    # Handle mph conversion if specified
    if "mph" in speed_str:
        match = re.search(r"(\d+(?:\.\d+)?)", speed_str)
        if match:
            return float(match.group(1)) * 1.60934

    match = re.search(r"(\d+(?:\.\d+)?)", speed_str)
    if match:
        return float(match.group(1))
    return None


def calculate_edge_speed_kmh(edge_data: dict[str, Any]) -> float:
    """
    Determines effective vehicular speed in km/h from maxspeed or highway classification.
    """
    parsed_speed = _parse_maxspeed(edge_data.get("maxspeed"))
    if parsed_speed is not None and 10.0 <= parsed_speed <= 120.0:
        return parsed_speed

    highway = _extract_highway_tag(edge_data)
    return DEFAULT_HIGHWAY_SPEEDS_KMH.get(highway, 25.0)


def calculate_surface_penalty(edge_data: dict[str, Any]) -> float:
    """
    Computes road friction and surface impedance factor.
    """
    surface = edge_data.get("surface")
    if isinstance(surface, list):
        surface = surface[0] if surface else None
    if surface:
        surface_str = str(surface).lower().strip()
        return SURFACE_PENALTY_FACTORS.get(surface_str, 1.2)

    # If surface tag is missing, infer from highway classification
    highway = _extract_highway_tag(edge_data)
    if highway in ("track", "unclassified"):
        return 1.3
    return 1.0


def calculate_edge_length_m(edge_data: dict[str, Any]) -> float:
    """Returns edge length in meters, guaranteed strictly positive."""
    length = edge_data.get("length", 1.0)
    try:
        val = float(length)
        return max(0.1, val)
    except (ValueError, TypeError):
        return 10.0


def calculate_edge_travel_time_s(edge_data: dict[str, Any]) -> float:
    """
    Computes realistic traversal time in seconds taking length, speed, and surface impedance into account.
    """
    length_m = calculate_edge_length_m(edge_data)
    speed_kmh = calculate_edge_speed_kmh(edge_data)
    surface_factor = calculate_surface_penalty(edge_data)

    speed_mps = max(2.0, (speed_kmh * 1000.0) / 3600.0)
    travel_time_s = (length_m / speed_mps) * surface_factor
    return max(0.1, travel_time_s)


def calculate_edge_weight(edge_data: dict[str, Any], weight_type: str = "travel_time") -> float:
    """
    Returns edge impedance value for routing calculations.
    Supported types: 'travel_time' (seconds), 'distance' (meters).
    """
    if weight_type == "distance" or weight_type == "length":
        return calculate_edge_length_m(edge_data)
    return calculate_edge_travel_time_s(edge_data)
