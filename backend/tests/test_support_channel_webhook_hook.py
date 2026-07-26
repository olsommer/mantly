from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "pocketbase/pb_hooks/support_channel_webhook_claims.pb.js"
HELPER = ROOT / "pocketbase/pb_hooks/support_channel_webhook_claims_helpers.js"


def test_channel_webhook_hook_requires_callback_helpers() -> None:
    source = HOOK.read_text()
    helper_source = HELPER.read_text()

    require_line = (
        "const channelWebhooks = require("
        "`${__hooks}/support_channel_webhook_claims_helpers.js`);"
    )
    assert source.count(require_line) == 2
    assert "function text(" not in source
    assert "module.exports" in helper_source
    for export in (
        "CHANNEL_EVENT_COLLECTION",
        "RETRY_POLICY_VERSION",
        "text",
        "jsonObject",
        "conflict",
        "inScope",
        "publicRecord",
    ):
        assert export in helper_source


def test_channel_webhook_hook_registers_and_loads_helpers_inside_callbacks() -> None:
    script = r"""
const path = require("path");
global.__hooks = path.resolve(process.cwd(), "pocketbase/pb_hooks");
global.BadRequestError = class BadRequestError extends Error {};
global.ApiError = class ApiError extends Error {};
global.toString = (value) => String(value);
global.$apis = { requireSuperuserAuth: () => ({}) };
const routes = {};
global.routerAdd = (_method, route, callback) => { routes[route] = callback; };

require("./pocketbase/pb_hooks/support_channel_webhook_claims.pb.js");

const expected = [
    "/api/mantly/support-channel-webhooks/{id}/claim",
    "/api/mantly/support-channel-webhooks/{id}/complete",
];
for (const route of expected) {
    if (typeof routes[route] !== "function") {
        throw new Error(`missing route ${route}`);
    }
    let error = null;
    try {
        routes[route]({
            request: { pathValue: () => "event1" },
            requestInfo: () => ({ body: {} }),
        });
    } catch (caught) {
        error = caught;
    }
    if (!(error instanceof global.BadRequestError)) {
        throw error || new Error(`callback ${route} did not execute validation`);
    }
}
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
