import asyncio
import hashlib
import hmac
import json

from starlette.testclient import TestClient

from automail.support import bridge
from automail.support.bridge import BridgeForwardSettings
from automail.support.bridge_app import create_app
from automail.support.discord_gateway import (
    DEFAULT_INTENTS,
    DiscordGatewaySettings,
    identify_payload,
    parse_discord_intents,
    run_discord_gateway_once,
)


def test_forward_bridge_event_posts_wrapped_payload(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"issueId": "issue1", "status": "created"}

    class FakeClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url: str, *, content: bytes, headers: dict[str, str]):
            captured.update({"url": url, "content": content, "headers": headers, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr(bridge.httpx, "Client", FakeClient)

    result = bridge.forward_bridge_event(
        provider="teams",
        channel_key="teams-main",
        payload={"type": "message", "text": "Help"},
        settings=BridgeForwardSettings(
            core_url="https://api.example.com/",
            project_id="project1",
            tenant_id="tenant1",
            token="forward-token",
            timeout_seconds=7,
        ),
    )

    assert result == {
        "status": "forwarded",
        "provider": "teams",
        "channelKey": "teams-main",
        "core": {"issueId": "issue1", "status": "created"},
    }
    assert captured["url"] == "https://api.example.com/api/internal/support/teams/teams-main?project_id=project1&tenant_id=tenant1"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "X-Support-Sync-Token": "forward-token",
    }
    assert json.loads(captured["content"]) == {
        "projectId": "project1",
        "tenantId": "tenant1",
        "payload": {"type": "message", "text": "Help"},
    }
    assert captured["timeout"] == 7


def test_forward_bridge_event_can_sign_forwarded_body(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(bridge.time, "time", lambda: 1_700_000_000)

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url: str, *, content: bytes, headers: dict[str, str]):
            captured.update({"content": content, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(bridge.httpx, "Client", FakeClient)

    bridge.forward_bridge_event(
        provider="discord",
        channel_key="discord-main",
        payload={"t": "MESSAGE_CREATE"},
        settings=BridgeForwardSettings(
            core_url="https://api.example.com",
            project_id="project1",
            signature_secret="signing-secret",
            signature_header="X-Bridge-Signature",
            signature_timestamp_header="X-Bridge-Timestamp",
        ),
    )

    expected = hmac.new(
        b"signing-secret",
        b"1700000000." + captured["content"],
        hashlib.sha256,
    ).hexdigest()
    assert captured["headers"]["X-Bridge-Signature"] == f"sha256={expected}"
    assert captured["headers"]["X-Bridge-Timestamp"] == "1700000000"


def test_forward_bridge_event_uses_canonical_provider_alias(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url: str, *, content: bytes, headers: dict[str, str]):
            captured.update({"url": url, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(bridge.httpx, "Client", FakeClient)

    result = bridge.forward_bridge_event(
        provider="webhook",
        channel_key="external-main",
        payload={"text": "Help"},
        settings=BridgeForwardSettings(core_url="https://api.example.com"),
    )

    assert result["provider"] == "channel-webhooks"
    assert captured["url"] == "https://api.example.com/api/internal/support/channel-webhooks/external-main"


def test_forward_bridge_validation_proxies_query_to_core(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = "challenge-123"

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url: str, *, headers: dict[str, str]):
            captured.update({"url": url, "headers": headers, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr(bridge.httpx, "Client", FakeClient)

    result = bridge.forward_bridge_validation(
        provider="facebook_messenger",
        channel_key="messenger-main",
        query_params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-token",
            "hub.challenge": "challenge-123",
            "project_id": "external-project",
        },
        settings=BridgeForwardSettings(
            core_url="https://api.example.com/",
            project_id="project1",
            tenant_id="tenant1",
            timeout_seconds=5,
        ),
    )

    assert result == {
        "status": "validated",
        "provider": "messenger",
        "channelKey": "messenger-main",
        "text": "challenge-123",
    }
    assert captured["url"] == (
        "https://api.example.com/api/internal/support/messenger/messenger-main"
        "?hub.mode=subscribe&hub.verify_token=verify-token&hub.challenge=challenge-123"
        "&project_id=project1&tenant_id=tenant1"
    )
    assert captured["headers"] == {"Accept": "text/plain, application/json"}
    assert captured["timeout"] == 5


def test_bridge_settings_uses_provider_default_token_env(monkeypatch):
    monkeypatch.delenv("SUPPORT_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("SUPPORT_BRIDGE_TOKEN_ENV", raising=False)
    monkeypatch.setenv("SUPPORT_SLACK_WEBHOOK_TOKEN", "slack-token")
    monkeypatch.setenv("SUPPORT_TWILIO_WEBHOOK_TOKEN", "twilio-token")
    monkeypatch.setenv("SUPPORT_MESSENGER_WEBHOOK_TOKEN", "messenger-token")
    monkeypatch.setenv("SUPPORT_LINE_WEBHOOK_TOKEN", "line-token")
    monkeypatch.setenv("SUPPORT_VIBER_WEBHOOK_TOKEN", "viber-token")

    assert bridge.bridge_settings_from_env("slack").token == "slack-token"
    assert bridge.bridge_settings_from_env("sms").token == "twilio-token"
    assert bridge.bridge_settings_from_env("facebook_messenger").token == "messenger-token"
    assert bridge.bridge_settings_from_env("line_messaging").token == "line-token"
    assert bridge.bridge_settings_from_env("viber_bot").token == "viber-token"


def test_bridge_app_teams_validation_echoes_token():
    client = TestClient(create_app())

    resp = client.get("/bridge/teams/teams-main?validationToken=abc123")

    assert resp.status_code == 200
    assert resp.text == "abc123"


def test_bridge_app_proxies_meta_validation(monkeypatch):
    calls: list[dict] = []

    monkeypatch.setattr(
        "automail.support.bridge_app.forward_bridge_validation",
        lambda **kwargs: calls.append(kwargs) or {"status": "validated", "text": "meta-challenge"},
    )
    client = TestClient(create_app())

    resp = client.get(
        "/bridge/whatsapp/wa-main"
        "?hub.mode=subscribe&hub.verify_token=verify-token&hub.challenge=meta-challenge"
    )

    assert resp.status_code == 200
    assert resp.text == "meta-challenge"
    assert calls == [
        {
            "provider": "whatsapp",
            "channel_key": "wa-main",
            "query_params": {
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-token",
                "hub.challenge": "meta-challenge",
            },
        }
    ]


def test_bridge_app_proxies_twitter_crc_validation(monkeypatch):
    calls: list[dict] = []

    monkeypatch.setattr(
        "automail.support.bridge_app.forward_bridge_validation",
        lambda **kwargs: calls.append(kwargs) or {"status": "validated", "json": {"response_token": "sha256=crc"}},
    )
    client = TestClient(create_app())

    resp = client.get("/bridge/twitter/twitter-main?crc_token=challenge")

    assert resp.status_code == 200
    assert resp.json() == {"response_token": "sha256=crc"}
    assert calls == [
        {
            "provider": "twitter",
            "channel_key": "twitter-main",
            "query_params": {"crc_token": "challenge"},
        }
    ]


def test_bridge_app_rejects_non_meta_validation_provider(monkeypatch):
    monkeypatch.setattr(
        "automail.support.bridge_app.forward_bridge_validation",
        lambda **_kwargs: {"status": "validated", "text": "challenge"},
    )
    client = TestClient(create_app())

    resp = client.get("/bridge/slack/slack-main?challenge=abc")

    assert resp.status_code == 404


def test_bridge_app_forwards_teams_payload(monkeypatch):
    calls: list[dict] = []

    monkeypatch.setattr(
        "automail.support.bridge_app.forward_bridge_event",
        lambda **kwargs: calls.append(kwargs) or {"status": "forwarded"},
    )
    client = TestClient(create_app())

    resp = client.post("/bridge/teams/teams-main", json={"type": "message", "text": "Help"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "forwarded"}
    assert calls == [
        {
            "provider": "teams",
            "channel_key": "teams-main",
            "payload": {"type": "message", "text": "Help"},
        }
    ]


def test_bridge_app_forwards_supported_provider_payloads(monkeypatch):
    calls: list[dict] = []

    monkeypatch.setattr(
        "automail.support.bridge_app.forward_bridge_event",
        lambda **kwargs: calls.append(kwargs) or {"status": "forwarded", "provider": kwargs["provider"]},
    )
    client = TestClient(create_app())

    for provider in ["slack", "telegram", "line", "viber", "whatsapp", "messenger", "instagram", "twitter", "sms", "channel-webhooks", "webhook"]:
        resp = client.post(f"/bridge/{provider}/{provider}-main", json={"text": "Need help"})
        assert resp.status_code == 200

    assert [call["provider"] for call in calls] == [
        "slack",
        "telegram",
        "line",
        "viber",
        "whatsapp",
        "messenger",
        "instagram",
        "twitter",
        "sms",
        "channel-webhooks",
        "channel-webhooks",
    ]
    assert calls[0]["channel_key"] == "slack-main"
    assert calls[-1]["channel_key"] == "webhook-main"


def test_bridge_app_rejects_unsupported_provider(monkeypatch):
    monkeypatch.setattr(
        "automail.support.bridge_app.forward_bridge_event",
        lambda **_kwargs: {"status": "forwarded"},
    )
    client = TestClient(create_app())

    resp = client.post("/bridge/not-a-provider/main", json={"text": "Need help"})

    assert resp.status_code == 404


def test_bridge_app_enforces_optional_inbound_token(monkeypatch):
    monkeypatch.setenv("SUPPORT_BRIDGE_INBOUND_TOKEN", "bridge-token")
    monkeypatch.setattr(
        "automail.support.bridge_app.forward_bridge_event",
        lambda **_kwargs: {"status": "forwarded"},
    )
    client = TestClient(create_app())

    unauthorized = client.post("/bridge/discord/discord-main", json={"t": "MESSAGE_CREATE"})
    authorized = client.post(
        "/bridge/discord/discord-main",
        json={"t": "MESSAGE_CREATE"},
        headers={"X-Support-Bridge-Token": "bridge-token"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_discord_gateway_intent_parsing():
    assert parse_discord_intents("") == DEFAULT_INTENTS
    assert parse_discord_intents("Guilds,GuildMessages,DirectMessages,MessageContent") == DEFAULT_INTENTS
    assert parse_discord_intents(str(DEFAULT_INTENTS)) == DEFAULT_INTENTS


def test_discord_gateway_identify_payload():
    payload = identify_payload(
        DiscordGatewaySettings(
            bot_token="bot-token",
            channel_key="discord-main",
            intents=513,
            identify_os="linux",
            library_name="mantly-test",
        )
    )

    assert payload == {
        "op": 2,
        "d": {
            "token": "bot-token",
            "intents": 513,
            "properties": {
                "os": "linux",
                "browser": "mantly-test",
                "device": "mantly-test",
            },
        },
    }


def test_discord_gateway_run_once_identifies_and_forwards_message_create():
    sent: list[dict] = []
    forwarded: list[dict] = []
    messages = [
        {"op": 10, "d": {"heartbeat_interval": 60000}},
        {
            "op": 0,
            "s": 7,
            "t": "MESSAGE_CREATE",
            "d": {
                "id": "discord-message-id",
                "channel_id": "discord-channel-id",
                "guild_id": "discord-guild-id",
                "content": "Need help",
                "author": {"id": "user1", "username": "Customer"},
            },
        },
    ]

    class FakeWebSocket:
        async def recv(self):
            return json.dumps(messages.pop(0))

        async def send(self, raw: str):
            sent.append(json.loads(raw))

    class FakeConnect:
        def __init__(self, url: str):
            self.url = url

        async def __aenter__(self):
            return FakeWebSocket()

        async def __aexit__(self, *_args):
            return None

    settings = DiscordGatewaySettings(
        bot_token="bot-token",
        channel_key="discord-main",
        gateway_url="wss://gateway.discord.test",
        intents=DEFAULT_INTENTS,
        identify_os="linux",
    )

    stats = asyncio.run(
        run_discord_gateway_once(
            settings,
            max_forwarded=1,
            forwarder=lambda **kwargs: forwarded.append(kwargs) or {"status": "forwarded"},
            connect_fn=lambda url: FakeConnect(url),
        )
    )

    assert stats.forwarded == 1
    assert stats.dispatches == 1
    assert stats.last_sequence == 7
    assert sent[0]["op"] == 2
    assert sent[0]["d"]["token"] == "bot-token"
    assert forwarded == [
        {
            "provider": "discord",
            "channel_key": "discord-main",
            "payload": {
                "op": 0,
                "s": 7,
                "t": "MESSAGE_CREATE",
                "d": {
                    "id": "discord-message-id",
                    "channel_id": "discord-channel-id",
                    "guild_id": "discord-guild-id",
                    "content": "Need help",
                    "author": {"id": "user1", "username": "Customer"},
                },
            },
        }
    ]
