"""LLM factory helpers."""

from typing import Any

from pydantic import SecretStr

from automail.core.config import AdminConfig


def message_content_text(content: Any) -> str:
    """Return text from LangChain message content across provider shapes."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text is not None:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return "" if content is None else str(content)


def create_llm(
    config: AdminConfig,
    *,
    timeout: int = 120,
    max_retries: int = 3,
    model: str | None = None,
    temperature: float | None = None,
) -> Any:
    """Build a LangChain chat model from the current admin config."""
    extra_kwargs: dict = {}
    if temperature is not None:
        extra_kwargs["temperature"] = temperature

    if config.llm_provider == "custom" and config.llm_custom_base_url:
        from langchain_openai import ChatOpenAI

        resolved_model = model or config.llm_custom_model or "gpt-4o"

        llm = ChatOpenAI(
            model=resolved_model,
            base_url=config.llm_custom_base_url,
            api_key=SecretStr(config.llm_api_key or "sk-placeholder"),
            timeout=timeout,
            max_retries=max_retries,
            **extra_kwargs,
        )
        return attach_usage_context(llm, provider="custom", model=resolved_model, config=config)

    from langchain_google_genai import ChatGoogleGenerativeAI

    api_key = config.llm_api_key
    if not api_key:
        raise ValueError(
            "No LLM API key configured. Set the API key in tenant settings "
            "or project admin config."
        )
    resolved_model = model or config.llm_model or "gemini-2.5-flash"
    llm = ChatGoogleGenerativeAI(
        model=resolved_model,
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
        **extra_kwargs,
    )
    return attach_usage_context(llm, provider="gemini", model=resolved_model, config=config)


def attach_usage_context(llm: Any, *, provider: str, model: str, config: AdminConfig) -> Any:
    """Attach Mantly usage metadata without importing LangChain internals."""
    object.__setattr__(
        llm,
        "_mantly_usage_context",
        {
            "provider": provider,
            "model": model,
            "billing_mode": getattr(config, "llm_billing_mode", "byok"),
        },
    )
    return llm
