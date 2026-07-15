from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

GMAIL_EXECUTE_SCOPE = "https://www.googleapis.com/auth/gmail.addons.execute"
GMAIL_CURRENT_MESSAGE_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.addons.current.message.readonly"
GMAIL_CURRENT_ACTION_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.addons.current.action.compose"
USERINFO_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"


class GmailAddonEventError(ValueError):
    """Raised when a Google Workspace add-on event is missing required context."""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_parameters(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(key): "" if value is None else str(value) for key, value in raw.items()}

    if isinstance(raw, list):
        normalized: dict[str, str] = {}
        for item in raw:
            if isinstance(item, dict) and "key" in item:
                normalized[str(item["key"])] = "" if item.get("value") is None else str(item.get("value"))
        return normalized

    return {}


@dataclass(slots=True)
class GmailAddonEvent:
    raw: dict[str, Any]
    message_id: str = ""
    thread_id: str = ""
    message_access_token: str = ""
    user_oauth_token: str = ""
    user_id_token: str = ""
    system_id_token: str = ""
    authorized_scopes: set[str] = field(default_factory=set)
    parameters: dict[str, str] = field(default_factory=dict)
    form_inputs: dict[str, Any] = field(default_factory=dict)
    host_app: str = ""
    platform: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "GmailAddonEvent":
        common = _as_dict(payload.get("commonEventObject"))
        authorization = _as_dict(payload.get("authorizationEventObject"))
        gmail = _as_dict(payload.get("gmail"))
        message_metadata = _as_dict(gmail.get("messageMetadata"))

        return cls(
            raw=payload,
            message_id=str(message_metadata.get("messageId") or gmail.get("messageId") or ""),
            thread_id=str(message_metadata.get("threadId") or gmail.get("threadId") or ""),
            message_access_token=str(message_metadata.get("accessToken") or gmail.get("accessToken") or ""),
            user_oauth_token=str(
                authorization.get("userOAuthToken")
                or authorization.get("userOauthToken")
                or common.get("userOAuthToken")
                or common.get("userOauthToken")
                or payload.get("userOAuthToken")
                or payload.get("userOauthToken")
                or ""
            ),
            user_id_token=str(authorization.get("userIdToken") or ""),
            system_id_token=str(authorization.get("systemIdToken") or ""),
            authorized_scopes=set(
                str(scope)
                for scope in authorization.get("authorizedScopes", [])
                if scope
            ),
            parameters=_normalize_parameters(common.get("parameters") or payload.get("parameters")),
            form_inputs=_as_dict(common.get("formInputs") or payload.get("formInputs")),
            host_app=str(common.get("hostApp") or ""),
            platform=str(common.get("platform") or ""),
        )

    @property
    def action(self) -> str:
        return self.parameters.get("action", "")

    def missing_scopes(self, required: list[str]) -> list[str]:
        # Empty means older/non-granular event shape or tests; do not block.
        if not self.authorized_scopes:
            return []
        return [scope for scope in required if scope not in self.authorized_scopes]

    def require_message_context(self) -> None:
        if not self.message_id:
            raise GmailAddonEventError("No Gmail message selected")

    def require_oauth_token(self) -> None:
        if not self.user_oauth_token:
            raise GmailAddonEventError("Gmail OAuth token missing")

    def form_string(self, name: str, default: str = "") -> str:
        value = self.form_inputs.get(name)
        if isinstance(value, str):
            return value
        if not isinstance(value, dict):
            return default

        string_inputs = _as_dict(value.get("stringInputs"))
        values = string_inputs.get("value")
        if isinstance(values, list) and values:
            return str(values[0])
        if isinstance(values, str):
            return values

        date_input = _as_dict(value.get("dateInput"))
        if "msSinceEpoch" in date_input:
            try:
                timestamp = int(date_input["msSinceEpoch"]) / 1000
                return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
            except (TypeError, ValueError, OSError):
                return str(date_input["msSinceEpoch"])

        return default
