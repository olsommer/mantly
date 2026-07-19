"""Shared HTTP tool factory for building LangChain tools.

Provides:
  - ToolDefinition   – dataclass describing an HTTP tool (used by both
                       identity and intent agents)
  - _make_http_tool  – creates a LangChain tool from a definition
  - _resolve_env_vars – substitutes {ENV_VAR} placeholders in strings

URL templates and header values may reference:
  - {sender_email}  – substituted per-call with the email sender address
  - {ENV_VAR_NAME}  – resolved from environment variables at load time
"""

import json
import logging
import math
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional
from urllib.parse import parse_qs, parse_qsl, quote, urlparse

import httpx
from langchain.tools import BaseTool, tool
from pydantic import Field, create_model

from automail.demo.e2e_fixtures import (
    E2EFixtureLookupError,
    E2EFixtureNotFound,
    e2e_fixture_runtime_enabled,
    lookup_e2e_tool_fixture,
    merge_e2e_tool_input,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type mapping for dynamic Pydantic field construction
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, Any] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list[str],
}


def _cast(py_type: Any, value: Any) -> Any:
    """Convert a string default value to the target Python type."""
    if py_type is bool:
        return str(value).lower() in ("true", "1", "yes")
    if py_type == list[str]:
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        return [str(value)]
    try:
        return py_type(value)
    except (ValueError, TypeError):
        return value


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


# ---------------------------------------------------------------------------
# ToolDefinition dataclass
# ---------------------------------------------------------------------------

@dataclass
class ToolDefinition:
    name: str
    description: str
    method: str
    url_template: str                    # may contain {sender_email}
    headers: dict = field(default_factory=dict)
    body: dict = field(default_factory=dict)
    env_vars: list[str] = field(default_factory=list)
    input_schema: list[dict] = field(default_factory=list)
    expects_file: bool = False
    attach_to_response: bool = True
    file_name_path: str = ""
    file_content_type_path: str = ""
    file_content_base64_path: str = ""


_generated_attachments: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "generated_tool_attachments",
    default=None,
)
_tool_calls: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "http_tool_calls",
    default=None,
)
_tool_execution_claim: ContextVar[Callable[[], bool] | None] = ContextVar(
    "http_tool_execution_claim",
    default=None,
)


class HttpToolExecutionFenced(RuntimeError):
    """The durable processing claim expired before an HTTP tool could run."""


@dataclass
class HttpToolCollection:
    """Tool activity captured inside one isolated execution scope."""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    generated_attachments: list[dict[str, Any]] = field(default_factory=list)

# Tool responses are untrusted.  Persist only a small, fixed set of operational
# facts for later reply composition/grounding; never persist the raw response,
# request arguments, URL, headers, or credentials in the tool-call audit.
_RESPONSE_FACT_ALLOWED_KEYS = frozenset({
    "action",
    "addresschangeallowed",
    "amount",
    "available",
    "cancellationdate",
    "carrier",
    "caseid",
    "casenumber",
    "claimid",
    "claimnumber",
    "contractid",
    "contractnumber",
    "currency",
    "deliverydate",
    "duedate",
    "effectivedate",
    "eligible",
    "estimateddelivery",
    "estimateddeliverydate",
    "estimateddeliverywindow",
    "eta",
    "found",
    "greencardeligible",
    "invoiceid",
    "invoicenumber",
    "licenseplate",
    "matchedby",
    "ok",
    "orderid",
    "ordernumber",
    "policyid",
    "policynumber",
    "price",
    "processid",
    "product",
    "productcode",
    "quantity",
    "reference",
    "result",
    "shipmentfound",
    "shipmentid",
    "sku",
    "state",
    "status",
    "statuslabel",
    "success",
    "ticketid",
    "ticketnumber",
    "ticketreference",
    "trackingnumber",
    "validfrom",
    "validto",
})
_RESPONSE_FACT_ALLOWED_NESTED_KEYS = frozenset({
    ("event", "label"),
    ("event", "location"),
    ("event", "timestamp"),
    ("lastevent", "label"),
    ("lastevent", "location"),
    ("lastevent", "timestamp"),
})
_RESPONSE_FACT_PRIVATE_CONTAINERS = frozenset({
    "account",
    "contact",
    "customer",
    "debug",
    "headers",
    "input",
    "lookup",
    "payload",
    "received",
    "recipient",
    "request",
    "sender",
    "user",
})
_RESPONSE_FACT_SECRET_FRAGMENTS = (
    "apikey",
    "authorization",
    "base64",
    "cookie",
    "credential",
    "password",
    "privatekey",
    "secret",
    "token",
)
_RESPONSE_FACT_MAX_COUNT = 24
_RESPONSE_FACT_MAX_DEPTH = 5
_RESPONSE_FACT_MAX_INSPECTED_NODES = 256
_RESPONSE_FACT_MAX_PATH_CHARS = 240
_RESPONSE_FACT_MAX_STRING_CHARS = 240
_RESPONSE_FACT_MAX_SERIALIZED_BYTES = 4_096


