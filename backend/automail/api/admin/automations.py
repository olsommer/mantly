"""Admin workflow automation endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import Field

from automail.api.admin.deps import AuthDep, ProjectEditorDep, ProjectViewerDep
from automail.db.pocketbase.client import (
    create_manual_issue,
    list_automation_rules,
    list_automation_runs,
    preview_automation_rules_for_issue,
    run_automation_rules_for_backlog,
    run_automation_rules_for_issue,
    support_analytics,
    upsert_automation_rule,
)
from automail.models import CamelCaseModel

router = APIRouter()

DEFAULT_HUMAN_LOOP_AGENT_QUESTION = "Draft an approval-ready response from the ticket context and knowledge base."


class AutomationRuleInput(CamelCaseModel):
    name: str
    active: bool = True
    trigger: str = "issue_created"
    conditions: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)


class AutomationManualRunInput(CamelCaseModel):
    issue_id: str
    trigger: str = "manual"


class AutomationBacklogRunInput(CamelCaseModel):
    trigger: str = "issue_created"
    status: str = "open"
    queue_key: str = ""
    limit: int = 25


class AutomationPreviewInput(AutomationManualRunInput):
    preview_rule: AutomationRuleInput | None = None


def _automation_proof_result(
    *,
    issue: dict[str, Any],
    tenant_id: str | None,
    project_id: str,
) -> dict[str, Any]:
    analytics = support_analytics(
        tenant_id=tenant_id,
        project_id=project_id,
    )
    launch_readiness = analytics.get("launchReadiness") if isinstance(analytics, dict) else {}
    return {
        "issue": issue,
        "launchReadiness": launch_readiness if isinstance(launch_readiness, dict) else {},
        "automationRuns": analytics.get("automationRuns", 0),
        "successfulAutomationRuns": analytics.get("successfulAutomationRuns", 0),
        "successfulHumanLoopAutomationRuns": analytics.get("successfulHumanLoopAutomationRuns", 0),
        "issuesNeedingApproval": analytics.get("issuesNeedingApproval", 0),
    }


def _action_creates_human_loop_agent_draft(action: dict[str, Any]) -> bool:
    action_type = str(action.get("type") or "").strip()
    if action_type not in {"prepare_agent_reply", "ask_agent", "agent_answer"}:
        return False
    if action.get("createDraft") is False or action.get("create_draft") is False:
        return False
    if action.get("approvalRequired") is False or action.get("approval_required") is False:
        return False
    return True


def _rule_has_human_loop_agent_draft(rule: dict[str, Any]) -> bool:
    if rule.get("active") is False:
        return False
    actions = rule.get("actions") if isinstance(rule.get("actions"), list) else []
    return any(_action_creates_human_loop_agent_draft(action) for action in actions if isinstance(action, dict))


def ensure_human_loop_automation_rule(
    *,
    tenant_id: str | None,
    project_id: str,
    actor_email: str,
) -> dict[str, Any]:
    clean_actor = actor_email.strip().lower()
    if not clean_actor:
        raise ValueError("Signed-in agent email is required")
    existing_rules = list_automation_rules(
        tenant_id=tenant_id,
        project_id=project_id,
        limit=200,
    )
    existing = next((rule for rule in existing_rules if _rule_has_human_loop_agent_draft(rule)), None)
    if existing:
        return {"created": False, "rule": existing}
    rule = upsert_automation_rule(
        tenant_id=tenant_id,
        project_id=project_id,
        name="Human-loop agent draft",
        trigger="issue_created",
        active=True,
        conditions={
            "requiresHuman": True,
            "unassigned": True,
        },
        actions=[
            {
                "type": "assign",
                "assigneeEmail": clean_actor,
            },
            {
                "type": "prepare_triage",
                "approvalRequired": True,
            },
            {
                "type": "prepare_custom_fields",
                "approvalRequired": True,
                "onlyMissing": True,
            },
            {
                "type": "prepare_agent_reply",
                "question": DEFAULT_HUMAN_LOOP_AGENT_QUESTION,
                "createDraft": True,
                "approvalRequired": True,
                "includeFeedbackLink": True,
            },
        ],
    )
    return {"created": True, "rule": rule}


def run_human_loop_automation_setup_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    actor_email: str,
) -> dict[str, Any]:
    setup = ensure_human_loop_automation_rule(
        tenant_id=tenant_id,
        project_id=project_id,
        actor_email=actor_email,
    )
    proof = run_human_loop_automation_proof(
        tenant_id=tenant_id,
        project_id=project_id,
        actor_email=actor_email,
    )
    return {**proof, "createdRule": setup["created"], "rule": setup["rule"]}


def run_human_loop_automation_proof(
    *,
    tenant_id: str | None,
    project_id: str,
    actor_email: str,
) -> dict[str, Any]:
    clean_actor = actor_email.strip().lower()
    if not clean_actor:
        raise ValueError("Signed-in agent email is required")
    issue = create_manual_issue(
        tenant_id=tenant_id,
        project_id=project_id,
        creator_email=clean_actor,
        subject="Launch proof: human-in-loop automation",
        from_address="launch-proof@example.invalid",
        contact_name="Launch Proof",
        account_name="Launch Proof",
        body="Synthetic ticket proving active support automation prepares an approval-required agent draft.",
        priority="normal",
        assignee_email="",
        queue_key="support",
        queue_name="Support",
        run_automations=True,
    )
    return _automation_proof_result(
        issue=issue,
        tenant_id=tenant_id,
        project_id=project_id,
    )


@router.get("/projects/{pid}/automations")
async def get_automation_rules(ctx: ProjectViewerDep, limit: int = 100) -> dict[str, Any]:
    return {
        "items": list_automation_rules(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            limit=max(1, min(limit, 200)),
        )
    }


@router.post("/projects/{pid}/automations")
async def create_automation_rule(body: AutomationRuleInput, ctx: ProjectEditorDep) -> dict[str, Any]:
    try:
        return upsert_automation_rule(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            name=body.name,
            trigger=body.trigger,
            active=body.active,
            conditions=body.conditions,
            actions=body.actions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/projects/{pid}/automations/{rule_id}")
async def update_automation_rule(rule_id: str, body: AutomationRuleInput, ctx: ProjectEditorDep) -> dict[str, Any]:
    try:
        return upsert_automation_rule(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            rule_id=rule_id,
            name=body.name,
            trigger=body.trigger,
            active=body.active,
            conditions=body.conditions,
            actions=body.actions,
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/projects/{pid}/automations/runs")
async def get_automation_runs(
    ctx: ProjectViewerDep,
    rule_id: str = "",
    issue_id: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    return {
        "items": list_automation_runs(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            rule_id=rule_id,
            issue_id=issue_id,
            limit=max(1, min(limit, 200)),
        )
    }


@router.post("/projects/{pid}/automations/run")
async def run_automations(
    body: AutomationManualRunInput,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    try:
        result = run_automation_rules_for_issue(
            body.issue_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            trigger=body.trigger,
            actor_email=auth.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return result


@router.post("/projects/{pid}/automations/run/backlog")
async def run_automation_backlog(
    body: AutomationBacklogRunInput,
    ctx: ProjectEditorDep,
    auth: AuthDep,
) -> dict[str, Any]:
    return run_automation_rules_for_backlog(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        trigger=body.trigger,
        status=body.status,
        queue_key=body.queue_key,
        limit=max(1, min(body.limit, 100)),
        actor_email=auth.email,
    )


@router.post("/projects/{pid}/support/automation-proof/run")
async def run_support_automation_proof(ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    try:
        return run_human_loop_automation_proof(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{pid}/automations/human-loop/setup")
async def setup_human_loop_automation(ctx: ProjectEditorDep, auth: AuthDep) -> dict[str, Any]:
    try:
        return run_human_loop_automation_setup_proof(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_email=auth.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{pid}/automations/preview")
async def preview_automations(body: AutomationPreviewInput, ctx: ProjectEditorDep) -> dict[str, Any]:
    result = preview_automation_rules_for_issue(
        body.issue_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        trigger=body.trigger,
        preview_rule=body.preview_rule.model_dump(by_alias=True) if body.preview_rule else None,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return result
