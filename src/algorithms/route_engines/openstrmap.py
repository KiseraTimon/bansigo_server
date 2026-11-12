import time
import osmnx as ox
from osmnx._errors import ResponseStatusCodeError

estimate_1 = (-1.286389, 36.817222)
estimates_2 = (-1.0610278,34.4715756)
estimates_3 = (-1.061219, 34.474196)

supermarket_coords = estimates_3
target_radius = 7000
wait_time = 10  # Initial wait time in seconds

while True:
  try:
    print("Attempting to fetch road network from OpenStreetMap...")
    G = ox.graph_from_point(
        supermarket_coords,
        dist=target_radius,
        dist_type="bbox",
        network_type="drive",
    )
    ox.save_graphml(
        G,
        filepath="C:/Projects/Programming/Systems/General/BansiGo/bansigo_server/migori_bansi_7km.graphml",
    )
    print("Success! Data downloaded and saved locally.")
    break
  except ResponseStatusCodeError as e:
    print(f"Server busy (502/429). Retrying in {wait_time} seconds...")
    time.sleep(wait_time)
    wait_time *= 2  # Exponential backoff