def begin_generated_attachment_collection() -> Token:
    """Start collecting files generated by HTTP tools for the current run."""
    return _generated_attachments.set([])


def collect_generated_attachments(token: Token | None = None) -> list[dict[str, Any]]:
    """Return collected generated attachments and optionally restore context."""
    collected = list(_generated_attachments.get() or [])
    if token is not None:
        _generated_attachments.reset(token)
    return collected


def current_generated_attachments() -> list[dict[str, Any]]:
    """Return generated attachments collected so far without resetting context."""
    return list(_generated_attachments.get() or [])


def begin_tool_call_collection() -> Token:
    """Start collecting HTTP tool calls for the current run."""
    return _tool_calls.set([])


def collect_tool_calls(token: Token | None = None) -> list[dict[str, Any]]:
    """Return collected HTTP tool calls and optionally restore context."""
    collected = list(_tool_calls.get() or [])
    if token is not None:
        _tool_calls.reset(token)
    return collected


def current_tool_calls() -> list[dict[str, Any]]:
    """Return HTTP tool calls collected so far without resetting context."""
    return [dict(call) for call in (_tool_calls.get() or [])]


@contextmanager
def fence_http_tool_execution(claim_is_active: Callable[[], bool]) -> Iterator[None]:
    """Require a durable active claim immediately before every HTTP tool call."""
    token = _tool_execution_claim.set(claim_is_active)
    try:
        yield
    finally:
        _tool_execution_claim.reset(token)


def _require_http_tool_execution_claim() -> None:
    claim_is_active = _tool_execution_claim.get()
    if claim_is_active is not None and not claim_is_active():
        raise HttpToolExecutionFenced("HTTP tool execution claim expired")


@contextmanager
def isolated_http_tool_collection() -> Iterator[HttpToolCollection]:
    """Capture tool activity without reading from or mutating a parent scope."""
    collection = HttpToolCollection()
    generated_token = _generated_attachments.set(collection.generated_attachments)
    tool_token = _tool_calls.set(collection.tool_calls)
    try:
        yield collection
    finally:
        _tool_calls.reset(tool_token)
        _generated_attachments.reset(generated_token)


def merge_http_tool_collection(
    collection: HttpToolCollection,
    *,
    include_generated_attachments: bool = True,
) -> None:
    """Append allowed isolated activity to the active parent in caller order."""
    tool_calls = _tool_calls.get()
    if tool_calls is not None:
        tool_calls.extend(dict(call) for call in collection.tool_calls)
    generated_attachments = _generated_attachments.get()
    if generated_attachments is not None and include_generated_attachments:
        generated_attachments.extend(dict(item) for item in collection.generated_attachments)


def _normalized_fact_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _safe_fact_path(path: tuple[str, ...]) -> bool:
    for segment in path:
        if segment.isdigit():
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", segment):
            return False
        normalized = _normalized_fact_key(segment)
        if normalized in _RESPONSE_FACT_PRIVATE_CONTAINERS:
            return False
        if any(fragment in normalized for fragment in _RESPONSE_FACT_SECRET_FRAGMENTS):
            return False
    return True


