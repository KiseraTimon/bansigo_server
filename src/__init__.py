# src/__init__.py

from fastapi import FastAPI, status, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.exception_handlers import request_validation_exception_handler, http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from starlette.exceptions import HTTPException as StarletteHTTPException

from pathlib import Path

from src.database import Base, engine
from config import Settings, get_settings
from utilities import RequestContextMiddleware, setup_logging


# path references
path = Path(__file__)
STATIC_DIR = f"{path.resolve().parent}/static"
MEDIA_DIR = f"{path.resolve().parent}/media"
TEMPLATES_DIR = f"{path.resolve().parent}/templates"


# database instance
def _sync_missing_columns(sync_conn) -> None:
    """Idempotently adds newly introduced columns on existing database tables (e.g. MySQL dump)."""
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    alterations = {
        "deliveries": [
            ("offer_expires_at", "DATETIME NULL"),
            ("pickup_due_at", "DATETIME NULL"),
            ("delivery_due_at", "DATETIME NULL"),
            ("is_overdue", "BOOLEAN NOT NULL DEFAULT 0"),
            ("overdue_notified_at", "DATETIME NULL"),
            ("overdue_escalated_at", "DATETIME NULL"),
            ("needs_manual_assignment", "BOOLEAN NOT NULL DEFAULT 0"),
            ("manual_assignment_reason", "VARCHAR(255) NULL"),
            ("rejection_count", "INT NOT NULL DEFAULT 0"),
            ("pickup_code_hash", "VARCHAR(64) NULL"),
            ("pickup_attempts", "INT NOT NULL DEFAULT 0"),
        ],
        "riders": [
            ("unjustified_rejections_count", "INT NOT NULL DEFAULT 0"),
            ("total_rejections_count", "INT NOT NULL DEFAULT 0"),
            ("overdue_deliveries_count", "INT NOT NULL DEFAULT 0"),
            ("penalty_points", "INT NOT NULL DEFAULT 0"),
            ("dispatch_cooldown_until", "DATETIME NULL"),
        ],
        "notifications": [
            ("external_key", "VARCHAR(64) NULL"),
            ("is_deleted", "BOOLEAN NOT NULL DEFAULT 0"),
        ],
    }

    for table, cols in alterations.items():
        if table not in existing_tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        for col_name, col_def in cols:
            if col_name not in present:
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"))


async def _delivery_sweeper_loop(settings: Settings) -> None:
    """Background loop checking delivery offer timeouts, overdue SLAs, and unpaid M-Pesa sweeps."""
    import asyncio
    from src.database import AsyncSessionLocal
    from src.services.delivery_service import DeliveryService
    from utilities import get_logger

    log = get_logger(__name__)
    interval = max(5, int(getattr(settings, "delivery_sweeper_interval_seconds", 20)))

    while True:
        try:
            await asyncio.sleep(interval)
            async with AsyncSessionLocal() as session:
                svc = DeliveryService(session, settings)
                await svc.sweep_delivery_timers()
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("Delivery sweeper iteration failed: %s", exc)


async def lifespan(app: FastAPI):
    import asyncio
    # db startup
    import src.models   # noqa: F401
    async with engine.begin() as conn:
        # idempotent database creation
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sync_missing_columns)

    # Seed default delivery zones for Migori if table is empty
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.models import DeliveryZone
    from decimal import Decimal
    async with AsyncSessionLocal() as session:
        has_zones = (await session.execute(select(DeliveryZone).limit(1))).scalar_one_or_none()
        if has_zones is None:
            default_zones = [
                DeliveryZone(name="Migori Town Central", delivery_fee=Decimal("50.00"), min_order_amount=Decimal("100.00"), estimated_minutes=20, is_active=True),
                DeliveryZone(name="Kadika & Nyasare", delivery_fee=Decimal("70.00"), min_order_amount=Decimal("150.00"), estimated_minutes=30, is_active=True),
                DeliveryZone(name="Kakrao & Oruba", delivery_fee=Decimal("90.00"), min_order_amount=Decimal("200.00"), estimated_minutes=35, is_active=True),
                DeliveryZone(name="Suna West & Lichota", delivery_fee=Decimal("110.00"), min_order_amount=Decimal("250.00"), estimated_minutes=45, is_active=True),
            ]
            session.add_all(default_zones)
            await session.commit()

    # initialize OpenStreetMap road network graph router
    from src.algorithms.route_engines import init_router
    router = init_router()
    app.state.road_router = router

    sweeper_task = None
    settings = get_settings()
    if settings.app_env != "testing":
        sweeper_task = asyncio.create_task(_delivery_sweeper_loop(settings))

    yield

    # shutdowns
    if sweeper_task is not None:
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass
    from src.dependencies import get_mpesa_client
    if get_mpesa_client.cache_info().currsize:
        await get_mpesa_client().aclose()
    await engine.dispose()


