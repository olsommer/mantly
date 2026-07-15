import os


def demo_mode_enabled() -> bool:
    return os.getenv("ENABLE_DEMO_MODE", "false").strip().lower() == "true"


def is_saas_mode() -> bool:
    return os.getenv("IS_SAAS", "false").strip().lower() == "true"


def demo_routes_available() -> bool:
    return demo_mode_enabled() or is_saas_mode()
