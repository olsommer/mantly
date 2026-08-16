#!/usr/bin/env python3
"""Small HTTP fixture for exercising restore verification without customer data."""

from __future__ import annotations

import json
import os
import pathlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

MODE = sys.argv[1]
STATE_PATH = pathlib.Path("/pb/pb_data/restore-fixture.json")
TOKEN = "restore-fixture-token"


def state() -> dict:
    if not STATE_PATH.is_file():
        return {"collectionCounts": {}, "records": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    def write_json(self, status: int, payload: dict) -> None:
        rendered = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(rendered)))
        self.end_headers()
        self.wfile.write(rendered)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/api/health":
            self.write_json(200, {"ok": True, "service": MODE})
            return
        if MODE != "pocketbase" or self.headers.get("Authorization") != TOKEN:
            self.write_json(401, {"error": "unauthorized"})
            return
        parts = path.strip("/").split("/")
        if len(parts) == 5 and parts[:2] == ["api", "collections"] and parts[3] == "records":
            collection = parts[2]
            record = state().get("records", {}).get(collection, {}).get(parts[4])
            if isinstance(record, dict):
                self.write_json(200, record)
            else:
                self.write_json(404, {"error": "missing"})
            return
        if len(parts) == 4 and parts[:2] == ["api", "collections"] and parts[3] == "records":
            collection = parts[2]
            count = state().get("collectionCounts", {}).get(collection, 0)
            self.write_json(200, {"items": [], "totalItems": count})
            return
        self.write_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if MODE != "pocketbase" or self.path != "/api/collections/_superusers/auth-with-password":
            self.write_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if (
            payload.get("identity") == os.environ["PB_ADMIN_EMAIL"]
            and payload.get("password") == os.environ["PB_ADMIN_PASSWORD"]
        ):
            self.write_json(200, {"token": TOKEN})
        else:
            self.write_json(401, {"error": "invalid credentials"})

    def log_message(self, format: str, *args: object) -> None:
        return


PORT = 8090 if MODE == "pocketbase" else 8080
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
