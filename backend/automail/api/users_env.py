"""Environment-backed user display helpers."""

import os


def parse_users() -> list[dict]:
    """Parse USERS env var into list of {name, email} dicts."""
    raw = os.getenv("USERS", "")
    users = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            name, email = entry.split(":", 1)
            users.append({"name": name.strip(), "email": email.strip()})
        else:
            users.append({"name": entry, "email": entry})
    return users


def resolve_creator_name(email: str, tenant_id: str | None = None) -> str:
    """Resolve an email address to a configured display name."""
    try:
        from automail.db.pocketbase.users import get_user_display_name
        display_name = get_user_display_name(email, tenant_id=tenant_id)
        if display_name:
            return display_name
    except Exception:
        pass

    for user in parse_users():
        if user["email"].lower() == email.lower():
            return user["name"] if user["name"] != user["email"] else ""
    return ""