# app factory
def create_app() -> FastAPI:
    """
    creates an instance of FastAPI
    :return: FastAPI
    """

    # app settings
    settings: Settings = get_settings()
    setup_logging(settings)


    # fastAPI object
    app = FastAPI(lifespan=lifespan)


    # middleware for logs
    app.add_middleware(RequestContextMiddleware)


    # mounting
    if Path(STATIC_DIR).is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    if Path(MEDIA_DIR).is_dir():
        app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

    # template object
    if Path(TEMPLATES_DIR).is_dir():
        app.state.templates = Jinja2Templates(directory=TEMPLATES_DIR)
        app.state.templates.env.globals["get_flashed_messages"] = lambda **kwargs: []

        from jinja2 import pass_context

        @pass_context
        def safe_url_for(context, name: str, **path_params):
            req = context["request"]
            if name == "static" and "filename" in path_params and "path" not in path_params:
                path_params["path"] = path_params.pop("filename")
            return req.url_for(name, **path_params)

        app.state.templates.env.globals["url_for"] = safe_url_for


    # routers
    from src.routers import router
    app.include_router(router)


    # http exception handler
    @app.exception_handler(StarletteHTTPException)
    async def http_exceptions(request: Request, exception: StarletteHTTPException):
        # determine if request expects JSON (API routes, AJAX calls, or mutation verbs)
        accept = request.headers.get("accept", "").lower()
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        content_type = request.headers.get("content-type", "").lower()

        if (
            request.url.path.startswith("/api")
            or "application/json" in accept
            or "application/json" in content_type
            or is_ajax
            or request.method in ("POST", "PATCH", "PUT", "DELETE")
        ):
            return await http_exception_handler(request, exception)

        message = (
            exception.detail
            if exception.detail else
            "An error occurred. Please check your request and try again"
        )

        # exceptions from browser views
        return app.state.templates.TemplateResponse(
            request,
            "errors.html",
            {
                "status_code": exception.status_code,
                "title": exception.status_code,
                "content": message
            },
            status_code=exception.status_code
        )


    # request validation exception handler
    @app.exception_handler(RequestValidationError)
    async def request_validation_exceptions(request: Request, exception: RequestValidationError):
        """
        handles request validation exceptions
        :param request: Request
        :param exception: RequestValidationError
        :return:
        """

        # exceptions from apis
        if request.url.path.startswith("/api"):
            return await request_validation_exception_handler(request, exception)

        # exceptions from views
        return app.state.templates.TemplateResponse(
            request,
            "errors.html",
            {
                "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
                "title": status.HTTP_422_UNPROCESSABLE_CONTENT,
                "content": "an error occurred; kindly verify the information you sent in is correct"
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )


    # unexpected errors
    @app.exception_handler(Exception)
    async def unhandled_exceptions(request: Request, exception: Exception):
        """
        handles internal server errors
        :param request: Request
        :return:
        """
        message = "Something went wrong on our side. Please try again later"
        headers = {"X-Request-ID": getattr(request.state, "request_id", "-")}

        # exceptions from apis
        if request.url.path.startswith("/api") or not hasattr(app.state, "templates"):
            return JSONResponse(
                {"detail": message},
                status_code=500,
                headers=headers
            )

        # exceptions from views
        return app.state.templates.TemplateResponse(
            request,
            "errors.html",
            {
                "status_code": 500,
                "title": 500,
                "content": message
            },
            status_code=500,
            headers=headers
        )


    # FastAPI instance
    return app
