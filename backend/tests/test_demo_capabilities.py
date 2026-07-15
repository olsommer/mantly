def test_demo_accounts_can_publish(monkeypatch):
    from automail.core import capabilities
    from automail.db.pocketbase import client as pb_client

    monkeypatch.setattr(capabilities, "is_saas_mode", lambda: True)
    monkeypatch.setattr(pb_client, "get_tenant_account_type", lambda _tenant_id: "demo")

    caps = capabilities.get_account_capabilities("tenant-demo")

    assert caps["canPublish"] is True
