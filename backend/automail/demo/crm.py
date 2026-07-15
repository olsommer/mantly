"""Demo CRM adapter backed by repo-root demo data."""

import json
import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path


def _demo_root() -> Path:
    return Path(os.getenv("DEMO_DATA_DIR", Path(__file__).resolve().parents[3] / "demo"))


@lru_cache(maxsize=1)
def _customers_by_email() -> dict[str, dict]:
    records = json.loads((_demo_root() / "crm" / "customers.json").read_text(encoding="utf-8"))
    return {str(record["email"]).strip().lower(): record for record in records}


def lookup_demo_customer(sender_email: str) -> dict:
    normalized_email = sender_email.strip().lower()
    record = _customers_by_email().get(normalized_email)

    if not record:
        return {
            "customerFound": False,
            "lookupEmail": normalized_email,
            "customerId": None,
            "fullName": None,
            "organization": None,
            "status": None,
            "segment": None,
            "preferredLanguage": None,
            "openMatters": [],
            "notes": [],
        }

    data = deepcopy(record)
    data.pop("email", None)
    return {"customerFound": True, "lookupEmail": normalized_email, **data}
