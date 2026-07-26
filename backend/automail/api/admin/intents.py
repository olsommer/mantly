"""Admin intent, attachment, feedback, and learning endpoints."""

import logging
import mimetypes

import yaml
from fastapi import APIRouter, HTTPException, UploadFile

from automail.api.admin.deps import ProjectEditorDep, ProjectViewerDep, _require_ctx_capability
from automail.db.pocketbase.client import (
    _delete,
    _first,
    _list_all,
    _patch,
    _patch_multipart,
    _post_multipart,
)
from automail.pipeline.drafts import ensure_draft_exists, get_draft_source
from automail.pipeline.store import (
    compose_intent_content,
    delete_project_intent,
    get_project_intent,
    list_project_intents,
    parse_intent_content,
    upsert_project_intent,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────────────
# Intents (project-scoped)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/intents")
async def list_intents(ctx: ProjectViewerDep) -> list[dict]:
    """List all draft intents."""
    draft = get_draft_source(ctx.project_id, tenant_id=ctx.tenant_id)
    ensure_draft_exists(ctx.project_id, tenant_id=ctx.tenant_id)
    return [
        {
            "name": rec.get("name", ""),
            "description": rec.get("description", ""),
            "actions": rec.get("actions") or [],
            "response": rec.get("response") or {},
            "active": rec.get("active", True),
            "require_review": rec.get("require_review", False),
        }
        for rec in list_project_intents(draft)
        if rec.get("name")
    ]


@router.get("/projects/{pid}/intents/{name}")
async def get_intent(name: str, ctx: ProjectViewerDep) -> dict:
    """Return INTENT.md-compatible content for a named draft intent."""
    draft = get_draft_source(ctx.project_id, tenant_id=ctx.tenant_id)
    ensure_draft_exists(ctx.project_id, tenant_id=ctx.tenant_id)
    rec = get_project_intent(draft, name)
    if rec:
        return {"name": rec.get("name", name), "content": compose_intent_content(rec)}
    raise HTTPException(status_code=404, detail=f"Intent '{name}' not found")


@router.put("/projects/{pid}/intents/{name}")
async def upsert_intent(name: str, body: dict, ctx: ProjectEditorDep) -> dict:
    """Create or replace an INTENT.md file (writes to draft).

    Body: { "content": "<full INTENT.md text>" }
    """
    _require_ctx_capability(ctx, "canEditIntents")
    content = body.get("content", "")
    try:
        fm, _ = parse_intent_content(content)
    except yaml.YAMLError as exc:
        detail = getattr(exc, "problem", None) or str(exc)
        raise HTTPException(status_code=400, detail=f"Invalid intent YAML: {detail}")
    if not isinstance(fm, dict) or not fm.get("name"):
        raise HTTPException(
            status_code=400,
            detail="INTENT.md must contain a valid YAML frontmatter block with a 'name' field",
        )

    draft = get_draft_source(ctx.project_id, tenant_id=ctx.tenant_id)
    ensure_draft_exists(ctx.project_id, tenant_id=ctx.tenant_id)
    try:
        upsert_project_intent(draft, name, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("Upserted intent (draft): %s [project=%s]", name, ctx.project_id)
    return {"status": "ok", "name": name}


@router.delete("/projects/{pid}/intents/{name}")
async def delete_intent(name: str, ctx: ProjectEditorDep) -> dict:
    """Delete a draft intent and its response attachment files."""
    _require_ctx_capability(ctx, "canEditIntents")
    draft = get_draft_source(ctx.project_id, tenant_id=ctx.tenant_id)
    ensure_draft_exists(ctx.project_id, tenant_id=ctx.tenant_id)
    if delete_project_intent(draft, name):
        for rec in _list_all("intent_attachments", _intent_attachment_filter(ctx.project_id, name)):
            _delete(f"/api/collections/intent_attachments/records/{rec['id']}")
        logger.info("Deleted intent (draft): %s [project=%s]", name, ctx.project_id)
        return {"status": "deleted", "name": name}
    raise HTTPException(status_code=404, detail=f"Intent '{name}' not found")


@router.patch("/projects/{pid}/intents/{name}")
async def rename_intent(name: str, body: dict, ctx: ProjectEditorDep) -> dict:
    """Rename an intent: change its slug (directory name) and frontmatter name.

    Body: { "newName": "<new-slug>" }
    """
    import re
    _require_ctx_capability(ctx, "canEditIntents")

    raw = (body.get("newName") or "").strip().lower()
    new_slug = re.sub(r"\s+", "-", raw)
    if not new_slug:
        raise HTTPException(400, "newName is required")
    if new_slug == "_else":
        raise HTTPException(400, "Cannot rename to the reserved '_else' slug")

    old_slug = name.strip().lower()
    if new_slug == old_slug:
        return {"status": "ok", "oldName": old_slug, "newName": new_slug}

    draft = get_draft_source(ctx.project_id, tenant_id=ctx.tenant_id)
    ensure_draft_exists(ctx.project_id, tenant_id=ctx.tenant_id)
    if get_project_intent(draft, new_slug):
        raise HTTPException(409, f"Intent '{new_slug}' already exists")
    rec = get_project_intent(draft, old_slug)
    if rec is None:
        raise HTTPException(404, f"Intent '{name}' not found")
    content = compose_intent_content({**rec, "name": new_slug})
    try:
        upsert_project_intent(draft, old_slug, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for rec in _list_all("intent_attachments", _intent_attachment_filter(ctx.project_id, old_slug)):
        _patch(f"/api/collections/intent_attachments/records/{rec['id']}", {"intent": new_slug})
    logger.info(
        "Renamed intent (draft): %s -> %s [project=%s]",
        old_slug, new_slug, ctx.project_id,
    )
    return {"status": "ok", "oldName": old_slug, "newName": new_slug}


# ──────────────────────────────────────────────────────────────────────────────
# Intent Files (response attachments) — project-scoped
# ──────────────────────────────────────────────────────────────────────────────

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _safe_filename(filename: str) -> str:
    """Validate and sanitise a filename.  Raises HTTPException on bad input."""
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")
    return filename.strip()


def _escape(value: str) -> str:
    return value.replace("'", "\\'")


def _intent_attachment_filter(project_id: str, intent: str, filename: str | None = None) -> str:
    filters = [
        f"project='{_escape(project_id)}'",
        f"intent='{_escape(intent)}'",
    ]
    if filename is not None:
        filters.append(f"filename='{_escape(filename)}'")
    return " && ".join(filters)


def _intent_file_info(rec: dict) -> dict:
    stored_file = rec.get("file")
    stored_name = stored_file[0] if isinstance(stored_file, list) and stored_file else stored_file
    return {
        "filename": rec.get("filename", ""),
        "size": int(rec.get("size") or 0),
        "contentType": rec.get("content_type") or mimetypes.guess_type(rec.get("filename", ""))[0] or "application/octet-stream",
        "id": rec.get("id"),
        "storedFilename": stored_name,
    }


@router.get("/projects/{pid}/intents/{name}/files")
async def list_intent_files(name: str, ctx: ProjectViewerDep) -> list[dict]:
    """List response attachment files for an intent."""
    records = _list_all("intent_attachments", _intent_attachment_filter(ctx.project_id, name), sort="filename")
    return [_intent_file_info(rec) for rec in records]


@router.post("/projects/{pid}/intents/{name}/files")
async def upload_intent_file(name: str, file: UploadFile, ctx: ProjectEditorDep) -> dict:
    """Upload a response attachment into PocketBase."""
    _require_ctx_capability(ctx, "canEditIntents")
    filename = _safe_filename(file.filename or "unnamed")

    # Read with size limit
    data = await file.read(_MAX_FILE_SIZE + 1)
    if len(data) > _MAX_FILE_SIZE:
        raise HTTPException(413, f"File exceeds {_MAX_FILE_SIZE // (1024 * 1024)} MB limit")

    content_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    payload = {
        "project": ctx.project_id,
        "intent": name,
        "filename": filename,
        "content_type": content_type,
        "size": str(len(data)),
    }
    if ctx.tenant_id:
        payload["tenant"] = ctx.tenant_id
    files = {"file": (filename, data, content_type)}
    existing = _first("intent_attachments", _intent_attachment_filter(ctx.project_id, name, filename))
    if existing:
        _patch_multipart(f"/api/collections/intent_attachments/records/{existing['id']}", payload, files)
    else:
        _post_multipart("/api/collections/intent_attachments/records", payload, files)
    logger.info("Uploaded file '%s' for intent '%s' (%d bytes) [project=%s]", filename, name, len(data), ctx.project_id)
    return {"status": "ok", "filename": filename, "size": len(data)}


@router.delete("/projects/{pid}/intents/{name}/files/{filename:path}")
async def delete_intent_file(name: str, filename: str, ctx: ProjectEditorDep) -> dict:
    """Delete a single response attachment."""
    _require_ctx_capability(ctx, "canEditIntents")
    filename = _safe_filename(filename)
    existing = _first("intent_attachments", _intent_attachment_filter(ctx.project_id, name, filename))
    if existing:
        _delete(f"/api/collections/intent_attachments/records/{existing['id']}")
    else:
        raise HTTPException(404, f"File '{filename}' not found")
    logger.info("Deleted file '%s' from intent '%s' [project=%s]", filename, name, ctx.project_id)
    return {"status": "deleted", "filename": filename}


# ──────────────────────────────────────────────────────────────────────────────
# Intent learnings & feedback (project-scoped)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/intents/{name}/learnings")
async def list_intent_learnings(name: str, ctx: ProjectViewerDep) -> list[dict]:
    """List AI-generated learnings for an intent."""
    from automail.billing.plans import require_feature
    from automail.db.pocketbase.client import get_intent_learnings_records
    require_feature(ctx.tenant_id, "feedback_learnings")
    return get_intent_learnings_records(
        name,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
    )


@router.put("/projects/{pid}/intents/{name}/learnings/{lid}")
async def update_learning(name: str, lid: str, body: dict, ctx: ProjectEditorDep) -> dict:
    """Reject legacy direct mutation; active rules require evaluated publish."""
    _require_ctx_capability(ctx, "canEditIntents")
    from automail.billing.plans import require_feature
    require_feature(ctx.tenant_id, "feedback_learnings")
    raise HTTPException(
        status_code=409,
        detail="Direct learning edits are disabled; create and evaluate an update proposal",
    )


@router.delete("/projects/{pid}/intents/{name}/learnings/{lid}")
async def delete_learning(name: str, lid: str, ctx: ProjectEditorDep) -> dict:
    """Reject legacy direct mutation; active rules require evaluated publish."""
    _require_ctx_capability(ctx, "canEditIntents")
    from automail.billing.plans import require_feature
    require_feature(ctx.tenant_id, "feedback_learnings")
    raise HTTPException(
        status_code=409,
        detail="Direct learning deletes are disabled; create and evaluate a delete proposal",
    )


@router.get("/projects/{pid}/intents/{name}/feedback")
async def list_intent_feedback(name: str, ctx: ProjectViewerDep) -> list[dict]:
    """List recent feedback for an intent (for admin display)."""
    from automail.billing.plans import require_feature
    from automail.db.pocketbase.client import get_intent_feedback
    require_feature(ctx.tenant_id, "feedback_learnings")
    return get_intent_feedback(name, tenant_id=ctx.tenant_id, project_id=ctx.project_id)


@router.delete("/projects/{pid}/intents/{name}/feedback/{fid}")
async def delete_feedback(name: str, fid: str, ctx: ProjectEditorDep) -> dict:
    """Delete inert feedback only; preserve active and in-review evidence."""
    _require_ctx_capability(ctx, "canEditIntents")
    from automail.billing.plans import require_feature
    from automail.db.pocketbase.client import (
        delete_feedback as delete_feedback_record,
    )
    from automail.db.pocketbase.client import get_feedback_record, get_intent_learnings_records
    from automail.db.pocketbase.learning_proposals import list_learning_proposals

    require_feature(ctx.tenant_id, "feedback_learnings")

    scope = {
        "intent_name": name,
        "tenant_id": ctx.tenant_id,
        "project_id": ctx.project_id,
    }
    feedback = get_feedback_record(fid, **scope)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    linked_active = [
        learning
        for learning in get_intent_learnings_records(
            name,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        )
        if str(learning.get("source_feedback_id") or "") == fid
    ]
    linked_proposals = [
        proposal
        for proposal in list_learning_proposals(
            intent_name=name,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        )
        if str(proposal.get("source_feedback_id") or "") == fid
        and str(proposal.get("status") or "") not in {"published", "rejected"}
    ]
    if linked_active or linked_proposals:
        raise HTTPException(
            status_code=409,
            detail="Feedback is evidence for an active or nonterminal learning proposal",
        )
    deleted = delete_feedback_record(
        fid,
        **scope,
    )
    if not deleted:
        raise HTTPException(status_code=503, detail="Feedback deletion failed")
    return {
        "status": "deleted",
        "id": fid,
        "learningCount": 0,
        "removedLearningCount": 0,
    }
