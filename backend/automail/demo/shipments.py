"""Demo shipment-status adapter backed by repo-root demo data."""

import json
import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path


def _demo_root() -> Path:
    return Path(os.getenv("DEMO_DATA_DIR", Path(__file__).resolve().parents[3] / "demo"))


def _normalize_identifier(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


@lru_cache(maxsize=1)
def _shipment_records() -> list[dict]:
    return json.loads((_demo_root() / "shipments" / "statuses.json").read_text(encoding="utf-8"))


def lookup_demo_shipment_status(
    *,
    sender_email: str = "",
    order_number: str | None = None,
    tracking_number: str | None = None,
) -> dict:
    lookup_order = _normalize_identifier(order_number)
    lookup_tracking = _normalize_identifier(tracking_number)
    lookup_email = sender_email.strip().lower()

    for record in _shipment_records():
        order_match = lookup_order and _normalize_identifier(record.get("orderNumber")) == lookup_order
        tracking_match = lookup_tracking and _normalize_identifier(record.get("trackingNumber")) == lookup_tracking
        if not order_match and not tracking_match:
            continue

        data = deepcopy(record)
        return {
            "shipmentFound": True,
            "lookup": {
                "senderEmail": lookup_email,
                "orderNumber": order_number or "",
                "trackingNumber": tracking_number or "",
                "matchedBy": "order_number" if order_match else "tracking_number",
            },
            **data,
        }

    return {
        "shipmentFound": False,
        "lookup": {
            "senderEmail": lookup_email,
            "orderNumber": order_number or "",
            "trackingNumber": tracking_number or "",
            "matchedBy": None,
        },
        "status": "not_found" if (lookup_order or lookup_tracking) else "missing_identifier",
    }
