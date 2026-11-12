# src/algorithms/route_engines/a_star.py

import heapq
from typing import Any
import networkx as nx

from utilities import get_logger
from .dijkstra import _extract_edge_coords, _extract_street_name
from .edge_weights import (
    MAX_NETWORK_SPEED_MPS,
    _extract_highway_tag,
    calculate_edge_length_m,
    calculate_edge_speed_kmh,
    calculate_edge_travel_time_s,
    calculate_edge_weight,
)
from .spatial_index import haversine_distance_m
from .types import RouteResult, RouteStep, RoutingAlgorithm

log = get_logger(__name__)


class AStarRouter:
    """
    Sophisticated A* route engine with admissible, consistent Haversine heuristics,
    priority-queue acceleration, and complete trajectory reconstruction.
    """

    def find_route(
        self,
        graph: nx.MultiDiGraph,
        source_node: int,
        target_node: int,
        weight: str = "travel_time",
    ) -> RouteResult:
        """
        Executes A* search from source_node to target_node using an admissible heuristic.
        """
        if source_node not in graph:
            raise ValueError(f"Source node {source_node} is not present in graph.")
        if target_node not in graph:
            raise ValueError(f"Target node {target_node} is not present in graph.")

        if source_node == target_node:
            node_data = graph.nodes[source_node]
            pt = (float(node_data["y"]), float(node_data["x"]))
            return RouteResult(
                algorithm=RoutingAlgorithm.A_STAR,
                source_node=source_node,
                target_node=target_node,
                total_distance_m=0.0,
                total_duration_s=0.0,
                node_path=[source_node],
                coordinates=[pt],
                steps=[],
            )

        # Precompute target coordinates for fast heuristic evaluations
        target_data = graph.nodes[target_node]
        target_lat = float(target_data["y"])
        target_lon = float(target_data["x"])

        def heuristic(node_id: int) -> float:
            nd = graph.nodes[node_id]
            h_dist_m = haversine_distance_m(float(nd["y"]), float(nd["x"]), target_lat, target_lon)
            if weight == "distance" or weight == "length":
                return h_dist_m
            # Admissible time heuristic: straight-line distance / max possible network speed
            return h_dist_m / MAX_NETWORK_SPEED_MPS

        # Priority queue entries: (f_score, g_score, node_id)
        start_h = heuristic(source_node)
        pq: list[tuple[float, float, int]] = [(start_h, 0.0, source_node)]

        g_score: dict[int, float] = {source_node: 0.0}
        predecessors: dict[int, tuple[int, dict[str, Any]]] = {}
        visited: set[int] = set()

        target_reached = False

        while pq:
            current_f, current_g, u = heapq.heappop(pq)

            if u in visited:
                continue
            visited.add(u)

            if u == target_node:
                target_reached = True
                break

            if current_g > g_score.get(u, float("inf")):
                continue

            for v in graph.successors(u):
                if v in visited:
                    continue

                edges = graph.get_edge_data(u, v)
                if not edges:
                    continue

                best_edge_data = min(
                    edges.values(),
                    key=lambda d: calculate_edge_weight(d, weight),
                )
                edge_cost = calculate_edge_weight(best_edge_data, weight)
                tentative_g = current_g + edge_cost

                if tentative_g < g_score.get(v, float("inf")):
                    g_score[v] = tentative_g
                    predecessors[v] = (u, best_edge_data)
                    f = tentative_g + heuristic(v)
                    heapq.heappush(pq, (f, tentative_g, v))

        if not target_reached:
            raise nx.NetworkXNoPath(f"No path found between node {source_node} and {target_node}.")

        # Reconstruct path and trajectory
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

            if not all_coords:
                all_coords.extend(step_coords)
            else:
                if step_coords:
                    all_coords.extend(step_coords[1:])

        return RouteResult(
            algorithm=RoutingAlgorithm.A_STAR,
            source_node=source_node,
            target_node=target_node,
            total_distance_m=total_distance_m,
            total_duration_s=total_duration_s,
            node_path=node_path,
            coordinates=all_coords,
            steps=steps,
        )
