import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

# load config.env FIRST — before any automail imports that read os.getenv at module level
from dotenv import load_dotenv

is_loaded = load_dotenv("config.env")

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import Receive, Scope, Send

from automail.addon.gmail.router import router as gmail_addon_router
from automail.api.admin.billing import admin_router as billing_admin_router
from automail.api.admin.billing import webhook_router as billing_webhook_router
from automail.api.admin.evals import mark_orphaned_eval_runs_failed
from automail.api.admin.evals import router as eval_router
from automail.api.admin.license import admin_router as license_admin_router
from automail.api.admin.license import public_router as license_public_router
from automail.api.admin.router import router as admin_router
from automail.api.auth import router as auth_router
from automail.api.email import router as email_router
from automail.api.internal_support import router as internal_support_router
from automail.api.support_knowledge import router as support_knowledge_router
from automail.api.support_portal import router as support_portal_router
from automail.api.support_web_chat import router as support_web_chat_router
from automail.billing.license import LicenseMiddleware, is_license_required, validate_license_on_startup
from automail.core.brand import get_brand

# Set up structured logging right after env is loaded
from automail.core.logging_config import setup_logging
from automail.core.rate_limit import limiter
from automail.core.runtime_flags import demo_routes_available, is_saas_mode
from automail.db.pocketbase.bootstrap_app_schema import ensure_app_collections_schema
from automail.db.pocketbase.bootstrap_common import validate_pb_bootstrap_env
from automail.db.pocketbase.bootstrap_mail import sync_pocketbase_mail_settings
from automail.db.pocketbase.bootstrap_migration import migrate_project_config_to_tenant
from automail.db.pocketbase.bootstrap_onprem import bootstrap_onprem_tenant
from automail.db.pocketbase.bootstrap_users import ensure_users_collection_schema
from automail.db.pocketbase.migration import migrate_to_projects
from automail.support.scheduler import (
    start_channel_test_job_scheduler,
    start_support_crm_sync_scheduler,
    start_support_delivery_scheduler,
    start_support_processing_expiry_scheduler,
    start_support_sla_scheduler,
    start_support_sync_scheduler,
)

setup_logging()

logger = logging.getLogger(__name__)
logger.info("ENV loaded: %s", is_loaded)
brand = get_brand()

# ── Startup validation ────────────────────────────────────────────────────────

REQUIRE_AUTH: bool = os.getenv("REQUIRE_AUTH", "false").lower() == "true"

if is_saas_mode() and not REQUIRE_AUTH:
    raise RuntimeError("REQUIRE_AUTH=true is required when IS_SAAS=true")

