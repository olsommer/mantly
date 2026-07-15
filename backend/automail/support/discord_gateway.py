"""Discord Gateway worker for the support bridge."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import platform
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from websockets.asyncio.client import connect

from automail.support.bridge import forward_bridge_event

logger = logging.getLogger(__name__)

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_GATEWAY_DEFAULT = "wss://gateway.discord.gg/?v=10&encoding=json"

DISCORD_INTENTS = {
    "GUILDS": 1 << 0,
    "GUILD_MESSAGES": 1 << 9,
    "DIRECT_MESSAGES": 1 << 12,
    "MESSAGE_CONTENT": 1 << 15,
}
DISCORD_INTENT_ALIASES = {
    "GUILDS": "GUILDS",
    "GUILD": "GUILDS",
    "GUILDMESSAGES": "GUILD_MESSAGES",
    "GUILD_MESSAGES": "GUILD_MESSAGES",
    "DIRECTMESSAGES": "DIRECT_MESSAGES",
    "DIRECT_MESSAGES": "DIRECT_MESSAGES",
    "DMS": "DIRECT_MESSAGES",
    "MESSAGECONTENT": "MESSAGE_CONTENT",
    "MESSAGE_CONTENT": "MESSAGE_CONTENT",
}
DEFAULT_INTENTS = (
    DISCORD_INTENTS["GUILDS"]
    | DISCORD_INTENTS["GUILD_MESSAGES"]
    | DISCORD_INTENTS["DIRECT_MESSAGES"]
    | DISCORD_INTENTS["MESSAGE_CONTENT"]
)


@dataclass(frozen=True)
class DiscordGatewaySettings:
    bot_token: str
    channel_key: str
    gateway_url: str = ""
    events: tuple[str, ...] = ("MESSAGE_CREATE",)
    intents: int = DEFAULT_INTENTS
    reconnect_seconds: float = 5
    identify_os: str = field(default_factory=lambda: platform.system().lower() or "linux")
    library_name: str = "mantly-support-bridge"


@dataclass
class DiscordGatewayRunStats:
    forwarded: int = 0
    ignored: int = 0
    heartbeats: int = 0
    dispatches: int = 0
    reconnect: bool = False
    last_sequence: int | None = None


class DiscordGatewayError(RuntimeError):
    pass


def _env_value(name: str) -> str:
    return os.getenv(name, "").strip()


def _split_tokens(raw: str) -> list[str]:
    tokens: list[str] = []
    current = []
    for char in raw:
        if char.isalnum() or char == "_":
            current.append(char)
            continue
        if current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def parse_discord_intents(raw: str) -> int:
    clean = raw.strip()
    if not clean:
        return DEFAULT_INTENTS
    if clean.isdigit():
        return int(clean)
    intents = 0
    for token in _split_tokens(clean):
        key = DISCORD_INTENT_ALIASES.get(token.upper())
        if key:
            intents |= DISCORD_INTENTS[key]
    if not intents:
        raise DiscordGatewayError(f"No supported Discord Gateway intents found in {raw!r}")
    return intents


def _parse_events(raw: str) -> tuple[str, ...]:
    events = tuple(token.upper() for token in _split_tokens(raw) if token)
    return events or ("MESSAGE_CREATE",)


def discord_gateway_settings_from_env() -> DiscordGatewaySettings:
    token_env = _env_value("SUPPORT_BRIDGE_DISCORD_BOT_TOKEN_ENV") or "SUPPORT_DISCORD_BOT_TOKEN"
    token = _env_value("SUPPORT_BRIDGE_DISCORD_BOT_TOKEN") or _env_value(token_env)
    if not token:
        raise DiscordGatewayError(f"Discord bot token env missing: {token_env}")
    return DiscordGatewaySettings(
        bot_token=token,
        channel_key=_env_value("SUPPORT_BRIDGE_DISCORD_CHANNEL_KEY") or "discord-main",
        gateway_url=_env_value("SUPPORT_BRIDGE_DISCORD_GATEWAY_URL"),
        events=_parse_events(_env_value("SUPPORT_BRIDGE_DISCORD_GATEWAY_EVENTS")),
        intents=parse_discord_intents(_env_value("SUPPORT_BRIDGE_DISCORD_GATEWAY_INTENTS")),
        reconnect_seconds=float(_env_value("SUPPORT_BRIDGE_RECONNECT_SECONDS") or "5"),
    )


def _gateway_ws_url(url: str) -> str:
    clean = url.strip()
    if not clean:
        return DISCORD_GATEWAY_DEFAULT
    if "?" in clean:
        return clean
    return f"{clean}?v=10&encoding=json"


def fetch_discord_gateway_url(bot_token: str) -> str:
    with httpx.Client(timeout=15) as client:
        response = client.get(
            f"{DISCORD_API_BASE}/gateway/bot",
            headers={"Authorization": f"Bot {bot_token}"},
        )
        response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise DiscordGatewayError("Discord gateway response was not an object")
    url = str(data.get("url") or "").strip()
    if not url:
        raise DiscordGatewayError("Discord gateway response did not include url")
    return _gateway_ws_url(url)


def identify_payload(settings: DiscordGatewaySettings) -> dict[str, Any]:
    return {
        "op": OP_IDENTIFY,
        "d": {
            "token": settings.bot_token,
            "intents": settings.intents,
            "properties": {
                "os": settings.identify_os,
                "browser": settings.library_name,
                "device": settings.library_name,
            },
        },
    }


def heartbeat_payload(sequence: int | None) -> dict[str, Any]:
    return {"op": OP_HEARTBEAT, "d": sequence}


async def _send_json(ws: Any, payload: dict[str, Any]) -> None:
    await ws.send(json.dumps(payload, separators=(",", ":")))


async def _heartbeat_loop(ws: Any, interval_seconds: float, state: DiscordGatewayRunStats) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await _send_json(ws, heartbeat_payload(state.last_sequence))
        state.heartbeats += 1


def _is_forwardable_dispatch(payload: dict[str, Any], settings: DiscordGatewaySettings) -> bool:
    if payload.get("op") != OP_DISPATCH:
        return False
    return str(payload.get("t") or "").upper() in settings.events


async def run_discord_gateway_once(
    settings: DiscordGatewaySettings,
    *,
    max_forwarded: int | None = None,
    forwarder: Callable[..., dict[str, Any]] = forward_bridge_event,
    connect_fn: Callable[..., Any] = connect,
) -> DiscordGatewayRunStats:
    gateway_url = _gateway_ws_url(settings.gateway_url) if settings.gateway_url else fetch_discord_gateway_url(settings.bot_token)
    stats = DiscordGatewayRunStats()
    heartbeat_task: asyncio.Task[None] | None = None
    async with connect_fn(gateway_url) as ws:
        try:
            while True:
                raw = await ws.recv()
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    stats.ignored += 1
                    continue
                sequence = payload.get("s")
                if isinstance(sequence, int):
                    stats.last_sequence = sequence
                op = payload.get("op")
                if op == OP_HELLO:
                    interval_ms = int((payload.get("d") or {}).get("heartbeat_interval") or 45000)
                    heartbeat_task = asyncio.create_task(_heartbeat_loop(ws, max(interval_ms / 1000, 1), stats))
                    await _send_json(ws, identify_payload(settings))
                    continue
                if op == OP_HEARTBEAT:
                    await _send_json(ws, heartbeat_payload(stats.last_sequence))
                    stats.heartbeats += 1
                    continue
                if op == OP_HEARTBEAT_ACK:
                    continue
                if op in {OP_RECONNECT, OP_INVALID_SESSION}:
                    stats.reconnect = True
                    return stats
                if op == OP_DISPATCH:
                    stats.dispatches += 1
                    if _is_forwardable_dispatch(payload, settings):
                        forwarder(provider="discord", channel_key=settings.channel_key, payload=payload)
                        stats.forwarded += 1
                        if max_forwarded and stats.forwarded >= max_forwarded:
                            return stats
                    else:
                        stats.ignored += 1
                    continue
                stats.ignored += 1
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
    return stats


async def run_discord_gateway_forever(settings: DiscordGatewaySettings | None = None) -> None:
    config = settings or discord_gateway_settings_from_env()
    while True:
        try:
            stats = await run_discord_gateway_once(config)
            logger.info("Discord gateway session ended: forwarded=%s ignored=%s reconnect=%s", stats.forwarded, stats.ignored, stats.reconnect)
        except Exception:
            logger.warning("Discord gateway session failed", exc_info=True)
        await asyncio.sleep(max(config.reconnect_seconds, 1))


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(run_discord_gateway_forever())


if __name__ == "__main__":
    main()
