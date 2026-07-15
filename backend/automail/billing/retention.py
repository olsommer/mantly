"""Plan-based tenant retention enforcement."""

import logging
from datetime import datetime, timedelta, timezone

from automail.billing.config import IS_SAAS
from automail.billing.usage import _is_unlimited, _pb_date_filter_value, get_tenant_limit

logger = logging.getLogger(__name__)

def enforce_retention(tenant_id: str) -> dict[str, int]:
    """Delete tenant data older than the plan retention window."""
    if not IS_SAAS:
        return {}

    days = get_tenant_limit(tenant_id, "retention_days")
    if _is_unlimited(days) or days <= 0:
        return {}

    from automail.db.pocketbase.client import _delete, _escape_pb, _list_all

    cutoff = _pb_date_filter_value(datetime.now(timezone.utc) - timedelta(days=days))
    esc_tid = _escape_pb(tenant_id)
    deleted = {"chats": 0, "eval_runs": 0, "eval_results": 0, "llm_usage_events": 0}

    for chat in _list_all("chats", f"tenant='{esc_tid}' && created<'{cutoff}'"):
        _delete(f"/api/collections/chats/records/{chat['id']}")
        deleted["chats"] += 1

    old_runs = _list_all("eval_runs", f"tenant='{esc_tid}' && created<'{cutoff}'")
    for run in old_runs:
        for result in _list_all("eval_results", f"eval_run='{_escape_pb(run['id'])}'"):
            _delete(f"/api/collections/eval_results/records/{result['id']}")
            deleted["eval_results"] += 1
        _delete(f"/api/collections/eval_runs/records/{run['id']}")
        deleted["eval_runs"] += 1

    for event in _list_all("llm_usage_events", f"tenant='{esc_tid}' && created<'{cutoff}'"):
        _delete(f"/api/collections/llm_usage_events/records/{event['id']}")
        deleted["llm_usage_events"] += 1

    return deleted

def enforce_retention_best_effort(tenant_id: str) -> dict[str, int]:
    try:
        return enforce_retention(tenant_id)
    except Exception:
        logger.warning("Failed to enforce retention for tenant %s", tenant_id, exc_info=True)
        return {}
