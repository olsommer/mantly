"""Application brand settings loaded from the repo-level brand.json file."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Brand:
    name: str
    short_name: str
    admin_title: str
    addin_display_name: str
    provider_name: str
    description: str
    description_de: str
    support_email: str
    support_url: str


_DEFAULT_BRAND = {
    "name": "Mantly",
    "shortName": "Mantly",
    "adminTitle": "Mantly Admin",
    "addinDisplayName": "Mantly",
    "providerName": "Mantly",
    "description": "AI-powered email assistant",
    "descriptionDe": "KI-gestützter E-Mail-Assistent für professionelle Teams",
    "supportEmail": "support@mantly.io",
    "supportUrl": "https://mantly.io",
}


def _brand_path() -> Path:
    return Path(os.getenv("APP_BRAND_PATH", Path(__file__).resolve().parents[3] / "brand.json"))


def _load_brand_data() -> dict:
    data = dict(_DEFAULT_BRAND)
    path = _brand_path()
    if path.exists():
        try:
            file_data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(file_data, dict):
                data.update(file_data)
        except (OSError, json.JSONDecodeError):
            pass

    env_map = {
        "APP_BRAND_NAME": "name",
        "APP_BRAND_SHORT_NAME": "shortName",
        "APP_BRAND_ADMIN_TITLE": "adminTitle",
        "APP_BRAND_ADDIN_DISPLAY_NAME": "addinDisplayName",
        "APP_BRAND_PROVIDER_NAME": "providerName",
        "APP_BRAND_DESCRIPTION": "description",
        "APP_BRAND_DESCRIPTION_DE": "descriptionDe",
        "APP_BRAND_SUPPORT_EMAIL": "supportEmail",
        "APP_BRAND_SUPPORT_URL": "supportUrl",
    }
    for env_name, key in env_map.items():
        value = os.getenv(env_name, "").strip()
        if value:
            data[key] = value
    return data


@lru_cache(maxsize=1)
def get_brand() -> Brand:
    data = _load_brand_data()
    return Brand(
        name=data["name"],
        short_name=data["shortName"],
        admin_title=data["adminTitle"],
        addin_display_name=data["addinDisplayName"],
        provider_name=data["providerName"],
        description=data["description"],
        description_de=data["descriptionDe"],
        support_email=data["supportEmail"],
        support_url=data["supportUrl"],
    )
