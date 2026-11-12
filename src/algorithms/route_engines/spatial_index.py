# src/algorithms/route_engines/spatial_index.py

import math
from typing import Sequence
import numpy as np


EARTH_RADIUS_METERS: float = 6371000.0


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes great-circle distance between two geographic coordinates in meters.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


class SpatialIndex:
    """
    Vectorized NumPy spatial index for sub-millisecond nearest-node lookups across OSM road graph vertices.
    """

    def __init__(self, node_ids: Sequence[int], latitudes: Sequence[float], longitudes: Sequence[float]):
        self.node_ids = np.array(node_ids, dtype=np.int64)
        self.latitudes = np.array(latitudes, dtype=np.float64)
        self.longitudes = np.array(longitudes, dtype=np.float64)
        self.lat_rad = np.radians(self.latitudes)
        self.lon_rad = np.radians(self.longitudes)

    def find_nearest_node(self, target_lat: float, target_lon: float) -> tuple[int, float]:
        """
        Finds the closest road graph vertex to the given (latitude, longitude) coordinate.
        Returns: (nearest_node_id, distance_in_meters)
        """
        if len(self.node_ids) == 0:
            raise ValueError("Spatial index contains no nodes.")

        t_lat_rad = math.radians(target_lat)
        t_lon_rad = math.radians(target_lon)

        dlat = self.lat_rad - t_lat_rad
        dlon = self.lon_rad - t_lon_rad

        a = (
            np.sin(dlat / 2.0) ** 2
            + math.cos(t_lat_rad) * np.cos(self.lat_rad) * np.sin(dlon / 2.0) ** 2
        )
        # Numerical clamp
        a = np.clip(a, 0.0, 1.0)
        c = 2.0 * np.arcsin(np.sqrt(a))
        distances_m = EARTH_RADIUS_METERS * c

        nearest_idx = int(np.argmin(distances_m))
        return int(self.node_ids[nearest_idx]), float(distances_m[nearest_idx])

    def is_within_radius(
        self,
        target_lat: float,
        target_lon: float,
        center_lat: float,
        center_lon: float,
        max_radius_km: float = 7.0,
    ) -> tuple[bool, float]:
        """
        Checks whether the target coordinates fall within the maximum service radius from center.
        Returns: (is_within, distance_in_meters)
        """
        dist_m = haversine_distance_m(target_lat, target_lon, center_lat, center_lon)
        return (dist_m <= max_radius_km * 1000.0), dist_m
