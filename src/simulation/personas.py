# src/simulation/personas.py

"""
Synthetic agentic user personas (Distinct system actors across Admin, Staff,
Rider, and Customer roles) and latent Kenyan household shopping archetypes
for realistic market-basket generation and routing telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import random
from typing import Any

import networkx as nx

from src.algorithms.route_engines import RoadNetworkRouter, haversine_distance_m
from src.models import AdminLevel, StaffPosition, VehicleType

COMMON_SIM_PASSWORD: str = "BansiSim@2026!"


@dataclass
class AdminPersona:
    code: str
    first_name: str
    last_name: str
    username: str
    email: str
    phone: str
    level: AdminLevel
    enable_2fa: bool = False


@dataclass
class StaffPersona:
    code: str
    first_name: str
    last_name: str
    username: str
    email: str
    phone: str
    employee_number: str
    position: StaffPosition


@dataclass
class RiderPersona:
    code: str
    first_name: str
    last_name: str
    username: str
    email: str
    phone: str
    national_id: str
    vehicle_type: VehicleType
    vehicle_plate: str | None
    vehicle_description: str
    licence_number: str | None
    licence_expiry: date | None
    behavior_profile: str  # "reliable" | "selective_justified" | "unreliable_unjustified" | "resubmit_applicant"
    accept_probability: float
    home_lat: float
    home_lon: float


@dataclass
class CustomerAddressSpec:
    label: str
    area: str
    street_address: str
    landmark: str
    directions: str
    latitude: float
    longitude: float
    distance_km: float
    zone_band: int  # 0..3


@dataclass
class CustomerPersona:
    code: str
    first_name: str
    last_name: str
    username: str
    email: str
    phone: str
    auth_mode: str  # "local" | "google" | "facebook"
    archetype: str
    secondary_archetype: str
    mpesa_preference: float  # probability of choosing M-Pesa over Cash
    delivery_preference: float  # probability of choosing Home Delivery over Click & Collect
    rec_receptiveness: float  # baseline responsiveness to relevant recommendations
    review_propensity: float  # probability of reviewing completed orders
    addresses: list[CustomerAddressSpec] = field(default_factory=list)


# 8 distinct Kenyan household shopping archetypes with category & keyword affinities
ARCHETYPE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "breakfast_tea_household": {
        "label": "Breakfast & Tea Household",
        "primary_keywords": ["milk", "bread", "eggs", "butter", "margarine", "blue band", "tea", "kericho", "sugar", "coffee", "buns", "mandazi", "yoghurt"],
        "secondary_keywords": ["jam", "honey", "queen cakes", "scones", "croissant", "nescafe", "dormans"],
        "basket_size_range": (3, 7),
    },
    "ugali_traditional_family": {
        "label": "Ugali & Traditional Meal Family",
        "primary_keywords": ["maize meal", "pembe", "jogoo", "hostess", "vegetable oil", "fresh fri", "elianto", "sukuma", "tomatoes", "onions", "royco", "salt", "kensalt", "beef", "tilapia"],
        "secondary_keywords": ["spinach", "avocado", "potatoes", "kimbo", "green grams", "beans", "milk"],
        "basket_size_range": (4, 8),
    },
    "pilau_weekend_feast": {
        "label": "Pilau & Weekend Feast Host",
        "primary_keywords": ["basmati", "pishori", "rice", "pilau", "masala", "chicken", "goat", "nyama", "coca-cola", "stoney", "fanta", "del monte", "tomato sauce"],
        "secondary_keywords": ["ice cream", "dairyland", "samosas", "sausages", "smokies", "mineral water"],
        "basket_size_range": (4, 8),
    },
    "young_parents_baby_care": {
        "label": "Young Parents & Baby Care",
        "primary_keywords": ["pampers", "softcare", "diapers", "wipes", "baby oil", "baby powder", "baby soap", "cerelac", "nan", "calpol", "tissues", "hanan"],
        "secondary_keywords": ["milk", "yoghurt", "vaseline", "dettol", "sunlight", "velvet"],
        "basket_size_range": (3, 6),
    },
    "home_hygiene_laundry": {
        "label": "Home Hygiene & Laundry Planner",
        "primary_keywords": ["ariel", "omo", "washing powder", "sunlight", "bar soap", "menengai", "morning fresh", "jik", "bleach", "harpic", "toilet paper", "velvet", "doom"],
        "secondary_keywords": ["bucket", "dish drainer", "dettol", "tissues", "geisha", "lifebuoy"],
        "basket_size_range": (3, 7),
    },
    "campus_quick_snack_tech": {
        "label": "Campus Quick-Snack & Tech Shopper",
        "primary_keywords": ["indomie", "noodles", "crisps", "stix", "urban bites", "cadbury", "dairy milk", "lunchbar", "soda", "sprite", "peanuts", "oraimo", "charger", "earbuds", "power"],
        "secondary_keywords": ["orbit", "patco", "coffee", "sausages", "smokies", "extension"],
        "basket_size_range": (2, 6),
    },
    "evening_social_beverages": {
        "label": "Evening Social & Beverage Buyer",
        "primary_keywords": ["tusker", "white cap", "guinness", "balozi", "gilbey", "vodka", "kenya cane", "captain morgan", "johnnie walker", "4th street", "wine", "chevda", "peanuts"],
        "secondary_keywords": ["krest", "sprite", "coca-cola", "samosas", "beef steak", "sausages", "ice cream"],
        "basket_size_range": (3, 6),
    },
    "wellness_grooming_firstaid": {
        "label": "Wellness, Grooming & First-Aid",
        "primary_keywords": ["geisha", "dettol", "lifebuoy", "colgate", "close up", "vaseline", "nivea", "nice & lovely", "always", "gillette", "panadol", "strepsils", "vicks", "eno"],
        "secondary_keywords": ["elastoplast", "betadine", "deep heat", "hedex", "mineral water", "keringet", "dasani"],
        "basket_size_range": (3, 6),
    },
}

MIGORI_AREAS: list[tuple[str, str, str, int, tuple[float, float]]] = [
    ("Migori Town CBD", "Posta Road", "Near Migori County Referral Junction", 0, (0.2, 1.4)),
    ("Oruba Estate", "Oruba Ring Street", "Opposite Oruba Primary Gate", 2, (1.4, 3.2)),
    ("Kadika Residential", "Kadika Hospital Lane", "200m past Kadika Market", 1, (1.2, 2.8)),
    ("Nyasare Gardens", "Nyasare Waterworks Rd", "Beside Nyasare ACK Church", 1, (1.8, 3.6)),
    ("Kakrao Township", "Migori-Isibania Highway", "Next to Kakrao Shopping Center", 2, (2.8, 4.8)),
    ("Wasweta II", "Wasweta Feeder Road", "Near Wasweta Dispensary", 2, (2.2, 4.2)),
    ("Ombo Mission Area", "Ombo Hospital Road", "Opposite St Joseph Ombo Gate", 1, (1.3, 2.9)),
    ("Suna West Marindi", "Marindi Bypass", "Near Marindi Chief's Camp", 3, (3.8, 6.2)),
    ("Lichota Farmstead", "Lichota Access Road", "Past Lichota Polytechnic", 3, (4.2, 6.6)),
    ("Ngege Suburb", "Ngege AirStrip Road", "Near Migori Airstrip Junction", 3, (3.5, 5.8)),
]


def sample_connected_road_locations(
    road_router: RoadNetworkRouter,
    rng: random.Random,
    count: int,
    distance_range_km: tuple[float, float] = (0.25, 6.6),
) -> list[tuple[float, float, float]]:
    """
    Samples real OpenStreetMap road vertices guaranteed to belong to the strongly
    connected component of Bansi Mega Supermarket and within the 7km coverage zone.
    Returns list of (latitude, longitude, distance_km).
    """
    g = road_router.graph
    sm_node = road_router.supermarket_node
    sm_lat, sm_lon = road_router.supermarket_coords

    reachable_out = nx.descendants(g, sm_node) | {sm_node}
    reachable_in = nx.ancestors(g, sm_node) | {sm_node}
    valid_nodes = sorted(reachable_out & reachable_in)

    lo_m = distance_range_km[0] * 1000.0
    hi_m = min(distance_range_km[1], road_router.max_delivery_radius_km - 0.15) * 1000.0

    band_candidates: list[tuple[float, float, float]] = []
    all_valid_coords: list[tuple[float, float, float]] = []

    for nid in valid_nodes:
        if nid == sm_node and len(valid_nodes) > 1:
            continue
        nd = g.nodes[nid]
        lat, lon = float(nd["y"]), float(nd["x"])
        dist_m = haversine_distance_m(sm_lat, sm_lon, lat, lon)
        if dist_m <= (road_router.max_delivery_radius_km - 0.1) * 1000.0:
            all_valid_coords.append((lat, lon, round(dist_m / 1000.0, 3)))
            if lo_m <= dist_m <= hi_m:
                band_candidates.append((lat, lon, round(dist_m / 1000.0, 3)))

    pool = band_candidates or all_valid_coords or [(sm_lat + 0.004, sm_lon + 0.004, 0.63)]
    results: list[tuple[float, float, float]] = []
    for _ in range(count):
        base_lat, base_lon, d_km = rng.choice(pool)
        # Micro-jitter (<18m) simulating exact residential gate offset from street centerline
        jitter_lat = round(base_lat + rng.uniform(-0.00012, 0.00012), 6)
        jitter_lon = round(base_lon + rng.uniform(-0.00012, 0.00012), 6)
        within, actual_m = road_router.is_within_coverage(jitter_lat, jitter_lon)
        if within:
            results.append((jitter_lat, jitter_lon, round(actual_m / 1000.0, 3)))
        else:
            results.append((round(base_lat, 6), round(base_lon, 6), d_km))
    return results


def build_agent_cohort(
    road_router: RoadNetworkRouter,
    *,
    run_tag: str = "s1",
    run_index: int = 1,
    seed: int = 20261127,
) -> dict[str, Any]:
    """
    Constructs the complete 54-agent synthetic ecosystem:
      - 5 Admin Personas (SUPER, OPERATIONS, FINANCE, INVENTORY, SUPPORT)
      - 6 Staff Personas (STORE_MANAGER, 2x PICKER, CASHIER, STOCK_CLERK, DISPATCHER)
      - 10 Rider Personas (MOTORCYCLE, TUKTUK, BICYCLE, VAN across 4 behavioral profiles)
      - 33 Customer Personas (distributed across 8 latent household archetypes)
    """
    rng = random.Random(seed)
    phone_seq = 1000 * (run_index % 80 + 10)  # e.g., 11000..90999

    def next_phone(prefix: str = "74") -> str:
        nonlocal phone_seq
        phone_seq += 1
        # +254 + 74 + 7 digits = +25474XXXXXXX (valid Kenyan mobile)
        return f"+254{prefix}{phone_seq:07d}"

    tag = run_tag.lower().replace("-", "")[:6]

    # 1. 5 Administrators
    admin_specs = [
        ("adm_super", "Wanjiku", "Mwangi", AdminLevel.SUPER, True),
        ("adm_ops", "Otieno", "Ochieng", AdminLevel.OPERATIONS, False),
        ("adm_fin", "Amina", "Hassan", AdminLevel.FINANCE, True),
        ("adm_inv", "Kipkorir", "Bett", AdminLevel.INVENTORY, False),
        ("adm_sup", "Naliaka", "Wafula", AdminLevel.SUPPORT, False),
    ]
    admins: list[AdminPersona] = []
    for code, fn, ln, lvl, use_2fa in admin_specs:
        uname = f"{fn.lower()}.{ln.lower()}.{tag}"[:28]
        admins.append(
            AdminPersona(
                code=code,
                first_name=fn,
                last_name=ln,
                username=uname,
                email=f"{uname}@bansigo-hq.co.ke",
                phone=next_phone("71"),
                level=lvl,
                enable_2fa=use_2fa,
            )
        )

    # 2. 6 Store Staff
    staff_specs = [
        ("stf_mgr", "Brian", "Onyango", StaffPosition.STORE_MANAGER),
        ("stf_pck1", "Mercy", "Akinyi", StaffPosition.PICKER),
        ("stf_pck2", "Kevin", "Odhiambo", StaffPosition.PICKER),
        ("stf_csh", "Faith", "Chebet", StaffPosition.CASHIER),
        ("stf_stk", "Dennis", "Mutua", StaffPosition.STOCK_CLERK),
        ("stf_dsp", "Sharon", "Awuor", StaffPosition.DISPATCHER),
    ]
    staff: list[StaffPersona] = []
    for idx, (code, fn, ln, pos) in enumerate(staff_specs, start=1):
        uname = f"stf.{fn.lower()}.{tag}{idx}"[:28]
        staff.append(
            StaffPersona(
                code=code,
                first_name=fn,
                last_name=ln,
                username=uname,
                email=f"{uname}@bansigo-staff.co.ke",
                phone=next_phone("72"),
                employee_number=f"EMP-{run_index:02d}{idx:02d}",
                position=pos,
            )
        )

    # 3. 10 Delivery Riders
    rider_specs = [
        ("rdr_01", "Erick", "Omondi", VehicleType.MOTORCYCLE, "Boxer BM150 Red", "reliable", 0.94),
        ("rdr_02", "Samuel", "Kipchoge", VehicleType.MOTORCYCLE, "TVS HLX 150", "reliable", 0.92),
        ("rdr_03", "Peter", "Owino", VehicleType.MOTORCYCLE, "Honda Ace 125", "reliable", 0.90),
        ("rdr_04", "Joseph", "Mwita", VehicleType.MOTORCYCLE, "Bajaj Boxer 150", "selective_justified", 0.72),
        ("rdr_05", "Collins", "Juma", VehicleType.MOTORCYCLE, "Captain 150", "reliable", 0.91),
        ("rdr_06", "kelvin", "Njuguna", VehicleType.MOTORCYCLE, "Haojue 150", "unreliable_unjustified", 0.45),
        ("rdr_07", "Hassan", "Abdi", VehicleType.TUKTUK, "Piaggio Ape City", "reliable", 0.89),
        ("rdr_08", "Derrick", "Marwa", VehicleType.TUKTUK, "TVS King Deluxe", "reliable", 0.88),
        ("rdr_09", "Victor", "Barasa", VehicleType.BICYCLE, "Giant Trek Cargo Bike", "reliable", 0.93),
        ("rdr_10", "Patrick", "Chacha", VehicleType.CAR, "Suzuki Every Microvan", "resubmit_applicant", 0.90),
    ]
    rider_locs = sample_connected_road_locations(road_router, rng, len(rider_specs), (0.3, 3.8))
    riders: list[RiderPersona] = []
    plate_char = chr(65 + (run_index % 24))
    future_exp = date.today() + timedelta(days=540)

    for idx, ((code, fn, ln, vtype, desc, beh, acc_p), (rlat, rlon, _)) in enumerate(
        zip(rider_specs, rider_locs), start=1
    ):
        uname = f"rdr.{fn.lower()}.{tag}{idx}"[:28]
        is_bike = (vtype == VehicleType.BICYCLE)
        plate = None if is_bike else f"KMF{plate_char} {200 + idx}B"
        lic = None if is_bike else f"DL-KE-{run_index:02d}{8000 + idx}"
        riders.append(
            RiderPersona(
                code=code,
                first_name=fn.capitalize(),
                last_name=ln,
                username=uname,
                email=f"{uname}@bansigo-fleet.co.ke",
                phone=next_phone("79"),
                national_id=f"37{run_index:02d}{1000 + idx:04d}",
                vehicle_type=vtype,
                vehicle_plate=plate,
                vehicle_description=desc,
                licence_number=lic,
                licence_expiry=None if is_bike else future_exp,
                behavior_profile=beh,
                accept_probability=acc_p,
                home_lat=rlat,
                home_lon=rlon,
            )
        )

    # 4. 33 Customers across 8 Household Archetypes
    customer_names = [
        ("Grace", "Atieno"), ("David", "Kamau"), ("Beatrice", "Adhiambo"), ("Stephen", "Oloo"), (" Esther", "Nyambura"),
        ("Michael", "Okoth"), ("Lucy", "Wambui"), ("Daniel", "Kariuki"), ("Millicent", "Auma"), ("George", "Nyamweya"),
        ("fatuma", "Ali"), ("Anthony", "Githinji"), ("Eunice", "Chepkoech"), (" Paul", "Obiero"), ("Catherine", "Muthoni"),
        ("felix", "Onyango"), ("Cynthia", "Moraa"), ("Martin", "Simiyu"), ("Brenda", "Nekesa"), ("kennedy", "Ouma"),
        ("Janet", "Kerubo"), ("Alex", "Mutuku"), ("Lilian", "Anyango"), ("Vincent", "Koech"), ("Diana", "Wangari"),
        ("Nicholas", "Chacha"), ("Sylvia", "Achieng"), ("Lawrence", "Mogaka"), ("Rose", "Robi"), ("agrey", "Odongo"),
        ("Miriam", "Njeri"), ("bernard", "Gikonyo"), ("Hellen", "Boke"),
    ]
    archetype_keys = list(ARCHETYPE_DEFINITIONS.keys())
    customers: list[CustomerPersona] = []

    for idx, (raw_fn, raw_ln) in enumerate(customer_names, start=1):
        fn = raw_fn.strip().capitalize()
        ln = raw_ln.strip().capitalize()
        uname = f"cust.{fn.lower()}{idx}.{tag}"[:28]

        primary_arch = archetype_keys[(idx - 1) % len(archetype_keys)]
        secondary_arch = archetype_keys[(idx + 2) % len(archetype_keys)]

        if idx <= 23:
            auth_mode = "local"
        elif idx <= 29:
            auth_mode = "google"
        else:
            auth_mode = "facebook"

        # 1 or 2 saved addresses per customer across Migori zones
        n_addr = 2 if idx % 3 == 0 else 1
        addr_specs: list[CustomerAddressSpec] = []
        for a_i in range(n_addr):
            area_name, street, landmark, z_band, dist_band = MIGORI_AREAS[(idx + a_i * 3) % len(MIGORI_AREAS)]
            sampled = sample_connected_road_locations(road_router, rng, 1, dist_band)[0]
            addr_specs.append(
                CustomerAddressSpec(
                    label="Home" if a_i == 0 else "Work",
                    area=area_name,
                    street_address=f"Plot {10 + idx + a_i}, {street}",
                    landmark=landmark,
                    directions=f"Gate #{idx}, call upon arrival",
                    latitude=sampled[0],
                    longitude=sampled[1],
                    distance_km=sampled[2],
                    zone_band=z_band,
                )
            )

        customers.append(
            CustomerPersona(
                code=f"cust_{idx:02d}",
                first_name=fn,
                last_name=ln,
                username=uname,
                email=f"{uname}@migori-shoppers.co.ke",
                phone=next_phone("70" if idx % 2 == 0 else "11"),
                auth_mode=auth_mode,
                archetype=primary_arch,
                secondary_archetype=secondary_arch,
                mpesa_preference=round(rng.uniform(0.62, 0.88), 2),
                delivery_preference=round(rng.uniform(0.78, 0.94), 2),
                rec_receptiveness=round(rng.uniform(0.35, 0.75), 2),
                review_propensity=round(rng.uniform(0.55, 0.85), 2),
                addresses=addr_specs,
            )
        )

    return {
        "admins": admins,
        "staff": staff,
        "riders": riders,
        "customers": customers,
        "total_agents": len(admins) + len(staff) + len(riders) + len(customers),
    }


def build_archetype_product_pools(products: list[dict[str, Any]]) -> dict[str, dict[str, list[int]]]:
    """
    Maps active catalogue products into primary anchor items and complementary cross-sell
    items for each of the 8 household archetypes using product names and category names.
    """
    all_ids = [p["id"] for p in products]
    pools: dict[str, dict[str, list[int]]] = {}

    for arch_key, spec in ARCHETYPE_DEFINITIONS.items():
        prim_kw = [k.lower() for k in spec["primary_keywords"]]
        sec_kw = [k.lower() for k in spec["secondary_keywords"]]

        primary_ids: list[int] = []
        secondary_ids: list[int] = []

        for p in products:
            haystack = f"{p.get('name', '')} {p.get('category_name', '')} {p.get('brand_name', '')}".lower()
            if any(k in haystack for k in prim_kw):
                primary_ids.append(p["id"])
            elif any(k in haystack for k in sec_kw):
                secondary_ids.append(p["id"])

        # Deterministic anchor subset (top 10-14 items per archetype so strong co-occurrence emerges!)
        primary_ids.sort()
        secondary_ids.sort()
        anchor_core = primary_ids[:12] if len(primary_ids) >= 6 else (primary_ids + all_ids[:8])
        extended = primary_ids[12:] + secondary_ids
        if not extended:
            extended = [pid for pid in all_ids if pid not in anchor_core][:15]

        pools[arch_key] = {
            "anchors": anchor_core,
            "complements": extended,
            "all_matching": list(dict.fromkeys(primary_ids + secondary_ids)),
        }

    return pools
