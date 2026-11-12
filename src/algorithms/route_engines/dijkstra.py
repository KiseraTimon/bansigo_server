# src/algorithms/route_engines/dijkstra.py

import heapq
from typing import Any, Optional
import networkx as nx
from shapely.geometry import LineString

from utilities import get_logger
from .edge_weights import (
    _extract_highway_tag,
    calculate_edge_length_m,
    calculate_edge_speed_kmh,
    calculate_edge_travel_time_s,
    calculate_edge_weight,
)
from .types import RouteResult, RouteStep, RoutingAlgorithm

log = get_logger(__name__)


def _extract_edge_coords(graph: nx.MultiDiGraph, u: int, v: int, edge_data: dict[str, Any]) -> list[tuple[float, float]]:
    """
    Extracts high-resolution (latitude, longitude) sequence for an edge.
    OSMnx stores Shapely LineStrings with (x, y) = (longitude, latitude).
    """
    geom = edge_data.get("geometry")
    if isinstance(geom, LineString):
        coords = [(float(lat), float(lon)) for lon, lat in geom.coords]
        # Verify alignment with u and v vertices
        u_data = graph.nodes[u]
        u_lat, u_lon = float(u_data["y"]), float(u_data["x"])
        # If geometry was stored reversed, orient it properly
        if coords and (abs(coords[0][0] - u_lat) > 1e-4 or abs(coords[0][1] - u_lon) > 1e-4):
            v_data = graph.nodes[v]
            v_lat, v_lon = float(v_data["y"]), float(v_data["x"])
            if abs(coords[-1][0] - u_lat) < abs(coords[0][0] - u_lat):
                coords.reverse()
        return coords

    # Fallback to direct straight line between nodes
    u_data = graph.nodes[u]
    v_data = graph.nodes[v]
    return [
        (float(u_data["y"]), float(u_data["x"])),
        (float(v_data["y"]), float(v_data["x"])),
    ]


def _extract_street_name(edge_data: dict[str, Any]) -> Optional[str]:
    name = edge_data.get("name")
    if isinstance(name, list):
        return ", ".join(str(n) for n in name if n)
    return str(name) if name else None