if REQUIRE_AUTH and not os.getenv("JWT_SECRET"):
    raise RuntimeError(
        "JWT_SECRET must be set when REQUIRE_AUTH=true. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

if REQUIRE_AUTH:
    raw_cors = os.getenv("CORS_ORIGINS", "*")
    if raw_cors.strip() == "*":
        raise RuntimeError(
            "CORS_ORIGINS must not be '*' when REQUIRE_AUTH=true. "
            "Set it to the actual add-in/admin origins (e.g. https://app.mantly.io,https://addin.mantly.io)."
        )

validate_pb_bootstrap_env(REQUIRE_AUTH)

# PocketBase handles email verification and password reset.  Startup syncs
# the public app URL and SMTP settings into PocketBase from env.

PB_URL: str = os.getenv("PB_URL", "http://localhost:8090")
logger.info("PocketBase URL: %s", PB_URL)

# Static files directory for the built Outlook add-in
STATIC_FILES_DIR = Path(os.getenv(
    "STATIC_FILES_DIR",
    Path(__file__).resolve().parent.parent.parent / "addin" / "dist"
))

ADMIN_STATIC_DIR = Path(os.getenv(
    "ADMIN_STATIC_FILES_DIR",
    Path(__file__).resolve().parent.parent.parent / "admin" / "dist"
))

ASSETS_DIR = Path(os.getenv(
    "ASSETS_DIR",
    Path(__file__).resolve().parent.parent / "assets"
))


class SPAStaticFiles(StaticFiles):
    """StaticFiles subclass that serves index.html for any path not matching a
    real file — the standard SPA catch-all pattern."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        except Exception:
            # Path didn't match a static file — serve index.html so the SPA
            # router can handle it client-side.
            scope["path"] = "/index.html"
            await super().__call__(scope, receive, send)


def _admin_index_response() -> FileResponse:
    index_path = ADMIN_STATIC_DIR / "index.html"
    return FileResponse(index_path)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if REQUIRE_AUTH:
            result = ensure_users_collection_schema()
            if result.updated:
                logger.info("PocketBase users collection bootstrap completed")
            else:
                logger.info("PocketBase users collection schema already current")
            sync_pocketbase_mail_settings()

        ensure_app_collections_schema()
        bootstrap_onprem_tenant()
        migrate_project_config_to_tenant()
        mark_orphaned_eval_runs_failed()

        # Migrate existing tenants to projects architecture (idempotent)
        try:
            migrate_to_projects()
        except Exception:
            logger.exception("Projects migration failed — continuing with degraded functionality")

        # License validation (on-prem only — noop when LICENSE_KEY is not set)
        validate_license_on_startup()

        start_support_sync_scheduler()
        start_support_delivery_scheduler()
        start_support_crm_sync_scheduler()
        start_support_sla_scheduler()
        start_support_processing_expiry_scheduler()
        start_channel_test_job_scheduler()

        yield

    app = FastAPI(
        title=brand.name,
        description=brand.description,
        version="1.0.0",
        lifespan=lifespan,
    )

    # Attach rate limiter and its exception handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, cast(Any, _rate_limit_exceeded_handler))

    # Configure CORS
    # Set CORS_ORIGINS env var to a comma-separated list of allowed origins.
    # Defaults to "*" for local dev; restrict this in production.
    raw_origins = os.getenv("CORS_ORIGINS", "*")
    allow_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security response headers
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # The Outlook add-in runs inside an iframe hosted by Office.
        # X-Frame-Options: SAMEORIGIN would block it, so we skip it for
        # /addin/ and /assets/ paths.  All other routes keep the header.
        path = request.url.path
        if not (path.startswith("/addin") or path.startswith("/assets")):
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    # License enforcement (on-prem only — noop when LICENSE_KEY is not set)
    if is_license_required():
        app.add_middleware(LicenseMiddleware)

    # Request / response logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            '{"method": "%s", "path": "%s", "status": %d, "duration_ms": %d}',
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    # Include API routes first so they take priority over static files
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    app.include_router(email_router, prefix="/api", tags=["email"])
    app.include_router(internal_support_router, prefix="/api/internal", tags=["internal"])
    app.include_router(support_knowledge_router, tags=["support-knowledge"])
    app.include_router(support_portal_router, tags=["support-portal"])
    app.include_router(support_web_chat_router, tags=["support-web-chat"])
    app.include_router(gmail_addon_router)
    app.include_router(admin_router, tags=["admin"])  # prefix="/api/admin" set in router.py
    app.include_router(eval_router, tags=["eval"])  # prefix="/api/admin/eval" set in eval_router.py
    app.include_router(license_public_router, tags=["license"])  # POST /api/license/validate
    app.include_router(license_admin_router, prefix="/api/admin", tags=["license-admin"])
    app.include_router(billing_admin_router, tags=["billing"])  # /api/admin/billing/*
    app.include_router(billing_webhook_router, tags=["billing-webhook"])  # POST /api/webhooks/stripe

    # Verification links are deep links into the admin SPA.
    @app.get("/verify-email")
    @app.get("/verify-email/")
    async def verify_email_entry():
        return _admin_index_response()

    if demo_routes_available():
        from automail.core.capabilities import require_demo_endpoint_access
        from automail.demo.actions import (
            DemoGreenCardRequest,
            DemoProcessStartRequest,
            DemoUpdateTitleRequest,
            mock_demo_green_card_request,
            mock_demo_motor_policy,
            mock_demo_process_start,
            mock_demo_update_title,
        )
        from automail.demo.crm import lookup_demo_customer
        from automail.demo.e2e_fixtures import (
            E2EFixtureManifestError,
            E2EFixtureNotFound,
            e2e_fixture_runtime_enabled,
            lookup_e2e_tool_fixture,
            merge_e2e_tool_input,
        )
        from automail.demo.shipments import lookup_demo_shipment_status, open_demo_logistics_ticket

        @app.get("/demo/crm")
        async def demo_crm_lookup(sender_email: str, request: Request):
            require_demo_endpoint_access(request)
            return lookup_demo_customer(sender_email)

        @app.get("/demo/logistics/shipment-status")
        async def demo_shipment_status_lookup(
            request: Request,
            sender_email: str = "",
            order_number: str = "",
            tracking_number: str = "",
        ):
            require_demo_endpoint_access(request)
            return lookup_demo_shipment_status(
                sender_email=sender_email,
                order_number=order_number,
                tracking_number=tracking_number,
            )

        @app.get("/demo/e2e/tool/{persona_id}/{tool_name}")
        async def demo_e2e_tool_lookup(
            persona_id: str,
            tool_name: str,
            request: Request,
        ):
            require_demo_endpoint_access(request)
            if not e2e_fixture_runtime_enabled():
                raise HTTPException(status_code=404, detail="Not found")
            supplied_input = merge_e2e_tool_input(request.query_params.multi_items())
            try:
                return lookup_e2e_tool_fixture(persona_id, tool_name, supplied_input)
            except E2EFixtureNotFound as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except E2EFixtureManifestError as exc:
                logger.exception("E2E fixture manifest lookup failed")
                raise HTTPException(
                    status_code=500,
                    detail="E2E fixture manifests are unavailable",
                ) from exc

        @app.post("/demo/logistics/open-ticket")
        async def demo_logistics_open_ticket(payload: dict[str, Any], request: Request):
            require_demo_endpoint_access(request)
            return open_demo_logistics_ticket(payload)

        @app.post("/demo/process-start")
        async def demo_process_start(payload: DemoProcessStartRequest, request: Request):
            require_demo_endpoint_access(request)
            return mock_demo_process_start(payload)

        @app.post("/demo/update-title")
        async def demo_update_title(payload: DemoUpdateTitleRequest, request: Request):
            require_demo_endpoint_access(request)
            return mock_demo_update_title(payload)

        @app.get("/demo/insurance/motor-policy")
        async def demo_motor_policy(sender_email: str = "", policy_number: str = ""):
            return mock_demo_motor_policy(sender_email=sender_email, policy_number=policy_number)

        @app.post("/demo/insurance/green-card")
        async def demo_green_card(payload: DemoGreenCardRequest):
            return mock_demo_green_card_request(payload)
    else:
        logger.info("Demo endpoints disabled. Set ENABLE_DEMO_MODE=true to enable /demo/* routes.")

        @app.api_route("/demo/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
        async def demo_disabled(full_path: str):
            raise HTTPException(status_code=404, detail="Demo endpoints are disabled")

    # /addin (no trailing slash) → /addin/ so StaticFiles can serve index.html
    @app.get("/addin")
    async def addin_redirect(request: Request):
        target = "/addin/"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(url=target, status_code=301)

    # Serve icon/asset files at /assets (referenced by Outlook manifest)
    if ASSETS_DIR.exists() and ASSETS_DIR.is_dir():
        logger.info("Serving assets from: %s", ASSETS_DIR)
        app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets-static")
    else:
        logger.info("No assets directory found at %s", ASSETS_DIR)

    # Serve add-in static files at /addin if built
    if STATIC_FILES_DIR.exists() and STATIC_FILES_DIR.is_dir():
        logger.info("Serving add-in from: %s", STATIC_FILES_DIR)
        app.mount("/addin", StaticFiles(directory=str(STATIC_FILES_DIR), html=True), name="addin-static")
    else:
        logger.info("No add-in build found at %s — add-in disabled", STATIC_FILES_DIR)

    # Serve admin SPA at / if built
    if ADMIN_STATIC_DIR.exists() and ADMIN_STATIC_DIR.is_dir():
        logger.info("Serving admin SPA from: %s", ADMIN_STATIC_DIR)
        app.mount("/", SPAStaticFiles(directory=str(ADMIN_STATIC_DIR), html=True), name="admin-static")
    else:
        logger.info("No admin build found at %s", ADMIN_STATIC_DIR)

    return app


app = create_app()


def main():
    """Run the FastAPI application."""

    reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(
        "automail.main:app",
        host="0.0.0.0",
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
