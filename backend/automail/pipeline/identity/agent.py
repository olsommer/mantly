"""Phase 1: Customer Identity Analysis agent.

Dynamically builds LangChain tools from user-defined HTTP tool configs and
runs a LangChain agent to look up customer information by sender email address.

If no tools are configured the phase returns an empty IdentityResult immediately
(no LLM call is made).
"""
import logging
from email.utils import parseaddr
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from automail.integrations.http_tool import ToolDefinition, _make_http_tool
from automail.llm.usage import llm_stage
from automail.models import IdentityResult
from automail.pipeline.identity.tools_factory import load_tool_definitions

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _retry_exception(retry_state: RetryCallState) -> BaseException | str:
    outcome = retry_state.outcome
    if outcome is None:
        return ""
    exc = outcome.exception()
    return exc if exc is not None else ""

_SYSTEM_PROMPT = (_PROMPTS_DIR / "identity_system_prompt.md").read_text(encoding="utf-8").strip()


def _normalize_sender_email(sender_email: str) -> str:
    """Extract the actual email address from a From header-like string."""
    _, parsed_email = parseaddr(sender_email)
    normalized = (parsed_email or sender_email).strip()
    return normalized.lower()


def _direct_json_lookup(defn: ToolDefinition, sender_email: str) -> IdentityResult | None:
    """Try a deterministic CRM-style lookup before trusting model summarization.

    If the configured tool returns a JSON object with a `customerFound` flag,
    convert it directly into an IdentityResult. This preserves the normal LLM
    path for arbitrary tools while making the demo CRM flow reliable.
    """
    # Check for demo CRM path (strip query string before matching)
    url_path = defn.url_template.split("?")[0].rstrip("/")
    if url_path.endswith("/demo/crm"):
        from automail.demo.crm import lookup_demo_customer

        data = lookup_demo_customer(sender_email)
        return IdentityResult(
            customer_found=bool(data.get("customerFound")),
            data=data,
            tool_calls_made=[defn.name],
        )

    url = defn.url_template.replace("{sender_email}", quote(sender_email, safe=''))
    payload: dict[str, Any] = {
        k: v.replace("{sender_email}", sender_email) if isinstance(v, str) else v
        for k, v in defn.body.items()
    }

    try:
        response = httpx.request(
            method=defn.method,
            url=url,
            headers=defn.headers,
            params=payload if defn.method == "GET" and payload else None,
            json=payload if defn.method != "GET" else None,
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    if not isinstance(data, dict) or "customerFound" not in data:
        return None

    return IdentityResult(
        customer_found=bool(data.get("customerFound")),
        data=data,
        tool_calls_made=[defn.name],
    )


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
    before_sleep=lambda rs: logger.warning(
        "Identity agent invoke failed (attempt %d), retrying: %s",
        rs.attempt_number, _retry_exception(rs),
    ),
)
def _invoke_identity_agent(agent: Any, sender_email: str) -> dict[str, Any]:
    return agent.invoke({
        "messages": [{
            "role": "user",
            "content": f"Look up the customer with email address: {sender_email}",
        }]
    })


def run_identity_agent(
    sender_email: str,
    config_path: Any = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> IdentityResult:
    """Phase 1: look up customer identity using configured HTTP tools.

    Returns an IdentityResult.  If no tools are configured, returns immediately
    with customer_found=False without making any LLM calls.
    """
    tool_definitions = load_tool_definitions(
        config_path=config_path,
        tenant_id=tenant_id,
        project_id=project_id,
    )

    if not tool_definitions:
        logger.info("No identity tools configured — skipping identity phase")
        return IdentityResult()

    normalized_sender_email = _normalize_sender_email(sender_email)
    logger.info(
        "Running identity agent for sender: %s (%d tools)",
        normalized_sender_email,
        len(tool_definitions),
    )

    if len(tool_definitions) == 1:
        direct_result = _direct_json_lookup(tool_definitions[0], normalized_sender_email)
        if direct_result:
            logger.info(
                "Using direct JSON identity lookup result for tool '%s'",
                tool_definitions[0].name,
            )
            return direct_result

    langchain_tools = [_make_http_tool(defn) for defn in tool_definitions]
    tool_names = [defn.name for defn in tool_definitions]

    from automail.core.config import read_config
    from automail.llm import create_llm, resolve_effective_config
    config = read_config(config_path=config_path)
    config = resolve_effective_config(config, tenant_id, project_id)

    extra_sections = []
    if config.identity_notes.strip():
        extra_sections.append(f"\n## Additional Instructions\n{config.identity_notes}")
    system_prompt = _SYSTEM_PROMPT + "".join(extra_sections)

    llm = create_llm(config, timeout=60, max_retries=2)
    agent = create_agent(
        model=llm,
        tools=langchain_tools,
        system_prompt=system_prompt,
        response_format=ToolStrategy(IdentityResult),
    )

    with llm_stage("identity"):
        result = _invoke_identity_agent(agent, normalized_sender_email)
    from automail.llm.usage import record_usage_from_result

    record_usage_from_result(result, getattr(llm, "_mantly_usage_context", None))
    structured: IdentityResult | None = result.get("structured_response")

    if not structured:
        logger.warning("Identity agent returned no structured response")
        structured = IdentityResult(
            tool_calls_made=tool_names,
            error="Agent returned no structured response",
        )

    # Ensure tool_calls_made is populated even if agent omitted it
    if not structured.tool_calls_made:
        structured.tool_calls_made = tool_names

    logger.info(
        "Identity result: customer_found=%s, tools=%s",
        structured.customer_found,
        structured.tool_calls_made,
    )
    return structured