class DijkstraRouter:
    """
    Sophisticated Dijkstra shortest-path route engine with priority-queue min-heap optimization,
    multi-edge resolution, full geometry reconstruction, and multi-target dispatching.
    """

    def find_route(
        self,
        graph: nx.MultiDiGraph,
        source_node: int,
        target_node: int,
        weight: str = "travel_time",
    ) -> RouteResult:
        """
        Executes Dijkstra's algorithm to compute the optimal path from source_node to target_node.
        """
        if source_node not in graph:
            raise ValueError(f"Source node {source_node} is not present in graph.")
        if target_node not in graph:
            raise ValueError(f"Target node {target_node} is not present in graph.")

        if source_node == target_node:
            node_data = graph.nodes[source_node]
            pt = (float(node_data["y"]), float(node_data["x"]))
            return RouteResult(
                algorithm=RoutingAlgorithm.DIJKSTRA,
                source_node=source_node,
                target_node=target_node,
                total_distance_m=0.0,
                total_duration_s=0.0,
                node_path=[source_node],
                coordinates=[pt],
                steps=[],
            )

        # Min-heap priority queue: entries are (cost, node_id)
        pq: list[tuple[float, int]] = []
        heapq.heappush(pq, (0.0, source_node))

        dist: dict[int, float] = {source_node: 0.0}
        predecessors: dict[int, tuple[int, dict[str, Any]]] = {}
        visited: set[int] = set()

        target_reached = False

        while pq:
            current_cost, u = heapq.heappop(pq)

            if u in visited:
                continue
            visited.add(u)

            # Early termination once destination vertex is settled
            if u == target_node:
                target_reached = True
                break

            # If current popped cost exceeds recorded distance, skip
            if current_cost > dist.get(u, float("inf")):
                continue

            for v in graph.successors(u):
                if v in visited:
                    continue

                # MultiDiGraph: determine lowest impedance edge between u and v
                edges = graph.get_edge_data(u, v)
                if not edges:
                    continue

                best_edge_data = min(
                    edges.values(),
                    key=lambda d: calculate_edge_weight(d, weight),
                )
                edge_cost = calculate_edge_weight(best_edge_data, weight)
                new_cost = current_cost + edge_cost

                if new_cost < dist.get(v, float("inf")):
                    dist[v] = new_cost
                    predecessors[v] = (u, best_edge_data)
                    heapq.heappush(pq, (new_cost, v))

        if not target_reached:
            raise nx.NetworkXNoPath(f"No path found between node {source_node} and {target_node}.")

        # Reconstruct path and detailed turn steps
        node_path: list[int] = []
        reversed_edges: list[tuple[int, int, dict[str, Any]]] = []
        curr = target_node

        while curr != source_node:
            prev, edge_data = predecessors[curr]
            reversed_edges.append((prev, curr, edge_data))
            node_path.append(curr)
            curr = prev

        node_path.append(source_node)
        node_path.reverse()
        reversed_edges.reverse()

        steps: list[RouteStep] = []
        all_coords: list[tuple[float, float]] = []
        total_distance_m = 0.0
        total_duration_s = 0.0

        for u, v, edge_data in reversed_edges:
            step_distance = calculate_edge_length_m(edge_data)
            step_duration = calculate_edge_travel_time_s(edge_data)
            step_speed = calculate_edge_speed_kmh(edge_data)
            step_coords = _extract_edge_coords(graph, u, v, edge_data)
            street_name = _extract_street_name(edge_data)
            highway_type = _extract_highway_tag(edge_data)

            step = RouteStep(
                from_node=u,
                to_node=v,
                street_name=street_name,
                highway_type=highway_type,
                distance_m=step_distance,
                duration_s=step_duration,
                speed_kmh=step_speed,
                coordinates=step_coords,
            )
            steps.append(step)
            total_distance_m += step_distance
            total_duration_s += step_duration

            # Seamless coordinate concatenation without duplicate junction vertices
            if not all_coords:
                all_coords.extend(step_coords)
            else:
                if step_coords:
                    all_coords.extend(step_coords[1:])

        return RouteResult(
            algorithm=RoutingAlgorithm.DIJKSTRA,
            source_node=source_node,
            target_node=target_node,
            total_distance_m=total_distance_m,
            total_duration_s=total_duration_s,
            node_path=node_path,
            coordinates=all_coords,
            steps=steps,
        )

    def find_distances_to_many(
        self,
        graph: nx.MultiDiGraph,
        source_node: int,
        target_nodes: set[int],
        weight: str = "travel_time",
    ) -> dict[int, float]:
        """
        Computes shortest distances from a single origin to multiple destination nodes in a single Dijkstra pass.
        Returns a mapping of target_node -> cost.
        """
        if source_node not in graph:
            raise ValueError(f"Source node {source_node} is not in graph.")

        remaining = set(target_nodes)
        results: dict[int, float] = {}

        if source_node in remaining:
            results[source_node] = 0.0
            remaining.remove(source_node)

        if not remaining:
            return results

        pq: list[tuple[float, int]] = [(0.0, source_node)]
        dist: dict[int, float] = {source_node: 0.0}
        visited: set[int] = set()

        while pq and remaining:
            cost, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)

            if u in remaining:
                results[u] = cost
                remaining.remove(u)
                if not remaining:
                    break

            if cost > dist.get(u, float("inf")):
                continue

            for v in graph.successors(u):
                if v in visited:
                    continue
                edges = graph.get_edge_data(u, v)
                if not edges:
                    continue
                min_edge = min(edges.values(), key=lambda d: calculate_edge_weight(d, weight))
                new_cost = cost + calculate_edge_weight(min_edge, weight)
                if new_cost < dist.get(v, float("inf")):
                    dist[v] = new_cost
                    heapq.heappush(pq, (new_cost, v))

        return results
