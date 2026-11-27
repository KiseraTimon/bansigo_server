# src/simulation/orchestrator.py

"""
End-to-End Multi-Agent System Simulation Orchestrator for BansiGo.

Coordinates 54 role-differentiated autonomous agents (Admins, Staff, Riders, Customers)
across registration, OTP/social authentication, catalogue & supplier operations,
330+ synthetic shopping baskets, live Apriori vs FP-Growth recommendation experiments,
M-Pesa STK/C2B & COD settlements, shelf picking (full, short, substituted),
Dijkstra vs A* road-network dispatch & turn-by-turn navigation, dual-PIN handovers,
maker-checker refunds, rider payouts, and verified reviews.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import random
import time
from typing import Any, Callable
import uuid

from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings, get_settings
from src.algorithms.recommenders import MiningConfig
from src.algorithms.route_engines import RoadNetworkRouter, get_router, init_router
from src.helpers.catalogue_import_export import import_products_from_excel
from src.models import (
    Admin,
    AdminLevel,
    Brand,
    Category,
    Customer,
    Delivery,
    DeliveryStatus,
    DeliveryZone,
    FulfilmentType,
    Inventory,
    Order,
    OrderPaymentStatus,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Product,
    Refund,
    RefundStatus,
    ReviewTargetType,
    Rider,
    RiderStatus,
    SimulationRun,
    Staff,
    TaxClass,
    UnitType,
    User,
    UserRole,
)
from src.schemas import SimulationEventIn
from src.security import hash_password_async, make_pickup_code
from src.services import OrderService, SimulationService
from utilities import get_logger, utc_now

from .harness import AgentSession, SimulationHarness
from .personas import (
    ARCHETYPE_DEFINITIONS,
    COMMON_SIM_PASSWORD,
    AdminPersona,
    CustomerPersona,
    RiderPersona,
    StaffPersona,
    build_agent_cohort,
    build_archetype_product_pools,
    sample_connected_road_locations,
)

log = get_logger(__name__)


@dataclass
class SimulationConfig:
    target_baskets: int = 335
    seed: int = 20261127
    run_tag: str | None = None
    title: str = "BansiGo 54-Agent End-to-End Lifecycle & Co-Algorithm Study"
    run_scaling_benchmarks: bool = True
    od_benchmark_pairs: int = 45


class SystemSimulationOrchestrator:
    """
    Executes the multi-phase agentic simulation against a FastAPI application and
    async SQLAlchemy session factory, persisting every event and algorithm comparison.
    """

    def __init__(
        self,
        *,
        app: FastAPI,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings | None = None,
        config: SimulationConfig | None = None,
    ):
        self.app = app
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.config = config or SimulationConfig()
        self.rng = random.Random(self.config.seed)

        self.admin_prefix = f"/{self.settings.admin_portal_path.strip('/')}/admin"
        self.staff_prefix = f"/{self.settings.admin_portal_path.strip('/')}/staff"

        self.run_id: int = 0
        self.run_code: str = ""
        self.seq_no: int = 0
        self._pending_events: list[tuple[int, SimulationEventIn]] = []

        # Live runtime registries
        self.admin_sessions: dict[str, AgentSession] = {}
        self.staff_sessions: dict[str, AgentSession] = {}
        self.rider_sessions: dict[str, AgentSession] = {}
        self.customer_sessions: dict[str, AgentSession] = {}
        self.rider_id_to_session: dict[int, tuple[RiderPersona, AgentSession]] = {}
        self.supplier_ids: list[int] = []

    async def _queue_event(self, ev: SimulationEventIn) -> None:
        self.seq_no += 1
        self._pending_events.append((self.seq_no, ev))
        if len(self._pending_events) >= 40:
            await self._flush_events()

    async def _flush_events(self) -> None:
        if not self._pending_events:
            return
        batch = list(self._pending_events)
        self._pending_events.clear()
        from src.models import SimulationEvent

        async with self.session_factory() as db:
            rows = [
                SimulationEvent(
                    run_id=self.run_id,
                    sequence_no=seq,
                    phase=ev.phase,
                    actor_role=ev.actor_role,
                    actor_subrole=ev.actor_subrole,
                    actor_user_id=ev.actor_user_id,
                    session_id=ev.session_id,
                    action=ev.action,
                    http_method=ev.http_method,
                    endpoint=ev.endpoint,
                    http_status=ev.http_status,
                    latency_ms=round(ev.latency_ms, 3),
                    entity_type=ev.entity_type,
                    entity_id=ev.entity_id,
                    payload_summary=ev.payload_summary,
                )
                for seq, ev in batch
            ]
            db.add_all(rows)
            await db.commit()

    async def _ensure_prerequisite_seed_data(self) -> RoadNetworkRouter:
        """Ensures delivery zones, road router, and retail product catalogue exist."""
        try:
            road_router = get_router()
        except Exception:
            road_router = init_router()

        async with self.session_factory() as db:
            # Ensure delivery zones exist
            has_zone = (await db.execute(select(DeliveryZone).limit(1))).scalar_one_or_none()
            if has_zone is None:
                db.add_all([
                    DeliveryZone(name="Migori Town Central", delivery_fee=Decimal("50.00"), min_order_amount=Decimal("100.00"), estimated_minutes=20, is_active=True),
                    DeliveryZone(name="Kadika & Nyasare", delivery_fee=Decimal("70.00"), min_order_amount=Decimal("150.00"), estimated_minutes=30, is_active=True),
                    DeliveryZone(name="Kakrao & Oruba", delivery_fee=Decimal("90.00"), min_order_amount=Decimal("200.00"), estimated_minutes=35, is_active=True),
                    DeliveryZone(name="Suna West & Lichota", delivery_fee=Decimal("110.00"), min_order_amount=Decimal("250.00"), estimated_minutes=45, is_active=True),
                ])
                await db.commit()

            # Ensure catalogue has products (import Excel workbook if empty, else fallback)
            prod_count = (await db.execute(select(func.count(Product.id)))).scalar_one() or 0
            if prod_count < 20:
                wb_candidates = [
                    Path("data/catalogue/kenyan_products_catalogue.xlsx"),
                    Path("kenyan_products_catalogue.xlsx"),
                ]
                wb_path = next((p for p in wb_candidates if p.exists()), None)
                if wb_path is not None:
                    await import_products_from_excel(wb_path.read_bytes(), actor_id=None, db=db)
                else:
                    cat = Category(name="Staples & Dairy", slug="staples-dairy", is_active=True)
                    brand = Brand(name="Bansi Select", slug="bansi-select", is_active=True)
                    db.add_all([cat, brand])
                    await db.flush()
                    sample_names = [
                        ("Milk 500ml", "65.00"), ("Bread 400g", "70.00"), ("Eggs 6pk", "130.00"),
                        ("Blue Band 250g", "160.00"), ("Kericho Tea 100g", "140.00"), ("Sugar 1kg", "165.00"),
                        ("Pembe Maize Meal 2kg", "185.00"), ("Fresh Fri Oil 1L", "310.00"),
                        ("Sukuma Wiki Bunch", "30.00"), ("Royco Mchuzi Mix", "85.00"),
                        ("Daawat Rice 2kg", "460.00"), ("Pilau Masala 100g", "110.00"),
                        ("Kenchic Chicken 1.2kg", "580.00"), ("Coca-Cola 1.25L", "150.00"),
                        ("Pampers Size 4", "1150.00"), ("Baby Wipes 80s", "240.00"),
                        ("Ariel Powder 1kg", "420.00"), ("Sunlight Bar Soap", "190.00"),
                        ("Indomie Noodles", "45.00"), ("Stix Crisps 50g", "60.00"),
                        ("Tusker Lager 500ml", "250.00"), ("Geisha Soap 225g", "95.00"),
                        ("Colgate 100ml", "180.00"), ("Panadol Advance", "120.00"),
                    ]
                    for idx, (nm, pr) in enumerate(sample_names, start=1):
                        slug = nm.lower().replace(" ", "-").replace(".", "")
                        is_alc = "tusker" in slug
                        p = Product(
                            category_id=cat.id,
                            brand_id=brand.id,
                            sku=f"SIM-FB-{idx:03d}",
                            name=nm,
                            slug=f"{slug}-{idx}",
                            unit=UnitType.PIECE,
                            price=Decimal(pr),
                            cost_price=Decimal(pr) * Decimal("0.75"),
                            tax_class=TaxClass.STANDARD,
                            is_active=True,
                            is_age_restricted=is_alc,
                        )
                        db.add(p)
                        await db.flush()
                        db.add(Inventory(product_id=p.id, quantity_on_hand=Decimal("500"), reorder_level=Decimal("30")))
                    await db.commit()

        return road_router

    async def execute(self, progress_cb: Callable[[str], None] | None = None) -> dict[str, Any]:
        """
        Runs the complete multi-agent simulation study and returns comprehensive summary metrics.
        """
        t_sim_start = time.perf_counter()
        road_router = await self._ensure_prerequisite_seed_data()

        async with self.session_factory() as db:
            existing_runs = (await db.execute(select(func.count(SimulationRun.id)))).scalar_one() or 0
            max_uid = (await db.execute(select(func.max(User.id)))).scalar_one() or 0
            run_index = int(existing_runs) + int(max_uid) + 1
            short_uid = uuid.uuid4().hex[:4]
            run_tag = self.config.run_tag or f"r{short_uid}"
            self.run_code = f"SIM-{utc_now().strftime('%Y%m%d')}-{int(existing_runs) + 1:03d}-{short_uid.upper()}"

            cohort = build_agent_cohort(
                road_router,
                run_tag=run_tag,
                run_index=run_index,
                seed=self.config.seed,
            )

            sim_svc = SimulationService(db)
            sim_run = await sim_svc.start_run(
                run_code=self.run_code,
                title=self.config.title,
                seed=self.config.seed,
                total_agents=cohort["total_agents"],
                target_baskets=self.config.target_baskets,
                config={
                    "run_tag": run_tag,
                    "target_baskets": self.config.target_baskets,
                    "admins_count": len(cohort["admins"]),
                    "staff_count": len(cohort["staff"]),
                    "riders_count": len(cohort["riders"]),
                    "customers_count": len(cohort["customers"]),
                    "road_graph_nodes": road_router.graph.number_of_nodes(),
                    "road_graph_edges": road_router.graph.number_of_edges(),
                },
            )
            self.run_id = sim_run.id

        harness = SimulationHarness(self.settings)

        def _notify(msg: str) -> None:
            log.info("[SIM %s] %s", self.run_code, msg)
            if progress_cb:
                progress_cb(msg)

        stats: dict[str, Any] = {
            "baskets_attempted": 0,
            "baskets_created": 0,
            "orders_completed": 0,
            "orders_cancelled_customer": 0,
            "orders_cancelled_staff": 0,
            "orders_expired_unpaid": 0,
            "mpesa_stk_settled": 0,
            "mpesa_c2b_settled": 0,
            "mpesa_manual_settled": 0,
            "mpesa_stk_retried": 0,
            "cash_settled": 0,
            "short_picks": 0,
            "substituted_picks": 0,
            "rider_accepts": 0,
            "rider_declines_justified": 0,
            "rider_declines_unjustified": 0,
            "manual_dispatches": 0,
            "failed_deliveries_reopened": 0,
            "age_restricted_id_checks": 0,
            "product_reviews_submitted": 0,
            "delivery_reviews_submitted": 0,
            "reviews_moderated": 0,
            "refunds_settled": 0,
            "rider_withdrawals": 0,
            "stock_replenishments": 0,
            "rec_impressions": 0,
            "rec_clicks": 0,
            "rec_cart_adds": 0,
            "rec_purchases": 0,
        }

        try:
            async with harness.activate():
                webhook_agent = AgentSession(
                    app=self.app,
                    actor_role="system_webhook",
                    actor_subrole="safaricom_daraja",
                    agent_code="daraja_webhook",
                    event_sink=self._queue_event,
                )

                # =============================================================
                # PHASE 1: ADMIN GOVERNANCE, CATALOGUE, INVENTORY, STAFF & RIDERS
                # =============================================================
                _notify("Phase 1/4: Onboarding 5 Admins, 6 Staff, 10 Riders, Suppliers & Inventory...")
                await self._run_phase1_workforce_and_catalogue(cohort, harness, run_index, stats)

                # =============================================================
                # PHASE 2: CUSTOMER ONBOARDING, OTP, SOCIAL AUTH & ADDRESSES
                # =============================================================
                _notify("Phase 2/4: Onboarding 33 Customers (Manual OTP + Social OAuth), Addresses & Route Quotes...")
                await self._run_phase2_customers_onboarding(cohort, harness)

                # =============================================================
                # PHASE 3: 335-BASKET MULTI-WAVE COMMERCE, ROUTING & REVIEWS
                # =============================================================
                _notify(f"Phase 3/4: Simulating {self.config.target_baskets} End-to-End Baskets across 3 Market Waves...")
                await self._run_phase3_market_waves(cohort, harness, webhook_agent, road_router, stats, _notify)

                # =============================================================
                # PHASE 4: SCALING & HYPERPARAMETER CO-ALGORITHM BENCHMARKS
                # =============================================================
                if self.config.run_scaling_benchmarks:
                    _notify("Phase 4/4: Running Corpus Scaling, Support Sensitivity & O-D Matrix Co-Algorithm Sweeps...")
                    await self._run_phase4_algorithmic_sweeps(road_router)

                await webhook_agent.aclose()

            await self._flush_events()
            elapsed_s = round(time.perf_counter() - t_sim_start, 2)
            stats["elapsed_seconds"] = elapsed_s
            stats["otp_emails_captured"] = harness.mailbox.total_captured

            async with self.session_factory() as db:
                sim_svc = SimulationService(db)
                completed_run = await sim_svc.finish_run(
                    self.run_id,
                    completed_baskets=stats["baskets_created"],
                    summary_metrics=stats,
                    status="completed",
                )
                stats["run_id"] = completed_run.id
                stats["run_code"] = completed_run.run_code
                stats["total_events"] = completed_run.total_events
                stats["routing_comparisons_count"] = completed_run.routing_comparisons_count
                stats["recommender_comparisons_count"] = completed_run.recommender_comparisons_count

            _notify(
                f"Simulation {self.run_code} completed in {elapsed_s}s: "
                f"{stats['baskets_created']} baskets, {stats['total_events']} events, "
                f"{stats['routing_comparisons_count']} routing comparisons, "
                f"{stats['recommender_comparisons_count']} recommender comparisons."
            )
            return stats

        finally:
            await self._flush_events()
            for group in (
                self.admin_sessions.values(),
                self.staff_sessions.values(),
                self.rider_sessions.values(),
                self.customer_sessions.values(),
            ):
                for sess in group:
                    await sess.aclose()

    # -------------------------------------------------------------------------
    # PHASE 1 IMPLEMENTATION
    # -------------------------------------------------------------------------
    async def _run_phase1_workforce_and_catalogue(
        self,
        cohort: dict[str, Any],
        harness: SimulationHarness,
        run_index: int,
        stats: dict[str, Any],
    ) -> None:
        admins: list[AdminPersona] = cohort["admins"]
        staff_list: list[StaffPersona] = cohort["staff"]
        riders: list[RiderPersona] = cohort["riders"]

        # 1. Bootstrap Superadmin in DB and authenticate via /admin/login
        super_spec = admins[0]
        async with self.session_factory() as db:
            existing_u = (await db.execute(select(User).where(User.username == super_spec.username))).scalar_one_or_none()
            if existing_u is None:
                pw_hash = await hash_password_async(COMMON_SIM_PASSWORD)
                u = User(
                    first_name=super_spec.first_name,
                    last_name=super_spec.last_name,
                    username=super_spec.username,
                    email=super_spec.email,
                    phone=super_spec.phone,
                    password_hash=pw_hash,
                    role=UserRole.ADMIN,
                    is_active=True,
                    is_verified=True,
                )
                db.add(u)
                await db.flush()
                adm = Admin(user_id=u.id, level=AdminLevel.SUPER)
                db.add(adm)
                await db.commit()
                super_uid, super_aid = u.id, adm.id
            else:
                adm = (await db.execute(select(Admin).where(Admin.user_id == existing_u.id))).scalar_one()
                super_uid, super_aid = existing_u.id, adm.id

        super_sess = AgentSession(
            app=self.app,
            actor_role="admin",
            actor_subrole=super_spec.level.value,
            agent_code=super_spec.code,
            event_sink=self._queue_event,
        )
        super_sess.user_id = super_uid
        super_sess.profile_id = super_aid
        self.admin_sessions[super_spec.level.value] = super_sess

        res = await super_sess.request(
            "POST",
            f"{self.admin_prefix}/login",
            phase="onboarding",
            action="admin.login",
            entity_type="admin",
            entity_id=super_aid,
            data={"username": super_spec.username, "password": COMMON_SIM_PASSWORD},
        )
        assert res.status_code == 200, f"Superadmin login failed: {res.status_code} {res.text}"
        super_sess.set_token(res.json()["access_token"])

        # Superadmin enables 2FA via email OTP & reviews security settings
        res_2fa = await super_sess.request(
            "POST",
            f"{self.admin_prefix}/security/2fa/request",
            phase="onboarding",
            action="admin.2fa_request",
            entity_type="user",
            entity_id=super_uid,
        )
        if res_2fa.status_code == 200:
            otp_2fa = harness.mailbox.latest_code_for(super_spec.email) or res_2fa.json().get("dev_code")
            if otp_2fa:
                await super_sess.request(
                    "POST",
                    f"{self.admin_prefix}/security/2fa/confirm",
                    phase="onboarding",
                    action="admin.2fa_confirm",
                    entity_type="user",
                    entity_id=super_uid,
                    data={"code": otp_2fa},
                )

        await super_sess.request(
            "POST",
            f"{self.admin_prefix}/security/settings",
            phase="onboarding",
            action="admin.configure_security_policy",
            entity_type="system_settings",
            entity_id="global",
            data={
                "unpaid_order_ttl_minutes": 15,
                "rider_fee_share": "0.70",
                "vat_standard_rate": "16.00",
                "mpesa_env": "sandbox",
            },
        )

        # 2. Superadmin provisions the 4 specialized Admins & each logs in
        for adm_spec in admins[1:]:
            c_res = await super_sess.request(
                "POST",
                f"{self.admin_prefix}/actors/admins",
                phase="onboarding",
                action="admin.provision_admin",
                entity_type="admin",
                payload_summary={"username": adm_spec.username, "level": adm_spec.level.value},
                data={
                    "first_name": adm_spec.first_name,
                    "last_name": adm_spec.last_name,
                    "username": adm_spec.username,
                    "email": adm_spec.email,
                    "phone": adm_spec.phone,
                    "password": COMMON_SIM_PASSWORD,
                    "level": adm_spec.level.value,
                },
            )
            aid = c_res.json().get("admin_id") if c_res.status_code == 200 else None

            sess = AgentSession(
                app=self.app,
                actor_role="admin",
                actor_subrole=adm_spec.level.value,
                agent_code=adm_spec.code,
                event_sink=self._queue_event,
            )
            l_res = await sess.request(
                "POST",
                f"{self.admin_prefix}/login",
                phase="onboarding",
                action="admin.login",
                entity_type="admin",
                entity_id=aid,
                data={"username": adm_spec.username, "password": COMMON_SIM_PASSWORD},
            )
            if l_res.status_code == 200:
                sess.set_token(l_res.json()["access_token"])
                me_res = await sess.request(
                    "GET", "/api/users/me", phase="onboarding", action="admin.read_profile", record_event=False
                )
                if me_res.status_code == 200:
                    sess.user_id = me_res.json()["id"]
                sess.profile_id = aid
            self.admin_sessions[adm_spec.level.value] = sess

        ops_admin = self.admin_sessions[AdminLevel.OPERATIONS.value]
        inv_admin = self.admin_sessions[AdminLevel.INVENTORY.value]

        # 3. Inventory Admin creates Kenyan wholesale suppliers, adds variant SKUs & stocks shelves
        supplier_defs = [
            (f"Brookside Dairy Migori Depot ({run_index})", "Peter Njoroge", "+254722101101", "orders@brookside-sim.co.ke", f"P051100{run_index:02d}A", 14),
            (f"Bidco & Staples Distributors ({run_index})", "Mary Wambugu", "+254722202202", "supply@bidco-sim.co.ke", f"P051200{run_index:02d}B", 30),
            (f"Lake Basin Fresh & Poultry ({run_index})", "John Owiti", "+254722303303", "fresh@lakebasin-sim.co.ke", f"P051300{run_index:02d}C", 7),
            (f"Nyanza Beverage & Spirits Ltd ({run_index})", "Grace Akumu", "+254722404404", "trade@nyanzabev-sim.co.ke", f"P051400{run_index:02d}D", 21),
        ]
        for s_name, c_name, s_phone, s_mail, kra, terms in supplier_defs:
            s_res = await inv_admin.request(
                "POST",
                f"{self.admin_prefix}/suppliers",
                phase="catalogue_inventory",
                action="inventory_admin.create_supplier",
                entity_type="supplier",
                payload_summary={"name": s_name, "terms_days": terms},
                data={
                    "name": s_name,
                    "contact_name": c_name,
                    "phone": s_phone,
                    "email": s_mail,
                    "kra_pin": kra,
                    "payment_terms_days": terms,
                },
            )
            if s_res.status_code == 200 and "supplier_id" in s_res.json():
                self.supplier_ids.append(s_res.json()["supplier_id"])

        # Add 3 new Bansi value-pack product variants via Inventory Admin
        async with self.session_factory() as db:
            first_cat = (await db.execute(select(Category).where(Category.is_active.is_(True)).limit(1))).scalar_one()
            first_brand = (await db.execute(select(Brand).where(Brand.is_active.is_(True)).limit(1))).scalar_one_or_none()
            cat_id = first_cat.id
            brand_id = first_brand.id if first_brand else None

        new_variants = [
            (f"BNS-COMBO-{run_index:02d}A", f"Bansi Family Breakfast Bundle #{run_index}", "495.00", "550.00", "380.00", "standard"),
            (f"BNS-HONEY-{run_index:02d}B", f"Migori Pure Highland Honey 500g #{run_index}", "380.00", "430.00", "270.00", "standard"),
            (f"BNS-UHT6-{run_index:02d}C", f"Bansi Farm Fresh Milk 6-Pack Saver #{run_index}", "350.00", "390.00", "285.00", "zero_rated"),
        ]
        for sku, nm, pr, cmp_pr, cost_pr, tx in new_variants:
            p_res = await inv_admin.request(
                "POST",
                f"{self.admin_prefix}/products",
                phase="catalogue_inventory",
                action="inventory_admin.add_product_variant",
                entity_type="product",
                payload_summary={"sku": sku, "price": pr},
                data={
                    "category_id": cat_id,
                    "brand_id": brand_id or "",
                    "sku": sku,
                    "name": nm,
                    "description": "Store manager promotional value variant created during simulation",
                    "unit": "piece",
                    "pack_size_label": "Value Pack",
                    "price": pr,
                    "compare_at_price": cmp_pr,
                    "cost_price": cost_pr,
                    "tax_class": tx,
                    "initial_stock": "250",
                    "reorder_level": "25",
                },
            )
            if p_res.status_code == 200:
                pid = p_res.json()["product_id"]
                # Update promotional price & reorder threshold on newly added variant
                await inv_admin.request(
                    "PATCH",
                    f"{self.admin_prefix}/products/{pid}",
                    phase="catalogue_inventory",
                    action="inventory_admin.update_promo_pricing",
                    entity_type="product",
                    entity_id=pid,
                    data={"price": str(Decimal(pr) - Decimal("10.00"))},
                )

        # Ensure healthy baseline stock across catalogue so 335 baskets run smoothly
        async with self.session_factory() as db:
            low_invs = list(
                (await db.execute(select(Inventory).where((Inventory.quantity_on_hand - Inventory.quantity_reserved) < 180))).scalars().all()
            )
            for inv in low_invs:
                inv.quantity_on_hand = inv.quantity_reserved + Decimal("320")
                if inv.reorder_level <= 0:
                    inv.reorder_level = Decimal("35")
            await db.commit()

        # Receive formal supplier shipment on 4 staple SKUs via Inventory Admin HTTP API
        async with self.session_factory() as db:
            staple_ids = list((await db.execute(select(Product.id).where(Product.is_active.is_(True)).limit(4))).scalars().all())
        for pid in staple_ids:
            await inv_admin.request(
                "POST",
                f"{self.admin_prefix}/inventory/{pid}/receive",
                phase="catalogue_inventory",
                action="inventory_admin.receive_supplier_shipment",
                entity_type="inventory",
                entity_id=pid,
                data={
                    "quantity": "80",
                    "supplier_id": self.supplier_ids[0] if self.supplier_ids else "",
                    "unit_cost": "95.00",
                    "note": "Opening simulation supplier delivery",
                },
            )
            stats["stock_replenishments"] += 1

        # 4. Operations Admin creates a Delivery Zone & provisions all 6 Store Staff
        await ops_admin.request(
            "POST",
            f"{self.admin_prefix}/dispatch/zones",
            phase="onboarding",
            action="ops_admin.create_delivery_zone",
            entity_type="delivery_zone",
            data={
                "name": f"Wasweta & Ombo Express ({run_index})",
                "delivery_fee": "65.00",
                "min_order_amount": "120.00",
                "estimated_minutes": "22",
            },
        )

        for stf in staff_list:
            stf_res = await ops_admin.request(
                "POST",
                f"{self.admin_prefix}/actors/staff",
                phase="onboarding",
                action="ops_admin.create_staff",
                entity_type="staff",
                payload_summary={"employee_number": stf.employee_number, "position": stf.position.value},
                data={
                    "first_name": stf.first_name,
                    "last_name": stf.last_name,
                    "username": stf.username,
                    "email": stf.email,
                    "phone": stf.phone,
                    "password": COMMON_SIM_PASSWORD,
                    "employee_number": stf.employee_number,
                    "position": stf.position.value,
                },
            )
            sid = stf_res.json().get("staff_id") if stf_res.status_code == 200 else None
            if sid:
                await ops_admin.request(
                    "POST",
                    f"{self.admin_prefix}/actors/staff/{sid}/toggle-duty",
                    phase="onboarding",
                    action="ops_admin.clock_in_staff",
                    entity_type="staff",
                    entity_id=sid,
                )

            stf_sess = AgentSession(
                app=self.app,
                actor_role="staff",
                actor_subrole=stf.position.value,
                agent_code=stf.code,
                event_sink=self._queue_event,
            )
            tok_res = await stf_sess.request(
                "POST",
                "/api/auth/login",
                phase="onboarding",
                action="staff.login",
                entity_type="staff",
                entity_id=sid,
                data={"username": stf.username, "password": COMMON_SIM_PASSWORD},
            )
            if tok_res.status_code == 200:
                stf_sess.set_token(tok_res.json()["access_token"])
                me_r = await stf_sess.request("GET", "/api/users/me", phase="onboarding", action="staff.me", record_event=False)
                if me_r.status_code == 200:
                    stf_sess.user_id = me_r.json()["id"]
                stf_sess.profile_id = sid
            self.staff_sessions[stf.code] = stf_sess

        # 5. All 10 Riders register, verify email via OTP, upload docs, apply & get vetted
        fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
        for rdr in riders:
            r_sess = AgentSession(
                app=self.app,
                actor_role="rider",
                actor_subrole=rdr.vehicle_type.value,
                agent_code=rdr.code,
                event_sink=self._queue_event,
            )
            # Signup with role="rider"
            s_res = await r_sess.request(
                "POST",
                "/api/auth/signup",
                phase="onboarding",
                action="rider.signup",
                entity_type="user",
                payload_summary={"username": rdr.username, "vehicle": rdr.vehicle_type.value},
                json={
                    "first_name": rdr.first_name,
                    "last_name": rdr.last_name,
                    "username": rdr.username,
                    "email": rdr.email,
                    "phone": rdr.phone,
                    "role": "rider",
                    "password": COMMON_SIM_PASSWORD,
                    "password_confirm": COMMON_SIM_PASSWORD,
                },
            )
            assert s_res.status_code == 201, f"Rider signup failed: {s_res.text}"
            r_sess.user_id = s_res.json()["id"]

            # Login
            l_res = await r_sess.request(
                "POST",
                "/api/auth/login",
                phase="onboarding",
                action="rider.login",
                entity_type="user",
                entity_id=r_sess.user_id,
                data={"username": rdr.username, "password": COMMON_SIM_PASSWORD},
            )
            r_sess.set_token(l_res.json()["access_token"])

            # Request & confirm email verification OTP
            await r_sess.request(
                "POST",
                "/api/users/me/email-verification",
                phase="onboarding",
                action="rider.request_email_otp",
                entity_type="user",
                entity_id=r_sess.user_id,
            )
            otp = harness.mailbox.latest_code_for(rdr.email)
            if otp:
                await r_sess.request(
                    "POST",
                    "/api/users/me/email-verification/confirm",
                    phase="onboarding",
                    action="rider.confirm_email_otp",
                    entity_type="user",
                    entity_id=r_sess.user_id,
                    json={"code": otp},
                )

            # Upload rider vetting document
            up_res = await r_sess.request(
                "POST",
                "/api/rider/documents/upload?doc_type=id_front",
                phase="onboarding",
                action="rider.upload_kyc_doc",
                entity_type="rider_doc",
                files={"file": ("id_front.jpg", fake_jpeg, "image/jpeg")},
            )
            id_front_url = up_res.json().get("url") if up_res.status_code == 200 else "/media/id_front.jpg"

            # Submit RiderApply profile
            apply_payload: dict[str, Any] = {
                "national_id_number": rdr.national_id,
                "id_card_front_url": id_front_url,
                "id_card_back_url": id_front_url,
                "vehicle_type": rdr.vehicle_type.value,
                "vehicle_description": rdr.vehicle_description,
            }
            if rdr.vehicle_plate:
                apply_payload["vehicle_plate"] = rdr.vehicle_plate
                apply_payload["licence_number"] = rdr.licence_number
                apply_payload["licence_expiry"] = rdr.licence_expiry.isoformat() if rdr.licence_expiry else None
                apply_payload["driving_licence_url"] = id_front_url
                apply_payload["vehicle_proof_url"] = id_front_url

            ap_res = await r_sess.request(
                "POST",
                "/api/rider/profile/apply",
                phase="onboarding",
                action="rider.submit_application",
                entity_type="rider",
                json=apply_payload,
            )
            assert ap_res.status_code == 201, f"Rider apply failed: {ap_res.text}"
            rider_id = ap_res.json()["id"]
            r_sess.profile_id = rider_id

            # Operations Admin vets rider
            if rdr.behavior_profile == "resubmit_applicant":
                # First reject due to blurry KYC scan, then rider resubmits and gets approved!
                await ops_admin.request(
                    "POST",
                    f"{self.admin_prefix}/actors/riders/{rider_id}/vet",
                    phase="onboarding",
                    action="ops_admin.reject_rider_kyc",
                    entity_type="rider",
                    entity_id=rider_id,
                    data={"action": "reject"},
                )
                await r_sess.request(
                    "POST",
                    "/api/rider/profile/apply",
                    phase="onboarding",
                    action="rider.resubmit_application",
                    entity_type="rider",
                    entity_id=rider_id,
                    json=apply_payload,
                )

            await ops_admin.request(
                "POST",
                f"{self.admin_prefix}/actors/riders/{rider_id}/vet",
                phase="onboarding",
                action="ops_admin.approve_rider",
                entity_type="rider",
                entity_id=rider_id,
                data={"action": "approve"},
            )

            # Go AVAILABLE & ping initial Migori road GPS telemetry
            await r_sess.request(
                "POST",
                "/api/rider/availability",
                phase="onboarding",
                action="rider.go_online",
                entity_type="rider",
                entity_id=rider_id,
                json={"status": "available"},
            )
            await r_sess.request(
                "POST",
                "/api/rider/location",
                phase="onboarding",
                action="rider.ping_gps",
                entity_type="rider",
                entity_id=rider_id,
                payload_summary={"lat": rdr.home_lat, "lon": rdr.home_lon},
                json={"latitude": str(rdr.home_lat), "longitude": str(rdr.home_lon)},
            )

            self.rider_sessions[rdr.code] = r_sess
            self.rider_id_to_session[rider_id] = (rdr, r_sess)

    # -------------------------------------------------------------------------
    # PHASE 2 IMPLEMENTATION
    # -------------------------------------------------------------------------
    async def _run_phase2_customers_onboarding(
        self,
        cohort: dict[str, Any],
        harness: SimulationHarness,
    ) -> None:
        customers: list[CustomerPersona] = cohort["customers"]

        # Load active delivery zones
        async with self.session_factory() as db:
            zones = list(
                (await db.execute(select(DeliveryZone).where(DeliveryZone.is_active.is_(True)).order_by(DeliveryZone.id))).scalars().all()
            )
            zone_ids = [z.id for z in zones]
            sample_prod_ids = list(
                (await db.execute(select(Product.id).where(Product.is_active.is_(True)).limit(20))).scalars().all()
            )

        for idx, cust in enumerate(customers):
            c_sess = AgentSession(
                app=self.app,
                actor_role="customer",
                actor_subrole=cust.archetype,
                agent_code=cust.code,
                event_sink=self._queue_event,
            )

            if cust.auth_mode == "local":
                # Manual Signup
                s_res = await c_sess.request(
                    "POST",
                    "/api/auth/signup",
                    phase="onboarding",
                    action="customer.signup_manual",
                    entity_type="user",
                    payload_summary={"archetype": cust.archetype, "auth": "local"},
                    json={
                        "first_name": cust.first_name,
                        "last_name": cust.last_name,
                        "username": cust.username,
                        "email": cust.email,
                        "phone": cust.phone,
                        "password": COMMON_SIM_PASSWORD,
                        "password_confirm": COMMON_SIM_PASSWORD,
                    },
                )
                assert s_res.status_code == 201, f"Customer signup failed: {s_res.text}"
                c_sess.user_id = s_res.json()["id"]

                l_res = await c_sess.request(
                    "POST",
                    "/api/auth/login",
                    phase="onboarding",
                    action="customer.login",
                    entity_type="user",
                    entity_id=c_sess.user_id,
                    data={"username": cust.username, "password": COMMON_SIM_PASSWORD},
                )
                c_sess.set_token(l_res.json()["access_token"])

                # On first customer, explicitly verify the unverified-checkout security gate (403 Forbidden)!
                if idx == 0 and sample_prod_ids:
                    await c_sess.request(
                        "POST",
                        "/api/customer/orders/checkout",
                        phase="onboarding",
                        action="customer.unverified_checkout_blocked",
                        entity_type="order",
                        json={
                            "idempotency_key": uuid.uuid4().hex,
                            "items": [{"product_id": sample_prod_ids[0], "quantity": "1"}],
                            "fulfilment_type": "pickup",
                            "payment_method": "cash",
                        },
                    )

                # Request & confirm email verification OTP
                await c_sess.request(
                    "POST",
                    "/api/users/me/email-verification",
                    phase="onboarding",
                    action="customer.request_email_otp",
                    entity_type="user",
                    entity_id=c_sess.user_id,
                )
                otp = harness.mailbox.latest_code_for(cust.email)
                assert otp is not None, f"OTP missing for {cust.email}"
                await c_sess.request(
                    "POST",
                    "/api/users/me/email-verification/confirm",
                    phase="onboarding",
                    action="customer.confirm_email_otp",
                    entity_type="user",
                    entity_id=c_sess.user_id,
                    json={"code": otp},
                )

                # Exercise password reset OTP lifecycle on customer #2
                if idx == 1:
                    await c_sess.request(
                        "POST",
                        "/api/auth/password-reset",
                        phase="onboarding",
                        action="customer.request_password_reset",
                        entity_type="user",
                        entity_id=c_sess.user_id,
                        json={"email": cust.email},
                    )
                    rst_otp = harness.mailbox.latest_code_for(cust.email)
                    if rst_otp:
                        await c_sess.request(
                            "POST",
                            "/api/auth/password-reset/confirm",
                            phase="onboarding",
                            action="customer.confirm_password_reset",
                            entity_type="user",
                            entity_id=c_sess.user_id,
                            json={
                                "email": cust.email,
                                "code": rst_otp,
                                "new_password": COMMON_SIM_PASSWORD,
                                "new_password_confirm": COMMON_SIM_PASSWORD,
                            },
                        )

            else:
                # Social OAuth (Google / Facebook) + Progressive Phone Onboarding
                clean_uid = f"{cust.code.replace('_', '')}r{self.run_id}"
                mock_tok = f"test_token_{clean_uid}_{cust.email}"
                soc_res = await c_sess.request(
                    "POST",
                    "/api/auth/social",
                    phase="onboarding",
                    action=f"customer.social_auth_{cust.auth_mode}",
                    entity_type="user",
                    payload_summary={"provider": cust.auth_mode, "archetype": cust.archetype},
                    json={"provider": cust.auth_mode, "token": mock_tok},
                )
                assert soc_res.status_code == 200, f"Social auth failed: {soc_res.text}"
                soc_body = soc_res.json()
                c_sess.user_id = soc_body["user"]["id"]
                c_sess.set_token(soc_body["access_token"])

                if soc_body.get("requires_phone"):
                    await c_sess.request(
                        "POST",
                        "/api/auth/complete-phone",
                        phase="onboarding",
                        action="customer.complete_progressive_phone",
                        entity_type="user",
                        entity_id=c_sess.user_id,
                        json={"phone": cust.phone},
                    )

            # Resolve customer profile ID
            async with self.session_factory() as db:
                cust_row = (
                    await db.execute(select(Customer).where(Customer.user_id == c_sess.user_id))
                ).scalar_one()
                c_sess.profile_id = cust_row.id

            # Check zones, coverage & route delivery fee estimate (recording co-algorithm comparison!)
            if idx % 4 == 0:
                await c_sess.request("GET", "/api/customer/zones", phase="onboarding", action="customer.list_zones")

            # Test out-of-coverage >7km coordinate on customer #3
            if idx == 2:
                await c_sess.request(
                    "GET",
                    "/api/customer/delivery/coverage?lat=-1.155000&lon=34.560000",
                    phase="onboarding",
                    action="customer.check_coverage_outside_7km",
                )

            saved_addr_ids: list[int] = []
            for a_idx, addr in enumerate(cust.addresses):
                z_id = zone_ids[addr.zone_band % len(zone_ids)]
                cov_res = await c_sess.request(
                    "GET",
                    f"/api/customer/delivery/coverage?lat={addr.latitude}&lon={addr.longitude}",
                    phase="onboarding",
                    action="customer.check_coverage",
                )
                if cov_res.status_code == 200 and cov_res.json().get("is_covered"):
                    est_res = await c_sess.request(
                        "POST",
                        "/api/customer/delivery/estimate",
                        phase="onboarding",
                        action="customer.estimate_delivery_route",
                        payload_summary={"area": addr.area, "dist_km": addr.distance_km},
                        json={"latitude": str(addr.latitude), "longitude": str(addr.longitude)},
                    )
                    if est_res.status_code == 200:
                        est_body = est_res.json()
                        async with self.session_factory() as db:
                            await SimulationService(db).record_routing_comparison(
                                self.run_id,
                                source_lat=float(self.settings.supermarket_latitude),
                                source_lon=float(self.settings.supermarket_longitude),
                                target_lat=addr.latitude,
                                target_lon=addr.longitude,
                                context="delivery_estimate",
                                selected_algorithm=est_body.get("routing_algorithm"),
                            )

                a_res = await c_sess.request(
                    "POST",
                    "/api/customer/addresses",
                    phase="onboarding",
                    action="customer.create_address",
                    entity_type="address",
                    payload_summary={"label": addr.label, "area": addr.area},
                    json={
                        "label": addr.label,
                        "recipient_name": f"{cust.first_name} {cust.last_name}",
                        "recipient_phone": cust.phone,
                        "zone_id": z_id,
                        "area": addr.area,
                        "street_address": addr.street_address,
                        "landmark": addr.landmark,
                        "directions": addr.directions,
                        "latitude": str(addr.latitude),
                        "longitude": str(addr.longitude),
                        "is_default": (a_idx == 0),
                    },
                )
                if a_res.status_code == 201:
                    saved_addr_ids.append(a_res.json()["id"])

            c_sess.saved_address_ids = saved_addr_ids  # type: ignore[attr-defined]

            # Sync wishlist & check initial notifications
            if sample_prod_ids and idx % 2 == 0:
                wl_pick = self.rng.sample(sample_prod_ids, k=min(3, len(sample_prod_ids)))
                await c_sess.request(
                    "POST",
                    "/api/customer/wishlist/sync",
                    phase="onboarding",
                    action="customer.sync_wishlist",
                    json={"product_ids": wl_pick},
                )
            if idx % 3 == 0:
                n_res = await c_sess.request(
                    "GET",
                    "/api/customer/notifications",
                    phase="onboarding",
                    action="customer.fetch_notifications",
                )
                if n_res.status_code == 200:
                    items = n_res.json().get("items", [])
                    if items:
                        await c_sess.request(
                            "PATCH",
                            f"/api/customer/notifications/{items[0]['id']}/read",
                            phase="onboarding",
                            action="customer.read_notification",
                        )

            self.customer_sessions[cust.code] = c_sess

    # -------------------------------------------------------------------------
    # PHASE 3 IMPLEMENTATION: 335-BASKET MULTI-WAVE LIFECYCLE
    # -------------------------------------------------------------------------
    async def _run_phase3_market_waves(
        self,
        cohort: dict[str, Any],
        harness: SimulationHarness,
        webhook_agent: AgentSession,
        road_router: RoadNetworkRouter,
        stats: dict[str, Any],
        notify_cb: Callable[[str], None],
    ) -> None:
        customers: list[CustomerPersona] = cohort["customers"]
        picker_sessions = [self.staff_sessions["stf_pck1"], self.staff_sessions["stf_pck2"]]
        cashier_sess = self.staff_sessions["stf_csh"]
        stock_clerk_sess = self.staff_sessions["stf_stk"]
        dispatcher_sess = self.staff_sessions["stf_dsp"]
        ops_admin = self.admin_sessions[AdminLevel.OPERATIONS.value]
        fin_admin = self.admin_sessions[AdminLevel.FINANCE.value]
        inv_admin = self.admin_sessions[AdminLevel.INVENTORY.value]
        sup_admin = self.admin_sessions[AdminLevel.SUPPORT.value]

        # Load active catalogue snapshot & build household archetype product pools
        async with self.session_factory() as db:
            prods_q = (
                select(Product, Category.name, Brand.name, Inventory.quantity_on_hand, Inventory.quantity_reserved)
                .join(Category, Product.category_id == Category.id)
                .outerjoin(Brand, Product.brand_id == Brand.id)
                .outerjoin(Inventory, Product.id == Inventory.product_id)
                .where(Product.is_active.is_(True))
            )
            prod_rows = (await db.execute(prods_q)).all()

        catalogue_items: list[dict[str, Any]] = []
        prod_by_id: dict[int, dict[str, Any]] = {}
        by_category: dict[int, list[int]] = {}
        for p, cat_name, brand_name, q_hand, q_res in prod_rows:
            entry = {
                "id": p.id,
                "name": p.name,
                "category_id": p.category_id,
                "category_name": cat_name,
                "brand_name": brand_name or "",
                "price": p.price,
                "is_age_restricted": p.is_age_restricted,
            }
            catalogue_items.append(entry)
            prod_by_id[p.id] = entry
            by_category.setdefault(p.category_id, []).append(p.id)

        archetype_pools = build_archetype_product_pools(catalogue_items)
        all_prod_ids = [c["id"] for c in catalogue_items]

        target_baskets = self.config.target_baskets
        secret_val = self.settings.secret_key.get_secret_value()

        for basket_idx in range(1, target_baskets + 1):
            stats["baskets_attempted"] += 1
            wave_name = (
                "wave1_cold_start"
                if basket_idx <= 60
                else ("wave2_growth" if basket_idx <= 190 else "wave3_mature")
            )

            # Select customer (weighted so active repeat households shop multiple times across sessions)
            cust = customers[(basket_idx * 7 + self.rng.randint(0, 4)) % len(customers)]
            c_sess = self.customer_sessions[cust.code]
            c_sess.rotate_session()

            # 1. Customer browses categories / searches catalogue periodically
            if basket_idx % 5 == 1:
                kw = self.rng.choice(ARCHETYPE_DEFINITIONS[cust.archetype]["primary_keywords"])
                await c_sess.request(
                    "GET",
                    f"/api/customer/products?q={kw}&in_stock_only=true&per_page=12",
                    phase="shopping_checkout",
                    action="customer.search_catalogue",
                    payload_summary={"query": kw, "wave": wave_name},
                )
            elif basket_idx % 9 == 0:
                await c_sess.request(
                    "GET",
                    "/api/customer/products?min_price=50&max_price=600&per_page=15",
                    phase="shopping_checkout",
                    action="customer.filter_catalogue_by_price",
                )

            # 2. Construct realistic household seed basket (anchors + secondary + occasional exploratory item)
            pool_prim = archetype_pools[cust.archetype]
            pool_sec = archetype_pools[cust.secondary_archetype]
            min_sz, max_sz = ARCHETYPE_DEFINITIONS[cust.archetype]["basket_size_range"]
            desired_size = self.rng.randint(min_sz, max_sz)

            chosen_pids: list[int] = []
            # Pick 2-4 core anchors so strong frequent itemsets emerge naturally
            n_anchors = min(len(pool_prim["anchors"]), self.rng.randint(2, max(2, desired_size - 1)))
            chosen_pids.extend(self.rng.sample(pool_prim["anchors"], k=n_anchors))

            # Add 1-2 complements or secondary archetype items
            rem = desired_size - len(chosen_pids)
            if rem > 0 and pool_prim["complements"]:
                k_comp = min(len(pool_prim["complements"]), self.rng.randint(0, rem))
                for pid in self.rng.sample(pool_prim["complements"], k=k_comp):
                    if pid not in chosen_pids:
                        chosen_pids.append(pid)

            if len(chosen_pids) < desired_size and self.rng.random() < 0.45 and pool_sec["anchors"]:
                sec_pid = self.rng.choice(pool_sec["anchors"])
                if sec_pid not in chosen_pids:
                    chosen_pids.append(sec_pid)

            if len(chosen_pids) < desired_size and self.rng.random() < 0.25:
                noise_pid = self.rng.choice(all_prod_ids)
                if noise_pid not in chosen_pids:
                    chosen_pids.append(noise_pid)

            # 3. Query AI Recommendations (server randomly picks Apriori or FP-Growth!)
            rec_context = self.rng.choice(["cart", "product_details", "home"])
            if rec_context == "home":
                rec_url = "/api/customer/recommendations?limit=6"
                seed_targets: list[int] = []
            elif rec_context == "product_details":
                seed_targets = [chosen_pids[0]]
                rec_url = f"/api/customer/recommendations?product_id={chosen_pids[0]}&limit=6"
            else:
                seed_targets = chosen_pids[:3]
                csv_ids = ",".join(str(x) for x in seed_targets)
                rec_url = f"/api/customer/recommendations?product_ids={csv_ids}&limit=6"

            rec_res = await c_sess.request(
                "GET",
                rec_url,
                phase="shopping_checkout",
                action="customer.get_recommendations",
                payload_summary={"context": rec_context, "wave": wave_name},
            )

            rec_added_pids: set[int] = set()
            chosen_rec_algo: str | None = None
            imp_cnt = clk_cnt = add_cnt = pur_cnt = 0
            rec_rating: int | None = None

            if rec_res.status_code == 200:
                rec_items = rec_res.json()
                if rec_items:
                    chosen_rec_algo = rec_items[0]["algorithm"]
                    relevant_set = set(pool_prim["all_matching"]) | set(pool_sec["all_matching"])

                    for r_idx, r_item in enumerate(rec_items[:4]):
                        r_pid = r_item["product"]["id"]
                        r_algo = r_item["algorithm"]
                        is_rule_based = str(r_item.get("reason", "")).startswith("Frequently bought")

                        # Record impression (record HTTP event on top item to keep event table crisp, all persisted in recommendation_events!)
                        await c_sess.request(
                            "POST",
                            "/api/customer/recommendations/track",
                            phase="shopping_checkout",
                            action="customer.track_rec_impression",
                            entity_type="product",
                            entity_id=r_pid,
                            record_event=(r_idx == 0),
                            json={
                                "product_id": r_pid,
                                "algorithm": r_algo,
                                "event_type": "impression",
                                "context": rec_context,
                                "session_id": c_sess.session_id,
                            },
                        )
                        imp_cnt += 1
                        stats["rec_impressions"] += 1

                        # Organic customer evaluation based on latent household relevance + associative reason
                        relevance_boost = 0.34 if r_pid in relevant_set else 0.06
                        assoc_boost = 0.14 if is_rule_based else 0.0
                        click_prob = min(0.85, cust.rec_receptiveness * 0.45 + relevance_boost + assoc_boost)

                        if self.rng.random() < click_prob:
                            await c_sess.request(
                                "POST",
                                "/api/customer/recommendations/track",
                                phase="shopping_checkout",
                                action="customer.track_rec_click",
                                entity_type="product",
                                entity_id=r_pid,
                                record_event=True,
                                json={
                                    "product_id": r_pid,
                                    "algorithm": r_algo,
                                    "event_type": "click",
                                    "context": rec_context,
                                    "session_id": c_sess.session_id,
                                },
                            )
                            clk_cnt += 1
                            stats["rec_clicks"] += 1

                            add_prob = 0.68 if r_pid in relevant_set else 0.25
                            if r_pid not in chosen_pids and self.rng.random() < add_prob:
                                chosen_pids.append(r_pid)
                                rec_added_pids.add(r_pid)
                                add_cnt += 1
                                stats["rec_cart_adds"] += 1
                                await c_sess.request(
                                    "POST",
                                    "/api/customer/recommendations/track",
                                    phase="shopping_checkout",
                                    action="customer.track_rec_add_to_cart",
                                    entity_type="product",
                                    entity_id=r_pid,
                                    json={
                                        "product_id": r_pid,
                                        "algorithm": r_algo,
                                        "event_type": "add_to_cart",
                                        "context": rec_context,
                                        "session_id": c_sess.session_id,
                                    },
                                )

                    # Submit helpfulness / usability feedback on ~35% of sessions
                    if self.rng.random() < 0.35:
                        top_pid = rec_items[0]["product"]["id"]
                        was_good = (add_cnt > 0) or (top_pid in relevant_set)
                        rec_rating = self.rng.choice([4, 5]) if was_good else self.rng.choice([2, 3, 4])
                        fb_type = "helpful" if rec_rating >= 4 else "unhelpful"
                        await c_sess.request(
                            "POST",
                            "/api/customer/recommendations/track",
                            phase="shopping_checkout",
                            action=f"customer.rate_recommendation_{fb_type}",
                            entity_type="product",
                            entity_id=top_pid,
                            json={
                                "product_id": top_pid,
                                "algorithm": chosen_rec_algo,
                                "event_type": fb_type,
                                "context": rec_context,
                                "session_id": c_sess.session_id,
                                "rating": rec_rating,
                                "feedback_text": "Relevant household bundle suggestion" if was_good else "Prefer closer category match",
                            },
                        )

            # 4. Build Checkout Request (ensure subtotal >= 260 KES so every delivery zone min_order_amount passes!)
            lines: list[dict[str, Any]] = []
            est_subtotal = Decimal("0")
            for pid in chosen_pids:
                p_info = prod_by_id.get(pid)
                if not p_info:
                    continue
                qty = self.rng.choices([1, 2, 3], weights=[0.62, 0.28, 0.10], k=1)[0]
                est_subtotal += p_info["price"] * qty
                lines.append({"product_id": pid, "quantity": str(qty)})

            if est_subtotal < Decimal("260.00") and lines:
                # Boost first item quantity so minimum zone order rule is cleanly satisfied
                first_price = prod_by_id[lines[0]["product_id"]]["price"]
                extra_qty = int((Decimal("270.00") - est_subtotal) // max(Decimal("1.00"), first_price)) + 2
                lines[0]["quantity"] = str(int(lines[0]["quantity"]) + extra_qty)

            addr_ids: list[int] = getattr(c_sess, "saved_address_ids", [])
            use_delivery = bool(addr_ids) and (self.rng.random() < cust.delivery_preference)
            fulfilment = FulfilmentType.DELIVERY.value if use_delivery else FulfilmentType.PICKUP.value
            pay_method = PaymentMethod.MPESA.value if (self.rng.random() < cust.mpesa_preference) else PaymentMethod.CASH.value

            checkout_body: dict[str, Any] = {
                "idempotency_key": uuid.uuid4().hex,
                "items": lines,
                "fulfilment_type": fulfilment,
                "payment_method": pay_method,
                "customer_note": f"Sim wave={wave_name} basket=#{basket_idx}",
            }
            if use_delivery:
                checkout_body["address_id"] = self.rng.choice(addr_ids)

            # Ensure sufficient stock right before checkout if an item ran low, triggering formal Inventory replenishment!
            await self._replenish_if_needed(lines, inv_admin, stock_clerk_sess, stats)

            chk_res = await c_sess.request(
                "POST",
                "/api/customer/orders/checkout",
                phase="shopping_checkout",
                action="customer.checkout_order",
                entity_type="order",
                payload_summary={
                    "basket_idx": basket_idx,
                    "items_count": len(lines),
                    "fulfilment": fulfilment,
                    "payment_method": pay_method,
                },
                json=checkout_body,
            )
            if chk_res.status_code != 201:
                log.warning("Checkout #%d returned %s: %s", basket_idx, chk_res.status_code, chk_res.text)
                continue

            order_data = chk_res.json()
            order_id = order_data["id"]
            order_number = order_data["order_number"]
            order_total = Decimal(str(order_data["total"]))
            stats["baskets_created"] += 1

            # Track recommendation purchase conversions for recommended items bought in this order
            if chosen_rec_algo and rec_added_pids:
                for pur_pid in rec_added_pids:
                    await c_sess.request(
                        "POST",
                        "/api/customer/recommendations/track",
                        phase="shopping_checkout",
                        action="customer.track_rec_purchase",
                        entity_type="product",
                        entity_id=pur_pid,
                        record_event=False,
                        json={
                            "product_id": pur_pid,
                            "algorithm": chosen_rec_algo,
                            "event_type": "purchase",
                            "context": rec_context,
                            "session_id": c_sess.session_id,
                        },
                    )
                    pur_cnt += 1
                    stats["rec_purchases"] += 1

            # Persist head-to-head RecommenderAlgorithmComparison (Apriori vs FP-Growth) for live shopping session!
            # We persist every 2nd basket + all wave milestones (~175 live session comparisons + Phase 4 sweeps!)
            if basket_idx <= 40 or basket_idx % 2 == 0:
                async with self.session_factory() as db:
                    await SimulationService(db).record_recommender_comparison(
                        self.run_id,
                        context=rec_context,
                        target_product_ids=seed_targets or None,
                        selected_algorithm=chosen_rec_algo,
                        customer_id=c_sess.profile_id,
                        order_id=order_id,
                        session_id=c_sess.session_id,
                        impressions_count=imp_cnt,
                        clicks_count=clk_cnt,
                        cart_adds_count=add_cnt,
                        purchases_count=pur_cnt,
                        user_rating=rec_rating,
                    )

            # Edge Case A: Unpaid M-Pesa order abandoned & swept by expire_unpaid (~1.5%)
            if pay_method == "mpesa" and basket_idx in (48, 165, 285):
                async with self.session_factory() as db:
                    ord_row = await db.get(Order, order_id)
                    if ord_row:
                        ord_row.created_at = utc_now() - (
                            __import__("datetime").timedelta(minutes=self.settings.unpaid_order_ttl_minutes + 5)
                        )
                        await db.commit()
                    expired_n = await OrderService(db, self.settings).expire_unpaid()
                    stats["orders_expired_unpaid"] += expired_n
                await self._queue_event(
                    SimulationEventIn(
                        phase="payment",
                        actor_role="system_sweeper",
                        actor_subrole="ttl_sweeper",
                        action="order.expire_unpaid_sweep",
                        entity_type="order",
                        entity_id=str(order_id),
                        payload_summary={"order_number": order_number},
                    )
                )
                continue

            # Edge Case B: Customer cancels before preparation (~2%)
            if basket_idx in (29, 118, 224, 310):
                cxl_res = await c_sess.request(
                    "POST",
                    f"/api/customer/orders/{order_id}/cancel",
                    phase="shopping_checkout",
                    action="customer.cancel_order",
                    entity_type="order",
                    entity_id=order_id,
                    json={"reason": "Forgot to include extra household items"},
                )
                if cxl_res.status_code == 200:
                    stats["orders_cancelled_customer"] += 1
                continue

            # 5. Payment Settlement for M-Pesa Orders
            if pay_method == "mpesa":
                await self._settle_mpesa_order(
                    basket_idx=basket_idx,
                    order_id=order_id,
                    order_number=order_number,
                    order_total=order_total,
                    cust=cust,
                    c_sess=c_sess,
                    fin_admin=fin_admin,
                    webhook_agent=webhook_agent,
                    harness=harness,
                    stats=stats,
                )

            # Edge Case C: Post-payment Support/Admin cancellation -> Maker-Checker Refund Settlement!
            if pay_method == "mpesa" and basket_idx in (75, 205, 302):
                sc_res = await sup_admin.request(
                    "POST",
                    f"{self.admin_prefix}/orders/{order_id}/cancel",
                    phase="treasury_settlement",
                    action="support_admin.cancel_paid_order",
                    entity_type="order",
                    entity_id=order_id,
                    data={"reason": "Customer requested urgent cancellation after M-Pesa payment"},
                )
                if sc_res.status_code == 200:
                    stats["orders_cancelled_staff"] += 1
                    await self._process_pending_refunds(fin_admin, super_admin=self.admin_sessions["super"], stats=stats)
                continue

            # 6. Store Shelf Picking by Staff Pickers (full picks, short picks, substitutions)
            picker = picker_sessions[basket_idx % len(picker_sessions)]
            await self._pick_and_pack_order(
                basket_idx=basket_idx,
                order_id=order_id,
                picker=picker,
                by_category=by_category,
                stats=stats,
            )

            # If a short pick on a paid order staged a partial refund, let Finance Admin settle it!
            if basket_idx % 25 == 0:
                await self._process_pending_refunds(fin_admin, super_admin=self.admin_sessions["super"], stats=stats)

            # 7. Fulfilment: Click & Collect Pickup vs Road-Network Rider Delivery
            if fulfilment == FulfilmentType.PICKUP.value:
                pk_res = await cashier_sess.request(
                    "POST",
                    f"{self.staff_prefix}/orders/{order_id}/complete-pickup",
                    phase="delivery_handover",
                    action="cashier.complete_click_and_collect",
                    entity_type="order",
                    entity_id=order_id,
                )
                if pk_res.status_code == 200:
                    stats["orders_completed"] += 1
                    if pay_method == "cash":
                        stats["cash_settled"] += 1
            else:
                delivered_ok = await self._execute_delivery_lifecycle(
                    basket_idx=basket_idx,
                    order_id=order_id,
                    pay_method=pay_method,
                    c_sess=c_sess,
                    dispatcher_sess=dispatcher_sess,
                    ops_admin=ops_admin,
                    secret_val=secret_val,
                    stats=stats,
                )
                if not delivered_ok:
                    continue

            # 8. Customer Product & Rider Reviews + Support Admin Moderation
            if self.rng.random() < cust.review_propensity:
                await self._submit_customer_reviews(
                    basket_idx=basket_idx,
                    order_id=order_id,
                    fulfilment=fulfilment,
                    c_sess=c_sess,
                    sup_admin=sup_admin,
                    stats=stats,
                )

            # 9. Periodic Operational Maintenance (Rider Wallet Withdrawals, Stock-Takes, Wastage, Admin Audits)
            if basket_idx % 55 == 0:
                await self._run_periodic_operations(
                    basket_idx=basket_idx,
                    all_prod_ids=all_prod_ids,
                    inv_admin=inv_admin,
                    ops_admin=ops_admin,
                    fin_admin=fin_admin,
                    stock_clerk_sess=stock_clerk_sess,
                    stats=stats,
                )

            if basket_idx % 60 == 0 or basket_idx == target_baskets:
                await self._flush_events()
                notify_cb(
                    f"  Progress: {basket_idx}/{target_baskets} baskets processed "
                    f"(completed={stats['orders_completed']}, rec_clicks={stats['rec_clicks']}, "
                    f"reviews={stats['product_reviews_submitted'] + stats['delivery_reviews_submitted']})"
                )

        # Final sweep of any remaining pending refunds
        await self._process_pending_refunds(fin_admin, super_admin=self.admin_sessions["super"], stats=stats)

    async def _replenish_if_needed(
        self,
        lines: list[dict[str, Any]],
        inv_admin: AgentSession,
        stock_clerk: AgentSession,
        stats: dict[str, Any],
    ) -> None:
        pids = [int(x["product_id"]) for x in lines]
        low_pids: list[int] = []
        async with self.session_factory() as db:
            invs = list((await db.execute(select(Inventory).where(Inventory.product_id.in_(pids)))).scalars().all())
            for inv in invs:
                if (inv.quantity_on_hand - inv.quantity_reserved) <= inv.reorder_level + Decimal("10"):
                    low_pids.append(inv.product_id)

        for pid in low_pids:
            actor = stock_clerk if (pid % 2 == 0) else inv_admin
            prefix = self.staff_prefix if actor is stock_clerk else self.admin_prefix
            await actor.request(
                "POST",
                f"{prefix}/inventory/{pid}/receive",
                phase="catalogue_inventory",
                action="inventory.reorder_replenishment",
                entity_type="inventory",
                entity_id=pid,
                data={
                    "quantity": "150",
                    "supplier_id": self.supplier_ids[pid % len(self.supplier_ids)] if self.supplier_ids else "",
                    "unit_cost": "110.00",
                    "note": "Automated reorder threshold restock",
                },
            )
            stats["stock_replenishments"] += 1

    async def _settle_mpesa_order(
        self,
        *,
        basket_idx: int,
        order_id: int,
        order_number: str,
        order_total: Decimal,
        cust: CustomerPersona,
        c_sess: AgentSession,
        fin_admin: AgentSession,
        webhook_agent: AgentSession,
        harness: SimulationHarness,
        stats: dict[str, Any],
    ) -> None:
        receipt_code = f"SIM{basket_idx:04d}{uuid.uuid4().hex[:5].upper()}"

        # Branch 1 (~8%): Direct Paybill C2B Confirmation quoting order_number
        if basket_idx % 12 == 0:
            c2b_payload = {
                "TransactionType": "Pay Bill",
                "TransID": receipt_code,
                "TransTime": harness.eat_timestamp_str(),
                "TransAmount": str(int(order_total)),
                "BusinessShortCode": "174379",
                "BillRefNumber": order_number,
                "MSISDN": cust.phone.lstrip("+"),
                "FirstName": cust.first_name,
            }
            await webhook_agent.request(
                "POST",
                harness.build_c2b_confirmation_url(),
                phase="payment",
                action="daraja.c2b_confirmation",
                entity_type="order",
                entity_id=order_id,
                headers=harness.trusted_safaricom_headers(),
                payload_summary={"receipt": receipt_code, "amount": str(order_total)},
                json=c2b_payload,
            )
            stats["mpesa_c2b_settled"] += 1
            return

        # Branch 2 (~6%): Manual M-Pesa Receipt Fallback (customer or Finance Admin reconciliation)
        if basket_idx % 16 == 0:
            if basket_idx % 32 == 0:
                await fin_admin.request(
                    "POST",
                    f"{self.admin_prefix}/finance/orders/{order_id}/confirm-manual",
                    phase="payment",
                    action="finance_admin.reconcile_manual_mpesa",
                    entity_type="order",
                    entity_id=order_id,
                    data={"transaction_code": receipt_code},
                )
            else:
                await c_sess.request(
                    "POST",
                    f"/api/customer/orders/{order_id}/pay/manual",
                    phase="payment",
                    action="customer.confirm_manual_mpesa",
                    entity_type="order",
                    entity_id=order_id,
                    json={"transaction_code": receipt_code},
                )
            stats["mpesa_manual_settled"] += 1
            return

        # Branch 3 (Primary ~86%): M-Pesa STK Push -> Daraja STK Webhook Callback
        stk_res = await c_sess.request(
            "POST",
            f"/api/customer/orders/{order_id}/pay/mpesa",
            phase="payment",
            action="customer.initiate_mpesa_stk",
            entity_type="order",
            entity_id=order_id,
            json={"idempotency_key": uuid.uuid4().hex, "phone": cust.phone},
        )
        assert stk_res.status_code == 200, f"STK initiate failed: {stk_res.text}"
        pay_id = stk_res.json()["id"]

        async with self.session_factory() as db:
            pay_row = await db.get(Payment, pay_id)
            checkout_req_id = pay_row.provider_checkout_request_id
            merchant_req_id = pay_row.provider_merchant_request_id or f"MOCK-M-{order_id}"

        # Occasional STK prompt user-cancel (ResultCode 1032) followed by manual receipt settlement!
        if basket_idx % 28 == 0:
            cancel_env = {
                "Body": {
                    "stkCallback": {
                        "MerchantRequestID": merchant_req_id,
                        "CheckoutRequestID": checkout_req_id,
                        "ResultCode": 1032,
                        "ResultDesc": "Request cancelled by user",
                    }
                }
            }
            await webhook_agent.request(
                "POST",
                harness.build_stk_callback_url(),
                phase="payment",
                action="daraja.stk_callback_cancelled_1032",
                entity_type="payment",
                entity_id=pay_id,
                headers=harness.trusted_safaricom_headers(),
                json=cancel_env,
            )
            await c_sess.request(
                "POST",
                f"/api/customer/orders/{order_id}/pay/manual",
                phase="payment",
                action="customer.retry_after_stk_cancel",
                entity_type="order",
                entity_id=order_id,
                json={"transaction_code": receipt_code},
            )
            stats["mpesa_stk_retried"] += 1
            stats["mpesa_manual_settled"] += 1
            return

        # Standard successful Daraja ResultCode=0 callback
        stk_env = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": merchant_req_id,
                    "CheckoutRequestID": checkout_req_id,
                    "ResultCode": 0,
                    "ResultDesc": "The service request is processed successfully.",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": int(order_total)},
                            {"Name": "MpesaReceiptNumber", "Value": receipt_code},
                            {"Name": "TransactionDate", "Value": harness.eat_timestamp_int()},
                            {"Name": "PhoneNumber", "Value": int(cust.phone.lstrip("+"))},
                        ]
                    },
                }
            }
        }
        await webhook_agent.request(
            "POST",
            harness.build_stk_callback_url(),
            phase="payment",
            action="daraja.stk_callback_success",
            entity_type="payment",
            entity_id=pay_id,
            headers=harness.trusted_safaricom_headers(),
            payload_summary={"receipt": receipt_code, "amount": int(order_total)},
            json=stk_env,
        )
        stats["mpesa_stk_settled"] += 1

    async def _pick_and_pack_order(
        self,
        *,
        basket_idx: int,
        order_id: int,
        picker: AgentSession,
        by_category: dict[int, list[int]],
        stats: dict[str, Any],
    ) -> None:
        await picker.request(
            "POST",
            f"{self.staff_prefix}/orders/{order_id}/start-picking",
            phase="fulfilment_picking",
            action="picker.start_picking",
            entity_type="order",
            entity_id=order_id,
        )

        async with self.session_factory() as db:
            from sqlalchemy.orm import selectinload
            ord_obj = (
                await db.execute(select(Order).options(selectinload(Order.items)).where(Order.id == order_id))
            ).scalar_one()
            items_snapshot = [
                {"id": it.id, "product_id": it.product_id, "quantity": it.quantity}
                for it in ord_obj.items
            ]
            ordered_pids = {it["product_id"] for it in items_snapshot}

        for idx, it in enumerate(items_snapshot):
            qty = it["quantity"]
            # Exercise SHORT pick (~3.5% on multi-unit lines)
            if idx == 0 and qty >= Decimal("2") and basket_idx % 19 == 0:
                short_qty = qty - Decimal("1")
                p_res = await picker.request(
                    "POST",
                    f"{self.staff_prefix}/orders/{order_id}/items/{it['id']}/pick",
                    phase="fulfilment_picking",
                    action="picker.record_short_pick",
                    entity_type="order_item",
                    entity_id=it["id"],
                    record_event=True,
                    data={"pick_status": "short", "quantity_picked": str(short_qty)},
                )
                if p_res.status_code == 200:
                    stats["short_picks"] += 1
                    continue

            # Exercise SUBSTITUTED pick (~2.5% on last line using same-category SKU)
            if idx == len(items_snapshot) - 1 and basket_idx % 27 == 0:
                sub_pid = None
                async with self.session_factory() as db:
                    orig_p = await db.get(Product, it["product_id"])
                    if orig_p:
                        candidates = [
                            cid for cid in by_category.get(orig_p.category_id, [])
                            if cid not in ordered_pids
                        ]
                        for cand_id in candidates:
                            inv = await db.get(Inventory, cand_id)
                            if inv and (inv.quantity_on_hand - inv.quantity_reserved) >= qty + Decimal("5"):
                                sub_pid = cand_id
                                break
                if sub_pid is not None:
                    s_res = await picker.request(
                        "POST",
                        f"{self.staff_prefix}/orders/{order_id}/items/{it['id']}/pick",
                        phase="fulfilment_picking",
                        action="picker.record_substituted_pick",
                        entity_type="order_item",
                        entity_id=it["id"],
                        record_event=True,
                        data={
                            "pick_status": "substituted",
                            "quantity_picked": str(qty),
                            "substitute_product_id": str(sub_pid),
                        },
                    )
                    if s_res.status_code == 200:
                        stats["substituted_picks"] += 1
                        continue

            # Standard full pick (record HTTP event on first item to keep trace concise)
            await picker.request(
                "POST",
                f"{self.staff_prefix}/orders/{order_id}/items/{it['id']}/pick",
                phase="fulfilment_picking",
                action="picker.record_item_picked",
                entity_type="order_item",
                entity_id=it["id"],
                record_event=(idx == 0),
                data={"pick_status": "picked", "quantity_picked": str(qty)},
            )

        await picker.request(
            "POST",
            f"{self.staff_prefix}/orders/{order_id}/finish-picking",
            phase="fulfilment_picking",
            action="picker.finish_picking",
            entity_type="order",
            entity_id=order_id,
        )

    async def _execute_delivery_lifecycle(
        self,
        *,
        basket_idx: int,
        order_id: int,
        pay_method: str,
        c_sess: AgentSession,
        dispatcher_sess: AgentSession,
        ops_admin: AgentSession,
        secret_val: str,
        stats: dict[str, Any],
    ) -> bool:
        async with self.session_factory() as db:
            deliv = (await db.execute(select(Delivery).where(Delivery.order_id == order_id))).scalar_one_or_none()
            ord_obj = await db.get(Order, order_id)
            if deliv is None or ord_obj is None:
                return False
            deliv_id = deliv.id
            dest_lat = float(ord_obj.delivery_latitude) if ord_obj.delivery_latitude else float(self.settings.supermarket_latitude)
            dest_lon = float(ord_obj.delivery_longitude) if ord_obj.delivery_longitude else float(self.settings.supermarket_longitude)
            assigned_rider_id = deliv.rider_id
            assigned_algo = deliv.routing_algorithm
            requires_id = deliv.requires_id_check

        # Persist head-to-head Dijkstra vs A* comparison for store -> customer dispatch route!
        async with self.session_factory() as db:
            await SimulationService(db).record_routing_comparison(
                self.run_id,
                source_lat=float(self.settings.supermarket_latitude),
                source_lon=float(self.settings.supermarket_longitude),
                target_lat=dest_lat,
                target_lon=dest_lon,
                context="dispatch_store_to_customer",
                selected_algorithm=assigned_algo,
                order_id=order_id,
                delivery_id=deliv_id,
                rider_id=assigned_rider_id,
            )

        # If unassigned, Operations Admin manually assigns an available rider
        if assigned_rider_id is None:
            assigned_rider_id = await self._manual_assign_fallback(deliv_id, ops_admin, stats)
            if assigned_rider_id is None:
                return False

        # Rider response loop (handles declines & automatic re-dispatch!)
        for _attempt in range(3):
            if assigned_rider_id not in self.rider_id_to_session:
                assigned_rider_id = await self._manual_assign_fallback(deliv_id, ops_admin, stats)
                if assigned_rider_id is None:
                    return False

            r_persona, r_sess = self.rider_id_to_session[assigned_rider_id]
            should_decline = (_attempt == 0) and (self.rng.random() > r_persona.accept_probability)

            if should_decline:
                if r_persona.behavior_profile == "unreliable_unjustified":
                    r_code, r_txt = "too_far", "Do not feel like riding right now"
                    stats["rider_declines_unjustified"] += 1
                else:
                    r_code = self.rng.choice(["shift_ending", "over_capacity", "vehicle_breakdown"])
                    r_txt = "Valid operational constraint during active shift"
                    stats["rider_declines_justified"] += 1

                await r_sess.request(
                    "POST",
                    f"/api/rider/deliveries/{deliv_id}/respond",
                    phase="dispatch_routing",
                    action="rider.decline_offer",
                    entity_type="delivery",
                    entity_id=deliv_id,
                    payload_summary={"reason_code": r_code},
                    json={"accept": False, "reason_code": r_code, "reason_text": r_txt},
                )
                async with self.session_factory() as db:
                    refreshed = await db.get(Delivery, deliv_id)
                    assigned_rider_id = refreshed.rider_id if refreshed else None
                if assigned_rider_id is None:
                    assigned_rider_id = await self._manual_assign_fallback(deliv_id, ops_admin, stats)
                    if assigned_rider_id is None:
                        return False
                continue

            # Accept offer!
            acc_res = await r_sess.request(
                "POST",
                f"/api/rider/deliveries/{deliv_id}/respond",
                phase="dispatch_routing",
                action="rider.accept_offer",
                entity_type="delivery",
                entity_id=deliv_id,
                json={"accept": True},
            )
            if acc_res.status_code == 200:
                stats["rider_accepts"] += 1
                break

        r_persona, r_sess = self.rider_id_to_session[assigned_rider_id]

        # Rider fetches active turn-by-turn navigation to supermarket (recording Dijkstra vs A* comparison!)
        if basket_idx % 3 == 0:
            nav_res = await r_sess.request(
                "GET",
                f"/api/rider/deliveries/{deliv_id}/navigation",
                phase="dispatch_routing",
                action="rider.navigate_to_supermarket",
                entity_type="delivery",
                entity_id=deliv_id,
            )
            if nav_res.status_code == 200:
                nav_algo = nav_res.json().get("routing_algorithm")
                async with self.session_factory() as db:
                    r_db = await db.get(Rider, assigned_rider_id)
                    r_lat = float(r_db.last_latitude) if r_db and r_db.last_latitude else r_persona.home_lat
                    r_lon = float(r_db.last_longitude) if r_db and r_db.last_longitude else r_persona.home_lon
                    await SimulationService(db).record_routing_comparison(
                        self.run_id,
                        source_lat=r_lat,
                        source_lon=r_lon,
                        target_lat=float(self.settings.supermarket_latitude),
                        target_lon=float(self.settings.supermarket_longitude),
                        context="navigation_rider_to_store",
                        selected_algorithm=nav_algo,
                        order_id=order_id,
                        delivery_id=deliv_id,
                        rider_id=assigned_rider_id,
                    )

        # Store Pickup PIN verification (alternating between Rider app & Store Dispatcher bay verification)
        pickup_pin = make_pickup_code(secret_val, deliv_id, self.settings.pickup_code_length)
        if basket_idx % 5 == 0:
            await dispatcher_sess.request(
                "POST",
                f"{self.staff_prefix}/deliveries/{deliv_id}/verify-pickup",
                phase="delivery_handover",
                action="dispatcher.verify_store_pickup_pin",
                entity_type="delivery",
                entity_id=deliv_id,
                data={"pickup_code": pickup_pin},
            )
        else:
            await r_sess.request(
                "POST",
                f"/api/rider/deliveries/{deliv_id}/pickup",
                phase="delivery_handover",
                action="rider.verify_pickup_pin",
                entity_type="delivery",
                entity_id=deliv_id,
                json={"pickup_code": pickup_pin},
            )

        # Edge Case D: Delivery fails mid-transit (customer temporarily unreachable) -> Dispatcher reopens & completes!
        if basket_idx in (92, 248):
            await r_sess.request(
                "POST",
                f"/api/rider/deliveries/{deliv_id}/fail",
                phase="delivery_handover",
                action="rider.report_delivery_failed",
                entity_type="delivery",
                entity_id=deliv_id,
                json={"reason": "Customer phone switched off at compound gate"},
            )
            re_res = await dispatcher_sess.request(
                "POST",
                f"{self.staff_prefix}/deliveries/{deliv_id}/reopen",
                phase="delivery_handover",
                action="dispatcher.reopen_failed_delivery",
                entity_type="delivery",
                entity_id=deliv_id,
                data={"order_id": str(order_id)},
            )
            stats["failed_deliveries_reopened"] += 1
            re_rider_id = re_res.json().get("reassigned_rider_id") if re_res.status_code == 200 else None
            if not re_rider_id:
                re_rider_id = await self._manual_assign_fallback(deliv_id, ops_admin, stats)
            if not re_rider_id or re_rider_id not in self.rider_id_to_session:
                return False
            assigned_rider_id = re_rider_id
            r_persona, r_sess = self.rider_id_to_session[assigned_rider_id]
            await r_sess.request(
                "POST",
                f"/api/rider/deliveries/{deliv_id}/respond",
                phase="dispatch_routing",
                action="rider.accept_reopened_offer",
                entity_type="delivery",
                entity_id=deliv_id,
                json={"accept": True},
            )
            pickup_pin = make_pickup_code(secret_val, deliv_id, self.settings.pickup_code_length)
            await r_sess.request(
                "POST",
                f"/api/rider/deliveries/{deliv_id}/pickup",
                phase="delivery_handover",
                action="rider.verify_pickup_pin",
                entity_type="delivery",
                entity_id=deliv_id,
                json={"pickup_code": pickup_pin},
            )

        # Rider navigates to customer drop-off & updates live GPS location
        if basket_idx % 4 == 0:
            await r_sess.request(
                "GET",
                f"/api/rider/deliveries/{deliv_id}/navigation",
                phase="delivery_handover",
                action="rider.navigate_to_customer",
                entity_type="delivery",
                entity_id=deliv_id,
            )

        await r_sess.request(
            "POST",
            "/api/rider/location",
            phase="delivery_handover",
            action="rider.ping_dropoff_gps",
            entity_type="rider",
            entity_id=assigned_rider_id,
            record_event=(basket_idx % 6 == 0),
            json={"latitude": f"{dest_lat:.6f}", "longitude": f"{dest_lon:.6f}"},
        )

        # Customer polls live delivery tracking
        if basket_idx % 4 == 1:
            await c_sess.request(
                "GET",
                f"/api/customer/orders/{order_id}/tracking",
                phase="delivery_handover",
                action="customer.track_live_delivery",
                entity_type="order",
                entity_id=order_id,
            )

        # Rider arrives at customer gate
        await r_sess.request(
            "POST",
            f"/api/rider/deliveries/{deliv_id}/arrive",
            phase="delivery_handover",
            action="rider.mark_arrived",
            entity_type="delivery",
            entity_id=deliv_id,
        )

        # Customer retrieves 4-digit HMAC handover PIN
        hc_res = await c_sess.request(
            "GET",
            f"/api/customer/orders/{order_id}/handover-code",
            phase="delivery_handover",
            action="customer.get_handover_pin",
            entity_type="order",
            entity_id=order_id,
        )
        if hc_res.status_code != 200:
            return False
        handover_pin = hc_res.json()["handover_code"]

        # Determine exact payable amount for Cash-on-Delivery orders
        complete_payload: dict[str, Any] = {
            "handover_code": handover_pin,
            "id_checked": bool(requires_id),
            "proof_photo_url": f"/media/pod/order_{order_id}.jpg",
        }
        if requires_id:
            stats["age_restricted_id_checks"] += 1

        if pay_method == "cash":
            async with self.session_factory() as db:
                ord_fresh = await db.get(Order, order_id)
                owed = ord_fresh.adjusted_total if (ord_fresh and ord_fresh.adjusted_total is not None) else ord_fresh.total
            complete_payload["cash_collected"] = str(owed)

        cmp_res = await r_sess.request(
            "POST",
            f"/api/rider/deliveries/{deliv_id}/complete",
            phase="delivery_handover",
            action="rider.complete_handover",
            entity_type="delivery",
            entity_id=deliv_id,
            payload_summary={"payment": pay_method, "id_checked": bool(requires_id)},
            json=complete_payload,
        )
        if cmp_res.status_code == 200:
            stats["orders_completed"] += 1
            if pay_method == "cash":
                stats["cash_settled"] += 1
            return True
        return False

    async def _manual_assign_fallback(
        self,
        delivery_id: int,
        ops_admin: AgentSession,
        stats: dict[str, Any],
    ) -> int | None:
        async with self.session_factory() as db:
            # Clear any expired cooldowns and find an approved online rider with capacity
            riders = list(
                (
                    await db.execute(
                        select(Rider).where(
                            Rider.id.in_(list(self.rider_id_to_session.keys())),
                            Rider.status != RiderStatus.OFFLINE,
                        )
                    )
                ).scalars().all()
            )
            if not riders:
                # Re-online riders if suspended/offline
                for rid in self.rider_id_to_session:
                    r_obj = await db.get(Rider, rid)
                    if r_obj and r_obj.approval_status.value == "approved":
                        r_obj.status = RiderStatus.AVAILABLE
                        r_obj.dispatch_cooldown_until = None
                await db.commit()
                riders = list(
                    (await db.execute(select(Rider).where(Rider.id.in_(list(self.rider_id_to_session.keys()))))).scalars().all()
                )
            chosen_rid = riders[0].id if riders else None

        if chosen_rid is None:
            return None

        m_res = await ops_admin.request(
            "POST",
            f"{self.admin_prefix}/deliveries/{delivery_id}/assign",
            phase="dispatch_routing",
            action="ops_admin.manual_assign_rider",
            entity_type="delivery",
            entity_id=delivery_id,
            data={"rider_id": str(chosen_rid)},
        )
        if m_res.status_code == 200:
            stats["manual_dispatches"] += 1
            return chosen_rid
        return None

    async def _submit_customer_reviews(
        self,
        *,
        basket_idx: int,
        order_id: int,
        fulfilment: str,
        c_sess: AgentSession,
        sup_admin: AgentSession,
        stats: dict[str, Any],
    ) -> None:
        st_res = await c_sess.request(
            "GET",
            f"/api/customer/orders/{order_id}/reviews",
            phase="reviews_moderation",
            action="customer.check_reviewable_items",
            entity_type="order",
            entity_id=order_id,
            record_event=(basket_idx % 5 == 0),
        )
        if st_res.status_code != 200:
            return
        rev_status = st_res.json()

        # 1. Product review
        prods = rev_status.get("reviewable_products", [])
        if prods:
            target_prod = self.rng.choice(prods)
            p_rating = self.rng.choices([5, 4, 3, 2, 1], weights=[0.52, 0.30, 0.10, 0.05, 0.03], k=1)[0]
            comments_by_rating = {
                5: "Fresh quality and great value from Bansi Mega Supermarket!",
                4: "Good packaging and accurate weight, will reorder.",
                3: "Decent item quality, met basic expectations.",
                2: "Packaging was slightly dented on arrival.",
                1: "Not as fresh as expected, please check shelf batch.",
            }
            pr_res = await c_sess.request(
                "POST",
                "/api/customer/reviews",
                phase="reviews_moderation",
                action="customer.submit_product_review",
                entity_type="review",
                payload_summary={"product_id": target_prod["product_id"], "rating": p_rating},
                json={
                    "target_type": ReviewTargetType.PRODUCT.value,
                    "order_id": order_id,
                    "product_id": target_prod["product_id"],
                    "rating": p_rating,
                    "comment": comments_by_rating[p_rating],
                },
            )
            if pr_res.status_code == 201:
                stats["product_reviews_submitted"] += 1
                rev_id = pr_res.json()["id"]
                # Support Admin moderates occasional low/flagged review
                if p_rating == 1 and self.rng.random() < 0.5:
                    await sup_admin.request(
                        "POST",
                        f"{self.admin_prefix}/reviews/{rev_id}/toggle-publish",
                        phase="reviews_moderation",
                        action="support_admin.moderate_review",
                        entity_type="review",
                        entity_id=rev_id,
                    )
                    stats["reviews_moderated"] += 1

        # 2. Rider delivery review
        if fulfilment == FulfilmentType.DELIVERY.value and rev_status.get("can_review_delivery"):
            d_rating = self.rng.choices([5, 4, 3, 2], weights=[0.58, 0.28, 0.10, 0.04], k=1)[0]
            dr_res = await c_sess.request(
                "POST",
                "/api/customer/reviews",
                phase="reviews_moderation",
                action="customer.submit_delivery_review",
                entity_type="review",
                payload_summary={"rider_id": rev_status.get("rider_id"), "rating": d_rating},
                json={
                    "target_type": ReviewTargetType.DELIVERY.value,
                    "order_id": order_id,
                    "rating": d_rating,
                    "comment": "Fast Migori delivery and polite handover!" if d_rating >= 4 else "Arrived okay, slight traffic delay.",
                },
            )
            if dr_res.status_code == 201:
                stats["delivery_reviews_submitted"] += 1

    async def _process_pending_refunds(
        self,
        fin_admin: AgentSession,
        *,
        super_admin: AgentSession,
        stats: dict[str, Any],
    ) -> None:
        async with self.session_factory() as db:
            pending_refunds = list(
                (
                    await db.execute(
                        select(Refund).where(Refund.status.in_((RefundStatus.REQUESTED, RefundStatus.APPROVED)))
                    )
                ).scalars().all()
            )

        for rf in pending_refunds:
            if rf.status == RefundStatus.REQUESTED:
                # Maker-checker: if fin_admin requested it, super_admin approves; else fin_admin approves
                approver = super_admin if rf.requested_by == fin_admin.user_id else fin_admin
                ap_res = await approver.request(
                    "POST",
                    f"{self.admin_prefix}/finance/refunds/{rf.id}/approve",
                    phase="treasury_settlement",
                    action="finance.approve_refund_maker_checker",
                    entity_type="refund",
                    entity_id=rf.id,
                )
                if ap_res.status_code != 200:
                    continue

            b2c_receipt = f"B2CRF{rf.id:04d}{uuid.uuid4().hex[:4].upper()}"
            st_res = await fin_admin.request(
                "POST",
                f"{self.admin_prefix}/finance/refunds/{rf.id}/settle",
                phase="treasury_settlement",
                action="finance.settle_b2c_refund",
                entity_type="refund",
                entity_id=rf.id,
                data={"receipt": b2c_receipt},
            )
            if st_res.status_code == 200:
                stats["refunds_settled"] += 1

    async def _run_periodic_operations(
        self,
        *,
        basket_idx: int,
        all_prod_ids: list[int],
        inv_admin: AgentSession,
        ops_admin: AgentSession,
        fin_admin: AgentSession,
        stock_clerk_sess: AgentSession,
        stats: dict[str, Any],
    ) -> None:
        # 1. Admins inspect economics, dashboard & dispatch SLA sweeper
        await ops_admin.request(
            "POST",
            f"{self.admin_prefix}/deliveries/sweep",
            phase="dispatch_routing",
            action="ops_admin.run_sla_timer_sweep",
        )
        await fin_admin.request(
            "GET",
            f"{self.admin_prefix}/products/export",
            phase="treasury_settlement",
            action="finance_admin.export_catalogue_economics_csv",
        )

        # 2. Stock Clerk performs a physical stock-take & Inventory Admin records minor spoilage write-off
        sample_pid = self.rng.choice(all_prod_ids)
        async with self.session_factory() as db:
            inv_row = await db.get(Inventory, sample_pid)
            cur_on_hand = inv_row.quantity_on_hand if inv_row else Decimal("200")
            cur_reserved = inv_row.quantity_reserved if inv_row else Decimal("0")

        if cur_on_hand - cur_reserved > Decimal("15"):
            await inv_admin.request(
                "POST",
                f"{self.admin_prefix}/inventory/{sample_pid}/write-off",
                phase="catalogue_inventory",
                action="inventory_admin.write_off_damaged_stock",
                entity_type="inventory",
                entity_id=sample_pid,
                data={"quantity": "2", "note": f"Routine shelf inspection damaged packaging (cycle {basket_idx})"},
            )
            await stock_clerk_sess.request(
                "POST",
                f"{self.staff_prefix}/inventory/{sample_pid}/stock-take",
                phase="catalogue_inventory",
                action="stock_clerk.reconcile_stock_take",
                entity_type="inventory",
                entity_id=sample_pid,
                data={"counted": str(cur_on_hand - Decimal("1")), "note": f"Cycle count #{basket_idx}"},
            )

        # 3. Riders inspect wallet earnings, reviews, and withdraw M-Pesa B2C payouts
        for r_persona, r_sess in list(self.rider_id_to_session.values())[:4]:
            w_res = await r_sess.request(
                "GET",
                "/api/rider/wallet",
                phase="treasury_settlement",
                action="rider.inspect_wallet",
                entity_type="rider",
                entity_id=r_sess.profile_id,
            )
            if w_res.status_code == 200:
                avail = Decimal(str(w_res.json().get("available_balance", "0")))
                if avail >= Decimal("100.00"):
                    wd_amt = (avail * Decimal("0.60")).quantize(Decimal("1.00"))
                    if wd_amt >= Decimal("50.00"):
                        wd_res = await r_sess.request(
                            "POST",
                            "/api/rider/wallet/withdraw",
                            phase="treasury_settlement",
                            action="rider.withdraw_mpesa_b2c",
                            entity_type="rider_payout",
                            payload_summary={"amount": str(wd_amt)},
                            json={"amount": str(wd_amt), "phone": r_persona.phone},
                        )
                        if wd_res.status_code == 201:
                            stats["rider_withdrawals"] += 1

    # -------------------------------------------------------------------------
    # PHASE 4 IMPLEMENTATION: SYSTEMATIC CO-ALGORITHM BENCHMARKS
    # -------------------------------------------------------------------------
    async def _run_phase4_algorithmic_sweeps(self, road_router: RoadNetworkRouter) -> None:
        async with self.session_factory() as db:
            sim_svc = SimulationService(db)
            baskets, _ = await sim_svc._load_live_baskets_and_products()
            total_baskets = len(baskets)

            # 1. Corpus Scaling Curve: Apriori vs FP-Growth at increasing transaction volumes
            checkpoints = sorted({c for c in [30, 60, 100, 150, 200, 250, 300, total_baskets] if 0 < c <= total_baskets})
            for cp in checkpoints:
                cfg = MiningConfig(
                    min_support=0.015,
                    min_support_count=2.0,
                    min_confidence=0.20,
                    min_lift=1.0,
                    max_itemset_size=4,
                )
                await sim_svc.record_recommender_comparison(
                    self.run_id,
                    context="corpus_scaling_sweep",
                    custom_config=cfg,
                    max_baskets=cp,
                    commit=False,
                )

            # 2. Support Threshold Sensitivity Sweep on full corpus
            for min_sup in (0.008, 0.010, 0.015, 0.020, 0.030, 0.050):
                cfg = MiningConfig(
                    min_support=min_sup,
                    min_support_count=2.0,
                    min_confidence=0.20,
                    min_lift=1.0,
                    max_itemset_size=4,
                )
                await sim_svc.record_recommender_comparison(
                    self.run_id,
                    context="support_sensitivity_sweep",
                    custom_config=cfg,
                    commit=False,
                )

            # 3. Stratified O-D Road Network Sweep: Dijkstra vs A* (travel_time AND distance modes)
            pts = sample_connected_road_locations(
                road_router, self.rng, max(20, self.config.od_benchmark_pairs * 2), (0.3, 6.7)
            )
            sm_lat, sm_lon = road_router.supermarket_coords
            n_pairs = self.config.od_benchmark_pairs
            for i in range(n_pairs):
                p_dest = pts[i % len(pts)]
                # Supermarket -> Customer under both travel_time and distance weights
                await sim_svc.record_routing_comparison(
                    self.run_id,
                    source_lat=sm_lat,
                    source_lon=sm_lon,
                    target_lat=p_dest[0],
                    target_lon=p_dest[1],
                    context="od_matrix_travel_time",
                    weight_mode="travel_time",
                    commit=False,
                )
                if i < 20:
                    await sim_svc.record_routing_comparison(
                        self.run_id,
                        source_lat=sm_lat,
                        source_lon=sm_lon,
                        target_lat=p_dest[0],
                        target_lon=p_dest[1],
                        context="od_matrix_distance",
                        weight_mode="distance",
                        commit=False,
                    )
                # Cross-town Rider -> Customer / Arbitrary O-D pair
                p_orig = pts[(i + 7) % len(pts)]
                if i < 25 and (p_orig[0] != p_dest[0] or p_orig[1] != p_dest[1]):
                    await sim_svc.record_routing_comparison(
                        self.run_id,
                        source_lat=p_orig[0],
                        source_lon=p_orig[1],
                        target_lat=p_dest[0],
                        target_lon=p_dest[1],
                        context="od_crosstown_travel_time",
                        weight_mode="travel_time",
                        commit=False,
                    )

            await db.commit()