def _allowed_fact_path(path: tuple[str, ...]) -> bool:
    normalized = [
        _normalized_fact_key(segment)
        for segment in path
        if not segment.isdigit()
    ]
    if not normalized:
        return False
    if normalized[-1] in _RESPONSE_FACT_ALLOWED_KEYS:
        return True
    return len(normalized) >= 2 and tuple(normalized[-2:]) in _RESPONSE_FACT_ALLOWED_NESTED_KEYS


def _response_facts(response_text: str) -> tuple[list[dict[str, Any]], bool]:
    """Extract bounded, allowlisted scalar facts from a successful JSON response."""
    try:
        data = json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        return [], False
    if not isinstance(data, (dict, list)):
        return [], False

    facts: list[dict[str, Any]] = []
    inspected_nodes = 0
    truncated = False

    def _visit(value: Any, path: tuple[str, ...], depth: int) -> None:
        nonlocal inspected_nodes, truncated
        inspected_nodes += 1
        if inspected_nodes > _RESPONSE_FACT_MAX_INSPECTED_NODES:
            truncated = True
            return
        if depth > _RESPONSE_FACT_MAX_DEPTH:
            truncated = True
            return
        if len(facts) >= _RESPONSE_FACT_MAX_COUNT:
            truncated = True
            return

        if isinstance(value, dict):
            for raw_key, child in value.items():
                if (
                    inspected_nodes >= _RESPONSE_FACT_MAX_INSPECTED_NODES
                    or len(facts) >= _RESPONSE_FACT_MAX_COUNT
                ):
                    truncated = True
                    break
                if not isinstance(raw_key, str):
                    continue
                child_path = (*path, raw_key)
                if _safe_fact_path(child_path):
                    _visit(child, child_path, depth + 1)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                if (
                    inspected_nodes >= _RESPONSE_FACT_MAX_INSPECTED_NODES
                    or len(facts) >= _RESPONSE_FACT_MAX_COUNT
                ):
                    truncated = True
                    break
                _visit(child, (*path, str(index)), depth + 1)
            return
        if not path or not _allowed_fact_path(path) or value is None:
            return
        if isinstance(value, bool):
            safe_value: str | bool | int | float = value
        elif isinstance(value, int):
            safe_value = value
        elif isinstance(value, float):
            if not math.isfinite(value):
                return
            safe_value = value
        elif isinstance(value, str):
            if len(value) > _RESPONSE_FACT_MAX_STRING_CHARS:
                truncated = True
                return
            safe_value = value
        else:
            return

        rendered_path = ".".join(path)
        if len(rendered_path) > _RESPONSE_FACT_MAX_PATH_CHARS:
            truncated = True
            return
        candidate = {"path": rendered_path, "value": safe_value}
        candidate_facts = [*facts, candidate]
        serialized_size = len(
            json.dumps(candidate_facts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if serialized_size > _RESPONSE_FACT_MAX_SERIALIZED_BYTES:
            truncated = True
            return
        facts.append(candidate)

    _visit(data, (), 0)
    return facts, truncated


def _record_tool_call(
    defn: ToolDefinition,
    *,
    status: str,
    response_text: str | None = None,
) -> None:
    collector = _tool_calls.get()
    if collector is not None:
        audit: dict[str, Any] = {
            "name": defn.name,
            "method": defn.method,
            "status": status,
        }
        if status == "success" and response_text is not None:
            response_facts, truncated = _response_facts(response_text)
            if response_facts:
                audit["responseFacts"] = response_facts
            if truncated:
                audit["responseFactsTruncated"] = True
        collector.append(audit)


# ---------------------------------------------------------------------------
# Env-var resolution
# ---------------------------------------------------------------------------

def _resolve_env_vars(value: str, secrets: dict[str, str] | None = None) -> str:
    """Replace {PLACEHOLDER} tokens with values from a *secrets* dict.

    Placeholders named ``sender_email`` are left untouched (substituted
    per-call at runtime).  All other placeholders are looked up in the
    provided *secrets* dict.  If the key is not found, the placeholder is
    left as-is and a warning is logged.

    If *secrets* is ``None`` (backward-compat / tests) falls back to
    ``os.getenv`` so existing on-prem setups that set env vars directly
    continue to work during migration.
    """
    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key == "sender_email":
            return match.group(0)  # leave {sender_email} for per-call substitution
        if secrets is not None:
            val = secrets.get(key)
        else:
            val = os.getenv(key)
        if val is None:
            logger.warning("Tool definition references secret '%s' which is not set", key)
            return match.group(0)
        return val

    return re.sub(r'\{([^}]+)\}', _replace, value)


# ---------------------------------------------------------------------------
# HTTP tool factory
# ---------------------------------------------------------------------------

def _maybe_call_hosted_demo_tool(url: str, payload: dict[str, Any]) -> str | None:
    """Resolve hosted demo tools in-process for stable demos."""
    parsed = urlparse(url)
    e2e_match = re.fullmatch(
        r"/demo/e2e/tool/(?P<persona_id>[a-z][a-z0-9-]+)/"
        r"(?P<tool_name>[a-z][a-z0-9_]*)",
        parsed.path,
    )
    if e2e_match:
        if not e2e_fixture_runtime_enabled():
            raise E2EFixtureLookupError("E2E fixture runtime is disabled")
        supplied_input = merge_e2e_tool_input(
            parse_qsl(parsed.query, keep_blank_values=True),
            payload,
        )
        result = lookup_e2e_tool_fixture(
            e2e_match.group("persona_id"),
            e2e_match.group("tool_name"),
            supplied_input,
        )
        logger.info("Using in-process E2E fixture tool for %s", parsed.path)
        return json.dumps(result, ensure_ascii=False)

    demo_paths = {
        "/demo/insurance/motor-policy",
        "/demo/insurance/green-card",
        "/demo/logistics/shipment-status",
    }
    if parsed.path not in demo_paths:
        return None

    from automail.demo.actions import (
        DemoGreenCardRequest,
        mock_demo_green_card_request,
        mock_demo_motor_policy,
    )
    from automail.demo.shipments import lookup_demo_shipment_status

    query = {
        key: values[-1]
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        if values
    }
    merged = {**query, **payload}

    logger.info("Using in-process hosted demo tool for %s", parsed.path)
    if parsed.path == "/demo/insurance/motor-policy":
        result = mock_demo_motor_policy(
            sender_email=merged.get("sender_email"),
            policy_number=merged.get("policy_number") or merged.get("policyNumber"),
        )
    elif parsed.path == "/demo/insurance/green-card":
        result = mock_demo_green_card_request(DemoGreenCardRequest(**merged))
    else:
        result = lookup_demo_shipment_status(
            sender_email=str(merged.get("sender_email") or ""),
            order_number=merged.get("order_number") or merged.get("orderNumber"),
            tracking_number=merged.get("tracking_number") or merged.get("trackingNumber"),
        )

    return json.dumps(result, ensure_ascii=False)


def _json_path(data: Any, path: str) -> Any:
    """Resolve a simple dot-separated JSON path."""
    current = data
    for part in [p for p in path.split(".") if p]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return None
    return current


def _omit_json_path(data: Any, path: str) -> Any:
    """Return a copy with a simple dot-separated path redacted."""
    if not path:
        return data
    try:
        cloned = json.loads(json.dumps(data))
    except Exception:
        return data
    parts = [p for p in path.split(".") if p]
    current = cloned
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return cloned
    if parts and isinstance(current, dict) and parts[-1] in current:
        current[parts[-1]] = "[base64 omitted]"
    return cloned


def _capture_generated_file(defn: ToolDefinition, response_text: str) -> str:
    """Extract configured generated-file data from a JSON tool response."""
    if not defn.expects_file:
        return response_text[:4000]

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        logger.warning("Tool %s expected a file but returned non-JSON data", defn.name)
        return response_text[:4000]

    filename = str(_json_path(data, defn.file_name_path) or "").strip()
    content_base64 = str(_json_path(data, defn.file_content_base64_path) or "").strip()
    content_type = str(_json_path(data, defn.file_content_type_path) or "application/octet-stream").strip()
    if not filename or not content_base64:
        logger.warning(
            "Tool %s expected file paths but filename/content were missing",
            defn.name,
        )
        return response_text[:4000]

    collector = _generated_attachments.get()
    if collector is not None:
        size = None
        try:
            import base64
            size = len(base64.b64decode(content_base64, validate=True))
        except Exception:
            logger.warning("Generated attachment from tool %s has invalid base64", defn.name)
        collector.append({
            "filename": filename,
            "content_base64": content_base64,
            "content_type": content_type or "application/octet-stream",
            "size": size,
            "source_tool": defn.name,
            "attach_to_response": defn.attach_to_response,
        })

    sanitized = _omit_json_path(data, defn.file_content_base64_path)
    return json.dumps(sanitized, ensure_ascii=False)[:4000]


def _make_http_tool(
    defn: ToolDefinition,
    sender_email: str | None = None,
) -> BaseTool:
    """Create a LangChain tool from a ToolDefinition.

    Args:
        defn: The tool definition describing the HTTP endpoint.
        sender_email: If provided, the sender email is pre-bound into the
            closure for ``{sender_email}`` URL/body substitution and is NOT
            added as an LLM-fillable field.  If ``None`` (default), a
            ``sender_email`` field is added to the tool schema so the LLM
            must provide it (identity agent behaviour).
    """
    # Build Pydantic field specs
    pydantic_fields: dict[str, Any] = {}

    if sender_email is None:
        # Identity agent mode: LLM fills sender_email
        pydantic_fields["sender_email"] = (
            str, Field(description="Email address of the sender"),
        )

    for param in defn.input_schema:
        key = param.get("key", "").strip()
        if not key:
            continue
        py_type = _TYPE_MAP.get(param.get("type", "string"), str)
        desc = param.get("description", "")
        default_raw = param.get("default")
        if param.get("required", True):
            pydantic_fields[key] = (py_type, Field(description=desc))
        else:
            default = _cast(py_type, default_raw) if default_raw is not None else None
            pydantic_fields[key] = (
                Optional[py_type], Field(default=default, description=desc),
            )

    ArgsModel = create_model(  # noqa: N806
        f"{defn.name.replace('-', '_')}_args", **pydantic_fields,
    )

    # Pre-bound sender email (for intent tools) or None (filled by LLM)
    _bound_sender = sender_email or ""

    def _http_call(**kwargs: Any) -> str:
        # Fence before demo adapters and real network calls. A stale worker may
        # still finish LLM reasoning, but it cannot start another tool request.
        _require_http_tool_execution_claim()
        # Resolve sender_email: LLM-provided (identity) or pre-bound (intent)
        email_addr: str = kwargs.pop("sender_email", _bound_sender)
        url = defn.url_template.replace(
            "{sender_email}", quote(email_addr, safe=""),
        )

        # Substitute any {key} path parameters in the URL from kwargs.
        # Keys consumed as path params are removed from kwargs so they
        # are NOT also sent as query/body parameters.
        path_keys = [m.group(1) for m in re.finditer(r'\{([^}]+)\}', url)]
        for pk in path_keys:
            if pk in kwargs and kwargs[pk] is not None:
                url = url.replace(f"{{{pk}}}", quote(str(kwargs[pk]), safe=""))
                kwargs.pop(pk)

        # Start with static body (env vars already resolved);
        # substitute {sender_email} in values
        payload: dict[str, Any] = {
            k: v.replace("{sender_email}", email_addr) if isinstance(v, str) else v
            for k, v in defn.body.items()
        }
        # Schema-filled kwargs override static body on key conflict;
        # skip None optionals
        payload.update({k: v for k, v in kwargs.items() if v is not None})

        try:
            demo_result = _maybe_call_hosted_demo_tool(url, payload)
            if demo_result is not None:
                _record_tool_call(defn, status="success", response_text=demo_result)
                return _capture_generated_file(defn, demo_result)

            response = httpx.request(
                method=defn.method,
                url=url,
                headers=defn.headers,
                params=payload if defn.method == "GET" and payload else None,
                json=payload if defn.method != "GET" else None,
                timeout=15.0,
            )
            response.raise_for_status()
            _record_tool_call(defn, status="success", response_text=response.text)
            return _capture_generated_file(defn, response.text)
        except E2EFixtureLookupError as exc:
            status = "fixture_not_found" if isinstance(exc, E2EFixtureNotFound) else "fixture_error"
            _record_tool_call(defn, status=status)
            return f"E2E fixture lookup failed: {exc}"
        except httpx.HTTPStatusError as exc:
            _record_tool_call(defn, status=f"http_{exc.response.status_code}")
            return f"HTTP {exc.response.status_code}: {exc.response.text[:500]}"
        except Exception as exc:
            _record_tool_call(defn, status="failed")
            return f"Request failed: {exc}"

    return tool(
        defn.name.replace("-", "_"),
        description=defn.description,
        args_schema=ArgsModel,
    )(
        _http_call
    )


# ---------------------------------------------------------------------------
# Helpers for converting raw dicts to ToolDefinition
# ---------------------------------------------------------------------------

_REQUIRED_TOOL_FIELDS = {"name", "description", "method", "urlTemplate"}
_INTENT_TOOL_METHODS = {"GET", "POST"}


def raw_tool_to_definition(raw: dict[str, Any], secrets: dict[str, str] | None = None) -> ToolDefinition | None:
    """Convert a raw YAML/JSON tool dict to a ToolDefinition.

    Returns None if required fields are missing.  *secrets* is passed
    through to ``_resolve_env_vars`` for placeholder resolution.
    """
    missing = _REQUIRED_TOOL_FIELDS - raw.keys()
    if missing:
        logger.warning("Tool config missing required fields: %s — skipping", sorted(missing))
        return None

    method = str(raw["method"]).upper()
    if method not in _INTENT_TOOL_METHODS:
        logger.warning("Intent tool %s uses unsupported method %s — skipping", raw.get("name"), method)
        return None

    headers_value = raw.get("headers")
    body_value = raw.get("body")
    env_vars_value = raw.get("envVars")
    input_schema_value = raw.get("inputSchema")
    file_value = raw.get("file")

    raw_headers: dict[str, Any] = headers_value if isinstance(headers_value, dict) else {}
    raw_body: dict[str, Any] = body_value if isinstance(body_value, dict) else {}
    raw_env_vars = [str(item) for item in env_vars_value] if isinstance(env_vars_value, list) else []
    raw_input_schema = [item for item in input_schema_value if isinstance(item, dict)] if isinstance(input_schema_value, list) else []
    raw_file: dict[str, Any] = file_value if isinstance(file_value, dict) else {}

    resolved_headers = {
        k: _resolve_env_vars(v, secrets) if isinstance(v, str) else v
        for k, v in raw_headers.items()
    }
    resolved_body = {
        k: _resolve_env_vars(v, secrets) if isinstance(v, str) else v
        for k, v in raw_body.items()
    }
    resolved_url = _resolve_env_vars(str(raw["urlTemplate"]), secrets)

    return ToolDefinition(
        name=str(raw["name"]),
        description=str(raw["description"]),
        method=method,
        url_template=resolved_url,
        headers=resolved_headers,
        body=resolved_body,
        env_vars=raw_env_vars,
        input_schema=raw_input_schema,
        expects_file=_as_bool(raw_file.get("expectsFile", raw_file.get("expects_file")), default=False),
        attach_to_response=_as_bool(raw_file.get("attachToResponse", raw_file.get("attach_to_response")), default=True),
        file_name_path=str(raw_file.get("filenamePath") or raw_file.get("filename_path") or ""),
        file_content_type_path=str(raw_file.get("contentTypePath") or raw_file.get("content_type_path") or ""),
        file_content_base64_path=str(raw_file.get("contentBase64Path") or raw_file.get("content_base64_path") or ""),
    )
