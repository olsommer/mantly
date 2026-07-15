"""Admin Outlook manifest endpoint."""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response as FastAPIResponse

from automail.api.admin.deps import ProjectAdminDep, _require_ctx_capability
from automail.core.brand import get_brand

router = APIRouter()

# ── Manifest download — project-scoped ─────────────────────────────────────────

_MANIFEST_TEMPLATE_PATH = Path(
    os.getenv(
        "MANIFEST_TEMPLATE_PATH",
        str(Path(__file__).resolve().parents[4] / "addin" / "manifest.xml"),
    )
)

_DEFAULT_ADDIN_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def _get_public_base_url(request: Request) -> str:
    explicit = os.getenv("PUBLIC_URL", "").strip() or os.getenv("MANIFEST_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}"


def _get_manifest_url(env_name: str, fallback: str) -> str:
    explicit = os.getenv(env_name, "").strip()
    return explicit.rstrip("/") if explicit else fallback


def _get_taskpane_url(addin_url: str, public_base_url: str) -> str:
    explicit = os.getenv("ADDIN_TASKPANE_URL", "").strip()
    if explicit:
        return explicit
    if addin_url == public_base_url:
        return f"{addin_url}/addin/index.html"
    return f"{addin_url}/"


@router.get("/projects/{pid}/manifest")
async def download_manifest(
    request: Request,
    ctx: ProjectAdminDep,
    base_url: str | None = None,
    addin_base_url: str | None = None,
    asset_base_url: str | None = None,
) -> FastAPIResponse:
    _require_ctx_capability(ctx, "canDownloadManifest")
    if not _MANIFEST_TEMPLATE_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Manifest template not found at {_MANIFEST_TEMPLATE_PATH}",
        )
    template = _MANIFEST_TEMPLATE_PATH.read_text(encoding="utf-8")
    addin_id = os.getenv("ADDIN_ID", "").strip() or _DEFAULT_ADDIN_ID
    public_base_url = base_url.rstrip("/") if base_url else _get_public_base_url(request)
    addin_url = addin_base_url.rstrip("/") if addin_base_url else _get_manifest_url("ADDIN_BASE_URL", public_base_url)
    asset_url = asset_base_url.rstrip("/") if asset_base_url else _get_manifest_url("ASSET_BASE_URL", public_base_url)
    taskpane_url = _get_taskpane_url(addin_url, public_base_url)
    manifest_xml = (
        template
        .replace("BACKEND_URL", public_base_url)
        .replace("ADDIN_BASE_URL", addin_url)
        .replace("ASSET_BASE_URL", asset_url)
        .replace("ADDIN_TASKPANE_URL", taskpane_url)
        .replace("ADDIN_ID", addin_id)
        .replace("APP_BRAND_NAME", get_brand().addin_display_name)
        .replace("APP_PROVIDER_NAME", get_brand().provider_name)
        .replace("APP_DESCRIPTION_DE", get_brand().description_de)
        .replace("APP_SUPPORT_URL", get_brand().support_url)
    )
    return FastAPIResponse(
        content=manifest_xml,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="manifest.xml"'},
    )
