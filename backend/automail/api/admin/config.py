"""Admin project list and project config endpoints."""

from typing import Any

from fastapi import APIRouter

from automail.api.admin.deps import AuthDep, ProjectEditorDep, ProjectViewerDep, _require_ctx_capability
from automail.core.config import AdminConfig, is_masked, mask_api_key, read_config, write_config
from automail.db.pocketbase.client import list_tenant_projects
from automail.pipeline.drafts import ensure_draft_exists, get_draft_source

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────
# Projects list (tenant-level)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/projects")
async def list_projects(auth: AuthDep) -> list[dict]:
    """List projects the current user has access to.

    Root users see all tenant projects.  Non-root users see only their
    project memberships.
    """
    if not auth.tenant_id:
        return []  # no-auth dev mode

    if auth.is_root:
        return list_tenant_projects(auth.tenant_id)

    from automail.db.pocketbase.client import get_user_projects
    return get_user_projects(auth.user_id)


# ──────────────────────────────────────────────────────────────────────────────
# Config (project-scoped)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/config")
async def get_config(ctx: ProjectViewerDep) -> dict:
    """Return the current admin configuration (from draft)."""
    draft = get_draft_source(ctx.project_id, tenant_id=ctx.tenant_id)
    ensure_draft_exists(ctx.project_id, tenant_id=ctx.tenant_id)
    config = read_config(config_path=draft)
    return {
        "orgName": config.org_name,
        "orgDescription": config.org_description,
        "useCustomOrg": config.use_custom_org,
        "llmModel": config.llm_model,
        "llmProvider": config.llm_provider,
        "llmApiKey": mask_api_key(config.llm_api_key),
        "llmCustomBaseUrl": config.llm_custom_base_url,
        "llmCustomModel": config.llm_custom_model,
        "useCustomLlm": config.use_custom_llm,
        "identityNotes": config.identity_notes,
        "tool": config.tool,
        "useCustomSecurity": config.use_custom_security,
        "phishingMonitoringEnabled": config.phishing_monitoring_enabled,
        "promptInjectionMonitoringEnabled": config.prompt_injection_monitoring_enabled,
    }


def _nonempty(value: Any) -> bool:
    return bool(str(value or "").strip())


def _requested_byok_llm(body: dict, incoming_key: str | None = None) -> bool:
    if incoming_key is not None and _nonempty(incoming_key) and not is_masked(incoming_key):
        return True
    return bool(
        body.get("useCustomLlm") is True
        or body.get("llmProvider") == "custom"
        or _nonempty(body.get("llmCustomBaseUrl"))
        or _nonempty(body.get("llmCustomModel"))
    )


@router.put("/projects/{pid}/config")
async def update_config(body: dict, ctx: ProjectEditorDep) -> dict:
    """Update the admin configuration (writes to draft)."""
    _require_ctx_capability(ctx, "canEditProjectConfig")
    draft = get_draft_source(ctx.project_id, tenant_id=ctx.tenant_id)
    ensure_draft_exists(ctx.project_id, tenant_id=ctx.tenant_id)
    current = read_config(config_path=draft)

    # Preserve existing API key if the frontend sends back a masked value.
    incoming_key = body.get("llmApiKey", current.llm_api_key)
    if is_masked(incoming_key):
        incoming_key = current.llm_api_key

    security_fields_touched = (
        "phishingMonitoringEnabled" in body
        or "promptInjectionMonitoringEnabled" in body
    )
    use_custom_security_value = body.get(
        "useCustomSecurity",
        True if security_fields_touched else current.use_custom_security,
    )

    if ctx.tenant_id:
        from automail.billing.plans import require_feature

        if _requested_byok_llm(body, incoming_key=body.get("llmApiKey")):
            require_feature(ctx.tenant_id, "byok_llm")
        if body.get("llmProvider") == "custom" or _nonempty(body.get("llmCustomBaseUrl")):
            require_feature(ctx.tenant_id, "custom_llm_gateway")
        use_custom_security = use_custom_security_value is True
        if use_custom_security and (
            body.get("phishingMonitoringEnabled", current.phishing_monitoring_enabled) is True
            or body.get("promptInjectionMonitoringEnabled", current.prompt_injection_monitoring_enabled) is True
        ):
            require_feature(ctx.tenant_id, "security_monitoring")

    updated = AdminConfig(
        org_name=body.get("orgName", current.org_name),
        org_description=body.get("orgDescription", current.org_description),
        use_custom_org=body.get("useCustomOrg", current.use_custom_org),
        llm_model=body.get("llmModel", current.llm_model),
        llm_provider=body.get("llmProvider", current.llm_provider),
        llm_api_key=incoming_key,
        llm_custom_base_url=body.get("llmCustomBaseUrl", current.llm_custom_base_url),
        llm_custom_model=body.get("llmCustomModel", current.llm_custom_model),
        use_custom_llm=body.get("useCustomLlm", current.use_custom_llm),
        identity_notes=body.get("identityNotes", current.identity_notes),
        tool=body.get("tool", current.tool),
        use_custom_security=use_custom_security_value,
        phishing_monitoring_enabled=body.get(
            "phishingMonitoringEnabled",
            current.phishing_monitoring_enabled,
        ),
        prompt_injection_monitoring_enabled=body.get(
            "promptInjectionMonitoringEnabled",
            current.prompt_injection_monitoring_enabled,
        ),
    )
    write_config(updated, config_path=draft)

    # Invalidate cached LLM singletons so changes take effect immediately.
    from automail.llm import invalidate_all
    invalidate_all()

    return {"status": "ok"}
