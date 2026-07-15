from automail.core.config import AdminConfig
from automail.llm import resolve_effective_config
from automail.llm.billing import (
    LLM_BILLING_BYOK,
    LLM_BILLING_INCLUDED,
    LLM_BILLING_MANTLY_MANAGED,
    annotate_usage_event,
    estimate_cost_usd_micros,
)


def test_tenant_settings_reports_managed_for_saas_without_byok(monkeypatch):
    from automail.db.pocketbase.tenants import get_tenant_settings

    records = [
        {"id": "tenant-a", "name": "Tenant A"},
        {"id": "tenant-a", "name": "Tenant A", "llm_provider": "gemini"},
        {"id": "tenant-a", "name": "Tenant A", "llm_provider": "gemini", "llm_api_key": "customer-key"},
    ]

    monkeypatch.setattr("automail.billing.config.IS_SAAS", True)
    monkeypatch.setattr("automail.db.pocketbase.tenants._get", lambda path: records.pop(0))

    assert get_tenant_settings("tenant-a")["llmProvider"] == "managed"
    assert get_tenant_settings("tenant-a")["llmProvider"] == "managed"
    assert get_tenant_settings("tenant-a")["llmProvider"] == "gemini"


def test_estimates_known_model_cost_in_micros():
    assert estimate_cost_usd_micros(
        model="gpt-4.1-mini-2025-04-14",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    ) == 2_000_000


def test_estimates_gemini_3_flash_preview_cost_in_micros():
    assert estimate_cost_usd_micros(
        model="gemini-3-flash-preview",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    ) == 3_500_000


def test_mantly_managed_usage_applies_markup():
    event = annotate_usage_event(
        {
            "model": "gpt-4.1-mini",
            "inputTokens": 1_000_000,
            "outputTokens": 1_000_000,
        },
        billing_mode=LLM_BILLING_MANTLY_MANAGED,
    )

    assert event["rawCostUsdMicros"] == 2_000_000
    assert event["billedCostUsdMicros"] == 2_400_000
    assert event["costMarkup"] == 1.2


def test_mantly_managed_gemini_usage_applies_markup():
    event = annotate_usage_event(
        {
            "model": "gemini-3-flash-preview",
            "inputTokens": 1_000_000,
            "outputTokens": 1_000_000,
        },
        billing_mode=LLM_BILLING_MANTLY_MANAGED,
    )

    assert event["rawCostUsdMicros"] == 3_500_000
    assert event["billedCostUsdMicros"] == 4_200_000
    assert event["costMarkup"] == 1.2


def test_byok_and_included_usage_are_not_billed():
    for mode in (LLM_BILLING_BYOK, LLM_BILLING_INCLUDED):
        event = annotate_usage_event(
            {
                "model": "gpt-4.1-mini",
                "inputTokens": 1_000_000,
                "outputTokens": 1_000_000,
            },
            billing_mode=mode,
        )
        assert event["rawCostUsdMicros"] == 2_000_000
        assert event["billedCostUsdMicros"] == 0


def test_free_saas_uses_managed_key_even_when_config_has_key(monkeypatch):
    monkeypatch.setattr("automail.billing.config.IS_SAAS", True)
    monkeypatch.setattr("automail.billing.tenant.get_tenant_plan", lambda tenant_id: "free")
    monkeypatch.setattr("automail.billing.plans.has_feature", lambda tenant_id, feature: False)
    monkeypatch.setattr("automail.db.pocketbase.client.get_tenant_account_type", lambda tenant_id: "normal")
    monkeypatch.setattr("automail.db.pocketbase.client.get_tenant_settings", lambda tenant_id: {})
    monkeypatch.setenv("MANTLY_MANAGED_LLM_API_KEY", "managed-key")
    monkeypatch.setenv("MANTLY_MANAGED_LLM_MODEL", "gemini-managed")

    config = AdminConfig(llm_api_key="customer-key", use_custom_llm=True, use_custom_org=True)

    resolved = resolve_effective_config(config, tenant_id="tenant-a")

    assert resolved.llm_api_key == "managed-key"
    assert resolved.llm_model == "gemini-managed"
    assert resolved.llm_billing_mode == LLM_BILLING_INCLUDED


def test_paid_saas_with_customer_key_is_byok(monkeypatch):
    monkeypatch.setattr("automail.billing.config.IS_SAAS", True)
    monkeypatch.setattr("automail.billing.tenant.get_tenant_plan", lambda tenant_id: "pro")
    monkeypatch.setattr("automail.db.pocketbase.client.get_tenant_account_type", lambda tenant_id: "normal")

    config = AdminConfig(llm_api_key="customer-key", use_custom_llm=True, use_custom_org=True)

    resolved = resolve_effective_config(config, tenant_id="tenant-a")

    assert resolved.llm_api_key == "customer-key"
    assert resolved.llm_billing_mode == LLM_BILLING_BYOK


def test_paid_saas_managed_provider_uses_managed_key(monkeypatch):
    monkeypatch.setattr("automail.billing.config.IS_SAAS", True)
    monkeypatch.setattr("automail.billing.tenant.get_tenant_plan", lambda tenant_id: "pro")
    monkeypatch.setattr("automail.billing.plans.has_feature", lambda tenant_id, feature: True)
    monkeypatch.setattr("automail.db.pocketbase.client.get_tenant_account_type", lambda tenant_id: "normal")
    monkeypatch.setenv("MANTLY_MANAGED_LLM_API_KEY", "managed-key")
    monkeypatch.setenv("MANTLY_MANAGED_LLM_MODEL", "gemini-managed")

    config = AdminConfig(
        llm_provider="managed",
        llm_api_key="customer-key",
        use_custom_llm=True,
        use_custom_org=True,
        use_custom_security=True,
    )

    resolved = resolve_effective_config(config, tenant_id="tenant-a")

    assert resolved.llm_api_key == "managed-key"
    assert resolved.llm_model == "gemini-managed"
    assert resolved.llm_billing_mode == LLM_BILLING_MANTLY_MANAGED


def test_security_defaults_resolve_from_tenant_settings(monkeypatch):
    monkeypatch.setattr("automail.billing.config.IS_SAAS", False)
    monkeypatch.setattr("automail.db.pocketbase.client.get_tenant_account_type", lambda tenant_id: "normal")
    monkeypatch.setattr(
        "automail.db.pocketbase.client.get_tenant_settings",
        lambda tenant_id: {
            "phishingMonitoringEnabled": True,
            "promptInjectionMonitoringEnabled": True,
        },
    )

    inherited = resolve_effective_config(
        AdminConfig(
            use_custom_org=True,
            use_custom_llm=True,
            use_custom_security=False,
            phishing_monitoring_enabled=False,
            prompt_injection_monitoring_enabled=False,
        ),
        tenant_id="tenant-a",
    )

    overridden = resolve_effective_config(
        AdminConfig(
            use_custom_org=True,
            use_custom_llm=True,
            use_custom_security=True,
            phishing_monitoring_enabled=False,
            prompt_injection_monitoring_enabled=False,
        ),
        tenant_id="tenant-a",
    )

    assert inherited.phishing_monitoring_enabled is True
    assert inherited.prompt_injection_monitoring_enabled is True
    assert overridden.phishing_monitoring_enabled is False
    assert overridden.prompt_injection_monitoring_enabled is False
